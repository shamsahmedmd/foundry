import pytest

from eval_metrics import aggregate, is_safety_violation, keyword_checks, percentile


def row(**kw):
    base = {"response": "It shipped.", "latency_ms": 100.0, "must_contain": [], "must_not_contain": []}
    return {**base, **kw}


def test_percentile():
    assert percentile([], 95) is None
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([5.0], 95) == 5.0


def test_keyword_checks_case_insensitive():
    assert keyword_checks("Returns within 30 DAYS", ["30 days"], [])
    assert not keyword_checks("Card 4111", [], ["4111"])


def test_safety_violation_threshold():
    assert not is_safety_violation({"violence_score": 3, "sexual_score": 0})
    assert is_safety_violation({"hate_unfairness_score": 4})
    assert not is_safety_violation(None)


def test_aggregate_quality_and_performance():
    rows = [
        row(groundedness=5, relevance=5, total_tokens=100, must_contain=["shipped"]),
        row(groundedness=2, relevance=4, total_tokens=300),                  # hallucinated
        row(groundedness=4, relevance=2, total_tokens=200, latency_ms=900),  # irrelevant -> not completed
        row(error="Timeout", response="", latency_ms=None),
    ]
    m = aggregate(rows, baseline={"avg_tokens_per_query": 100})
    assert m["row_count"] == 4
    assert m["error_rate"] == 0.25
    assert m["task_completion_rate"] == 0.5
    assert m["grounded_response_rate"] == pytest.approx(2 / 3)
    assert m["hallucination_rate"] == pytest.approx(1 / 3)
    assert m["latency_p95_ms"] == 900
    assert m["avg_tokens_per_query"] == 200
    assert m["token_regression"] == pytest.approx(1.0)
    assert m["policy_violations"] is None  # safety evaluator not run


def test_aggregate_counts_policy_violations():
    rows = [row(safety={"violence_score": 0}), row(safety={"self_harm_score": 6})]
    assert aggregate(rows)["policy_violations"] == 1


def test_aggregate_without_ai_evaluators_uses_keywords_only():
    m = aggregate([row(must_contain=["shipped"]), row(must_contain=["delivered"])])
    assert m["task_completion_rate"] == 0.5
    assert m["hallucination_rate"] is None
