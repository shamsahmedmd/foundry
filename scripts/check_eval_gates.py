"""Fail the pipeline when evaluation results breach the gate thresholds.

    python scripts/check_eval_gates.py --results eval/results/results.json --profile ci
    python scripts/check_eval_gates.py --results eval/results/results.json \
        --max-hallucination 0.05 --min-task-completion 0.90 --max-latency-p95 4000

A metric that a threshold applies to but which was not computed (e.g. evaluators
skipped) fails the gate unless --allow-missing is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from foundry_common import REPO_ROOT, append_summary, load_yaml

GATES_FILE = REPO_ROOT / "config" / "eval_gates.yaml"

# threshold key -> (metric key, direction, label)
RULES: dict[str, tuple[str, str, str]] = {
    "max_hallucination_rate": ("hallucination_rate", "max", "Hallucination rate"),
    "min_task_completion_rate": ("task_completion_rate", "min", "Task completion rate"),
    "min_grounded_response_rate": ("grounded_response_rate", "min", "Grounded response rate"),
    "max_policy_violations": ("policy_violations", "max", "Policy violations"),
    "max_latency_p95_ms": ("latency_p95_ms", "max", "p95 latency (ms)"),
    "max_token_regression": ("token_regression", "max", "Token usage regression"),
    "max_error_rate": ("error_rate", "max", "Error rate"),
}


def load_profile(name: str | None, gates_file: Path = GATES_FILE) -> dict[str, Any]:
    if not name:
        return {}
    profiles = load_yaml(gates_file)["profiles"]
    if name not in profiles:
        raise SystemExit(f"Unknown gate profile '{name}'. Available: {', '.join(profiles)}")
    return dict(profiles[name])


def evaluate_gates(metrics: dict[str, Any], thresholds: dict[str, Any], allow_missing: bool = False) -> list[dict[str, Any]]:
    checks = []
    for key, limit in thresholds.items():
        if limit is None or key not in RULES:
            continue
        metric, direction, label = RULES[key]
        value = metrics.get(metric)
        if value is None:
            passed = allow_missing
            detail = "not computed" + (" (allowed)" if allow_missing else "")
        else:
            passed = value <= limit if direction == "max" else value >= limit
            detail = ""
        checks.append({"label": label, "metric": metric, "value": value, "limit": limit,
                       "direction": direction, "passed": passed, "detail": detail})
    return checks


def report(checks: list[dict[str, Any]], profile: str | None) -> str:
    rows = ["| Gate | Value | Threshold | Result |", "|---|---|---|---|"]
    for c in checks:
        value = "n/a" if c["value"] is None else (f"{c['value']:.3f}" if isinstance(c["value"], float) else c["value"])
        op = "≤" if c["direction"] == "max" else "≥"
        rows.append(f"| {c['label']} | {value} | {op} {c['limit']} | {'✅' if c['passed'] else '❌'} {c['detail']} |")
    return f"### Evaluation gates ({profile or 'custom'})\n\n" + "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", required=True)
    parser.add_argument("--profile", help="Profile from config/eval_gates.yaml (ci, test, prod)")
    parser.add_argument("--gates-file", default=str(GATES_FILE))
    parser.add_argument("--max-hallucination", type=float)
    parser.add_argument("--min-task-completion", type=float)
    parser.add_argument("--min-grounded", type=float)
    parser.add_argument("--max-policy-violations", type=int)
    parser.add_argument("--max-latency-p95", type=float)
    parser.add_argument("--max-token-regression", type=float)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    thresholds = load_profile(args.profile, Path(args.gates_file))
    overrides = {
        "max_hallucination_rate": args.max_hallucination,
        "min_task_completion_rate": args.min_task_completion,
        "min_grounded_response_rate": args.min_grounded,
        "max_policy_violations": args.max_policy_violations,
        "max_latency_p95_ms": args.max_latency_p95,
        "max_token_regression": args.max_token_regression,
    }
    thresholds.update({k: v for k, v in overrides.items() if v is not None})
    if not thresholds:
        raise SystemExit("No thresholds: pass --profile and/or explicit threshold flags")

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    metrics = results.get("metrics", results)
    checks = evaluate_gates(metrics, thresholds, args.allow_missing)
    markdown = report(checks, args.profile)
    append_summary(markdown)
    print(markdown)

    failures = [c for c in checks if not c["passed"]]
    if failures:
        for c in failures:
            print(f"GATE FAILED: {c['label']} = {c['value']} (limit {c['limit']}) {c['detail']}", file=sys.stderr)
        sys.exit(1)
    print("All evaluation gates passed — proceeding to deployment")


if __name__ == "__main__":
    main()
