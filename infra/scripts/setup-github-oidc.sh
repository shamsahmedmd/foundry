#!/usr/bin/env bash
# Create one Entra app registration per environment, each with a GitHub OIDC federated
# credential and least-privilege RBAC on that environment only. No client secrets.
#
#   GITHUB_REPO=contoso/support-agent PREFIX=contoso ./infra/scripts/setup-github-oidc.sh
#   APPLY_WITH_GH=true ...   # also write the GitHub variables/environments with the gh CLI
#
# Identity                 Federated subject                  Roles (scoped to that env only)
# <prefix>-agents-<env>    repo:<repo>:environment:<env>      Foundry Project Manager on the project
#                                                             Cognitive Services OpenAI User on the account (eval judge)
#
# Dev credentials can never deploy to Test or Production.
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:?set GITHUB_REPO=owner/repo}"
PREFIX="${PREFIX:?set PREFIX, e.g. contoso}"
ENVIRONMENTS="${ENVIRONMENTS:-dev test prod}"
EVAL_MODEL_DEPLOYMENT="${EVAL_MODEL_DEPLOYMENT:-gpt-4.1-mini}"

TENANT_ID=$(az account show --query tenantId -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

create_identity() {  # name subject -> prints appId
  local name=$1 subject=$2 app_id
  app_id=$(az ad app list --display-name "$name" --query "[0].appId" -o tsv)
  if [ -z "$app_id" ]; then
    app_id=$(az ad app create --display-name "$name" --query appId -o tsv)
    az ad sp create --id "$app_id" -o none
  fi
  if ! az ad app federated-credential list --id "$app_id" --query "[?subject=='$subject']" -o tsv | grep -q .; then
    az ad app federated-credential create --id "$app_id" --parameters "{
      \"name\": \"github-$(echo "$subject" | tr -c 'a-zA-Z0-9' '-' | cut -c1-100)\",
      \"issuer\": \"https://token.actions.githubusercontent.com\",
      \"subject\": \"$subject\",
      \"audiences\": [\"api://AzureADTokenExchange\"]
    }" -o none
  fi
  echo "$app_id"
}

assign() {  # appId scope role [fallback-role]
  local sp; sp=$(az ad sp show --id "$1" --query id -o tsv)
  az role assignment create --assignee-object-id "$sp" --assignee-principal-type ServicePrincipal \
    --scope "$2" --role "$3" -o none 2>/dev/null \
  || { [ -n "${4:-}" ] && az role assignment create --assignee-object-id "$sp" --assignee-principal-type ServicePrincipal \
    --scope "$2" --role "$4" -o none; }
}

output() {  # deployment-outputs-json key
  echo "$1" | python -c "import sys,json;print(json.load(sys.stdin)['$2']['value'])"
}

declare -A CLIENT_IDS ENDPOINTS OPENAI
for ENV in $ENVIRONMENTS; do
  echo "== $ENV"
  OUT=$(az deployment group show -g "rg-${PREFIX}-agents-${ENV}" -n "foundry-${ENV}" --query properties.outputs -o json)
  PROJECT_ID=$(output "$OUT" projectResourceId)
  ACCOUNT_ID="${PROJECT_ID%/projects/*}"
  ENDPOINTS[$ENV]=$(output "$OUT" foundryProjectEndpoint)
  OPENAI[$ENV]=$(output "$OUT" azureOpenAiEndpoint)

  APP=$(create_identity "${PREFIX}-agents-${ENV}" "repo:${GITHUB_REPO}:environment:${ENV}")
  # Role was renamed from "Azure AI Project Manager"; same role ID.
  assign "$APP" "$PROJECT_ID" "Foundry Project Manager" "Azure AI Project Manager"
  assign "$APP" "$ACCOUNT_ID" "Cognitive Services OpenAI User"
  CLIENT_IDS[$ENV]=$APP
done

cat <<EOF

================ Configure GitHub ================
Repository variables (Settings > Secrets and variables > Actions > Variables):
  AZURE_TENANT_ID        = $TENANT_ID
  AZURE_SUBSCRIPTION_ID  = $SUBSCRIPTION_ID
EOF
for ENV in $ENVIRONMENTS; do
cat <<EOF
Environment "$ENV" variables:
  AZURE_CLIENT_ID          = ${CLIENT_IDS[$ENV]}
  FOUNDRY_PROJECT_ENDPOINT = ${ENDPOINTS[$ENV]}
  AZURE_OPENAI_ENDPOINT    = ${OPENAI[$ENV]}
  EVAL_MODEL_DEPLOYMENT    = $EVAL_MODEL_DEPLOYMENT
EOF
done
echo
echo "Then add Required reviewers to the 'test' and 'prod' environments and restrict 'prod' to the main branch."

if [ "${APPLY_WITH_GH:-false}" = "true" ] && command -v gh >/dev/null; then
  gh variable set AZURE_TENANT_ID -R "$GITHUB_REPO" -b "$TENANT_ID"
  gh variable set AZURE_SUBSCRIPTION_ID -R "$GITHUB_REPO" -b "$SUBSCRIPTION_ID"
  for ENV in $ENVIRONMENTS; do
    gh api -X PUT "repos/$GITHUB_REPO/environments/$ENV" >/dev/null
    gh variable set AZURE_CLIENT_ID -R "$GITHUB_REPO" -e "$ENV" -b "${CLIENT_IDS[$ENV]}"
    gh variable set FOUNDRY_PROJECT_ENDPOINT -R "$GITHUB_REPO" -e "$ENV" -b "${ENDPOINTS[$ENV]}"
    gh variable set AZURE_OPENAI_ENDPOINT -R "$GITHUB_REPO" -e "$ENV" -b "${OPENAI[$ENV]}"
    gh variable set EVAL_MODEL_DEPLOYMENT -R "$GITHUB_REPO" -e "$ENV" -b "$EVAL_MODEL_DEPLOYMENT"
  done
  echo "GitHub variables and environments created with gh (reviewers still need to be added in the UI)."
fi
