# Operations runbook

The CLI commands below assume `az login` with an identity that has access to the target
project, and `FOUNDRY_PROJECT_ENDPOINT` set to that project's endpoint (or pass
`--foundry-endpoint`).

## What is live?

```bash
python scripts/get_active_version.py --env prod
```

Every deploy and promote job also writes the new version and the **previous version**
(the rollback target) to the workflow run summary. Each version's metadata records
`git_sha`, `instructions_sha256`, `environment`, `pipeline_run` and `promoted_from`, so
Prod v4 can be traced back to the exact commit and prompt.

## Roll back

Rolling back is instant: the previous version still exists, so only the endpoint routing
changes.

- **GitHub**: Actions → **agent-rollback** → *Run workflow* → choose the environment and
  the known-good version. You can also delete the bad version in the same run.
- **CLI**:

```bash
python scripts/promote_agent.py --from-env prod --to-env prod --agent-version <known-good>
python scripts/smoke_test.py
python scripts/delete_agent_version.py --agent-version <bad>   # refused while it serves traffic
```

The pipeline rolls back automatically when:
- the Test stage's smoke test, evaluation or gate fails after promotion, or
- the Production smoke test fails after promotion.

## Kill switch

Take the endpoint offline. This is reversible, and all versions are kept:

```bash
python scripts/enable_agent_endpoint.py --disable
python scripts/enable_agent_endpoint.py                  # bring it back
```

## A gate failed: what now?

1. Open the `eval-dev` or `eval-test` artefact from the run. `results.json` has each row's
   response, relevance and groundedness scores, `groundedness_reason`, safety scores,
   latency and any error. The run summary shows the gate table.
2. If it's a genuine regression, fix the prompt or config in a new PR.
3. If the dataset is wrong or out of date, fix the dataset in a PR, reviewed like code.
4. Don't loosen thresholds to force a release through. Changes to
   `config/eval_gates.yaml` need the owners listed in CODEOWNERS to approve.

## Refreshing the token baseline

After a release is accepted, download the `eval-test` artefact and commit it:

```bash
cp test-results.json eval/baselines/test.json
```

## Production monitoring

- Traces: Application Insights (connected to each project by the Bicep) → *Transaction
  search* / *Performance*, or the tracing view in the Foundry portal.
- Continuous evaluation: add a scheduled workflow (`on: schedule`) that runs
  `run_evaluations.py` against Prod with a dataset sampled from real traffic, then
  `check_eval_gates.py --profile prod`, and alerts on failure.
