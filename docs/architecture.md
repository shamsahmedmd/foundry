# Architecture notes & design decisions

## Layers (from the reference architecture)

| Layer | Implementation here |
|---|---|
| 1. Developer | `agent.yaml`, `prompts/`, eval datasets, `infra/` (Bicep), all in one GitHub repo |
| 2. CI | ruff, bandit, schema + secret validation, pytest, release manifest (no Docker build for prompt agents) |
| 3. CD | Dev → Test → Prod Foundry projects; evaluation gates, GitHub Environment approvals, automatic rollback |
| 4. Agent Service | Prompt agent versions (`PromptAgentDefinition`); the endpoint routes 100% of traffic to one version |
| 5. Governance | Per-environment RBAC and OIDC identities, version metadata as the audit trail, App Insights tracing, CODEOWNERS on gates and prompts |

## Promotion model

Foundry agent versions belong to a project, so a version can't be "moved" between
projects. Promotion here means:

1. CI creates `release/manifest.json`, containing the agent config, the full prompt text,
   its SHA-256 and the git SHA. The manifest is uploaded as a workflow artefact.
2. Every stage deploys **that file** with `create_version` in its own project, and
   `update_details` routes the endpoint to the new version. Version metadata records the
   provenance.
3. `load_manifest` refuses a manifest whose prompt doesn't match its recorded hash.
4. `promote_agent.py --source-endpoint` can also check that the source version's metadata
   matches the manifest. The workflow skips this check because the manifest comes from the
   same run, and giving the Test identity read access to Dev would weaken isolation. Use the
   flag for manual promotions.

Version numbers differ between projects (Dev v12 might be Prod v4). The git SHA and prompt
hash in the metadata connect them.

## Why evaluation runs after the Dev deploy, not on the PR

The article puts an evaluation gate in CI. Here it runs in the Dev stage, against the
deployed version, for these reasons:

- The result then reflects the real model deployment, the tools and the content filters.
- The pipeline doesn't need to evaluate an agent version that isn't routed yet.

Nothing reaches Test or Prod without passing the gate. To also gate merges, add a PR job
that deploys to a separate `pr` Foundry project (its own environment and identity) and runs
`run_evaluations.py` + `check_eval_gates.py --profile ci`. The scripts support this without
changes.

## Security

- No long-lived credentials. GitHub OIDC federated credentials are scoped to
  `environment:<env>`, so each environment's identity only works in jobs that target that
  environment, and only has roles on its own project.
- Foundry accounts use `disableLocalAuth: true`, so API keys don't work. The evaluation
  judge model is also called with Entra ID.
- The validator rejects secret-looking strings in the prompt and tool definitions.
- CODEOWNERS covers the gates, datasets, prompts, workflows and infra.

## Known limitations

- **Private networking** is not configured. Add private endpoints and a VNet to
  `main.bicep` if the client needs them. The pipeline would then need self-hosted runners
  inside the network.
- **Traffic splitting / canary** isn't supported by Foundry agent endpoints: routing is 100%
  to one version.
- Pin exact package versions (`pip-compile`) once the client's environment is validated.
