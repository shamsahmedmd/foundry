# Setup

## Prerequisites

- An Azure subscription, with quota for the model in `infra/main.*.bicepparam` (default
  `gpt-4.1-mini`, GlobalStandard) in the region you choose.
- Azure CLI 2.80 or later (`az bicep` included), Python 3.10 or later, and a bash shell
  (Git Bash or WSL on Windows).
- For the one-time setup only: **Owner** (or Contributor + User Access Administrator) on
  the subscription, and permission to create Entra app registrations.
- A GitHub repository for the client, with admin rights to configure environments.

## 1. Provision the Foundry environments

```bash
az login
az account set -s <subscription-id>
# Edit infra/main.{dev,test,prod}.bicepparam (prefix, region, model, capacity, tags)
PREFIX=contoso LOCATION=eastus2 ./infra/scripts/deploy-infra.sh
```

Each environment gets its own resource group, `rg-<prefix>-agents-<env>`, containing:
- a Foundry account (`disableLocalAuth: true`, so API keys don't work)
- project `proj-<env>`
- the model deployment
- Log Analytics
- Application Insights, connected to the project for tracing

## 2. Connect GitHub with OIDC

```bash
GITHUB_REPO=<org>/<repo> PREFIX=contoso ./infra/scripts/setup-github-oidc.sh
# Add APPLY_WITH_GH=true to create the environments and variables with the gh CLI
```

The script creates `<prefix>-agents-dev`, `-test` and `-prod` app registrations. Each
one:
- has a federated credential for `repo:<org>/<repo>:environment:<env>` only (no secrets)
- gets **Foundry Project Manager** on its own project, to create and route agent versions
- gets **Cognitive Services OpenAI User** on its own account, for the evaluation judge model

Then, in the GitHub repository settings:

1. **Variables** (Settings → Secrets and variables → Actions → Variables):
   - Repository: `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
   - Environments `dev`, `test` and `prod`: `AZURE_CLIENT_ID`, `FOUNDRY_PROJECT_ENDPOINT`,
     `AZURE_OPENAI_ENDPOINT`, `EVAL_MODEL_DEPLOYMENT`
2. **Environments** (Settings → Environments):
   - `dev`: no protection.
   - `test`: *Required reviewers* (the human-in-the-loop validation step).
   - `prod`: *Required reviewers*, *Prevent self-review*, and *Deployment branches:
     selected branches → `main`*.
3. **Branch protection** on `main`: require pull requests and the `CI · validate & test`
   status check.

## 3. Token baseline (before the first Test run)

The `test` gate fails if token usage per query grows more than 20% over a baseline. On the
first run there isn't one, so either:
- after the first successful Dev run, download the `eval-dev` artefact and commit
  `dev-results.json` as `eval/baselines/test.json`; or
- temporarily set `max_token_regression: null` in the `test` profile of
  `config/eval_gates.yaml`, and restore it once you've committed a baseline.

## 4. First run

Push to `main` or run **agent-cicd** from the Actions tab. The first deployment creates the
agent in each project. Later runs create new versions and move the endpoint to them.

## Running the scripts locally

```bash
az login
export FOUNDRY_PROJECT_ENDPOINT=<dev project endpoint>
export AZURE_OPENAI_ENDPOINT=<dev openai endpoint> EVAL_MODEL_DEPLOYMENT=gpt-4.1-mini
python scripts/build_manifest.py
python scripts/deploy_agent.py --env dev
python scripts/run_evaluations.py --dataset eval/datasets/golden_set.jsonl --output eval/results/local.json
python scripts/check_eval_gates.py --results eval/results/local.json --profile ci
```

Your own account needs the same roles on the Dev project as the pipeline identity.
