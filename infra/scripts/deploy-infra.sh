#!/usr/bin/env bash
# Provision the dev/test/prod Foundry environments (one resource group + project each).
# Run once (and again after infra changes) by a platform engineer with Owner /
# User Access Administrator on the target subscription or resource groups.
#
#   PREFIX=contoso LOCATION=eastus2 ./infra/scripts/deploy-infra.sh
set -euo pipefail

PREFIX="${PREFIX:?set PREFIX, e.g. contoso}"
LOCATION="${LOCATION:-eastus2}"
ENVIRONMENTS="${ENVIRONMENTS:-dev test prod}"
cd "$(dirname "$0")/.."

for ENV in $ENVIRONMENTS; do
  RG="rg-${PREFIX}-agents-${ENV}"
  az group create -n "$RG" -l "$LOCATION" -o none
  echo "Deploying $ENV into $RG ..."
  az deployment group create -g "$RG" -n "foundry-${ENV}" -f main.bicep -p "main.${ENV}.bicepparam" \
    -p namePrefix="$PREFIX" location="$LOCATION" -o none
  az deployment group show -g "$RG" -n "foundry-${ENV}" \
    --query "{projectEndpoint: properties.outputs.foundryProjectEndpoint.value, openAiEndpoint: properties.outputs.azureOpenAiEndpoint.value}" -o table
done

echo
echo "Next: GITHUB_REPO=<owner>/<repo> PREFIX=$PREFIX ./infra/scripts/setup-github-oidc.sh"
