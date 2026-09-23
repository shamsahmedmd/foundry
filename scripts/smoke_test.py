"""Fast post-deploy smoke test: the endpoint answers and the answers look right.

    python scripts/smoke_test.py --foundry-endpoint $FOUNDRY_PROJECT_ENDPOINT
"""

from __future__ import annotations

import argparse

from eval_metrics import keyword_checks
from foundry_common import REPO_ROOT, fail, load_agent_config, log, project_client, resolve_endpoint
from run_evaluations import call_agent, load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--dataset", default=str(REPO_ROOT / "eval" / "datasets" / "smoke_set.jsonl"))
    parser.add_argument("--config", default="agent.yaml")
    args = parser.parse_args()

    name = load_agent_config(args.config)["name"]
    openai_client = project_client(resolve_endpoint(args.foundry_endpoint)).get_openai_client(agent_name=name)

    failures = 0
    for row in load_dataset(args.dataset):
        record = call_agent(openai_client, row)
        ok = not record.get("error") and record["response"].strip() and keyword_checks(
            record["response"], record["must_contain"], record["must_not_contain"]
        )
        log(f"[{'PASS' if ok else 'FAIL'}] {record['latency_ms']}ms  {row['query'][:60]!r}")
        if not ok:
            failures += 1
            log(f"       response={record['response'][:200]!r} error={record.get('error')}")
    if failures:
        fail(f"{failures} smoke test(s) failed")
    log("smoke tests passed")


if __name__ == "__main__":
    main()
