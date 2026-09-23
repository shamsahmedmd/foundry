"""Run an evaluation dataset against the deployed agent and write gate metrics.

    python scripts/run_evaluations.py \
        --dataset eval/datasets/golden_set.jsonl \
        --output  eval/results/results.json \
        --foundry-endpoint $FOUNDRY_PROJECT_ENDPOINT

Dataset rows (JSONL):
    {"query": "...", "context": "facts the answer must be grounded in",
     "must_contain": ["..."], "must_not_contain": ["..."], "category": "orders"}

Metrics (see eval_metrics.aggregate):
    quality     task_completion_rate, hallucination_rate   (azure-ai-evaluation Relevance/Groundedness)
    safety      grounded_response_rate, policy_violations  (azure-ai-evaluation ContentSafetyEvaluator)
    performance latency_p95_ms, avg_tokens_per_query, token_regression vs. --baseline

Judge model: AZURE_OPENAI_ENDPOINT + EVAL_MODEL_DEPLOYMENT (keyless, Entra ID auth).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from eval_metrics import aggregate
from foundry_common import (
    append_summary,
    fail,
    load_agent_config,
    log,
    project_client,
    resolve_endpoint,
    routed_version,
)


def load_dataset(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                row = json.loads(line)
                if "query" not in row:
                    fail(f"{path}:{i} has no 'query'")
                rows.append(row)
    if not rows:
        fail(f"{path} is empty")
    return rows


def call_agent(openai_client, row: dict[str, Any]) -> dict[str, Any]:
    record = {
        "query": row["query"],
        "category": row.get("category"),
        "context": row.get("context"),
        "must_contain": row.get("must_contain", []),
        "must_not_contain": row.get("must_not_contain", []),
    }
    start = time.perf_counter()
    try:
        response = openai_client.responses.create(input=row["query"])
        record["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        record["response"] = response.output_text or ""
        usage = getattr(response, "usage", None)
        record["total_tokens"] = getattr(usage, "total_tokens", None) if usage else None
    except Exception as exc:  # noqa: BLE001 - every failure is recorded as an errored row
        record["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        record["response"] = ""
        record["error"] = f"{type(exc).__name__}: {exc}"[:500]
    return record


def build_evaluators(project_endpoint: str, skip_quality: bool, skip_safety: bool) -> dict[str, Any]:
    evaluators: dict[str, Any] = {}
    if skip_quality and skip_safety:
        return evaluators

    from azure.ai.evaluation import (
        AzureOpenAIModelConfiguration,
        ContentSafetyEvaluator,
        GroundednessEvaluator,
        RelevanceEvaluator,
    )
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    if not skip_quality:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        deployment = os.environ.get("EVAL_MODEL_DEPLOYMENT")
        if not endpoint or not deployment:
            fail("AZURE_OPENAI_ENDPOINT and EVAL_MODEL_DEPLOYMENT must be set for quality evaluators")
        # No api_key: the judge model is called with Entra ID (keyless).
        model_config = AzureOpenAIModelConfiguration(azure_endpoint=endpoint, azure_deployment=deployment)
        evaluators["groundedness"] = GroundednessEvaluator(model_config, credential=credential)
        evaluators["relevance"] = RelevanceEvaluator(model_config, credential=credential)
    if not skip_safety:
        evaluators["safety"] = ContentSafetyEvaluator(credential=credential, azure_ai_project=project_endpoint)
    return evaluators


def score_row(record: dict[str, Any], evaluators: dict[str, Any]) -> dict[str, Any]:
    if record.get("error"):
        return record
    query, response = record["query"], record["response"]
    try:
        if "relevance" in evaluators:
            record["relevance"] = evaluators["relevance"](query=query, response=response).get("relevance")
        if "groundedness" in evaluators and record.get("context"):
            out = evaluators["groundedness"](query=query, response=response, context=record["context"])
            record["groundedness"] = out.get("groundedness")
            record["groundedness_reason"] = out.get("groundedness_reason")
        if "safety" in evaluators:
            record["safety"] = evaluators["safety"](query=query, response=response)
    except Exception as exc:  # noqa: BLE001
        record["evaluator_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return record


def summary_markdown(title: str, metrics: dict[str, Any]) -> str:
    def fmt(v: Any) -> str:
        if v is None:
            return "n/a"
        return f"{v:.3f}" if isinstance(v, float) else str(v)

    lines = [f"### Evaluation: {title}", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {fmt(v)} |" for k, v in metrics.items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--config", default="agent.yaml")
    parser.add_argument("--agent-name")
    parser.add_argument("--baseline", help="Previous results.json used to detect token-usage regression")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--skip-quality", action="store_true", help="Skip AI-assisted quality evaluators")
    parser.add_argument("--skip-safety", action="store_true", help="Skip content safety evaluator")
    args = parser.parse_args()

    endpoint = resolve_endpoint(args.foundry_endpoint)
    name = args.agent_name or load_agent_config(args.config)["name"]
    dataset = load_dataset(args.dataset)
    client = project_client(endpoint)
    version = routed_version(client, name)
    log(f"evaluating {name} v{version} with {len(dataset)} rows from {args.dataset}")

    openai_client = client.get_openai_client(agent_name=name)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        records = list(pool.map(lambda r: call_agent(openai_client, r), dataset))

    evaluators = build_evaluators(endpoint, args.skip_quality, args.skip_safety)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        records = list(pool.map(lambda r: score_row(r, evaluators), records))

    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")).get("metrics")

    metrics = aggregate(records, baseline)
    result = {
        "agent_name": name,
        "agent_version": version,
        "dataset": args.dataset,
        "evaluated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "evaluators": sorted(evaluators),
        "metrics": metrics,
        **metrics,  # flat copy so simple tooling can read results["hallucination_rate"]
        "rows": records,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    summary = summary_markdown(f"{name} v{version} — {Path(args.dataset).name}", metrics)
    append_summary(summary)
    print(summary)
    errors = [r for r in records if r.get("evaluator_error")]
    if errors:
        log(f"WARNING: {len(errors)} row(s) had evaluator errors; see {args.output}")


if __name__ == "__main__":
    main()
