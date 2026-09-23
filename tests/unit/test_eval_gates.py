import json
import subprocess
import sys

import pytest

from check_eval_gates import GATES_FILE, evaluate_gates, load_profile
from foundry_common import REPO_ROOT

GOOD = {
    "hallucination_rate": 0.01,
    "task_completion_rate": 0.97,
    "grounded_response_rate": 0.99,
    "policy_violations": 0,
    "latency_p95_ms": 2500,
    "token_regression": 0.05,
    "error_rate": 0.0,
}


@pytest.mark.parametrize("profile", ["ci", "test", "prod"])
def test_good_results_pass_every_profile(profile):
    assert all(c["passed"] for c in evaluate_gates(GOOD, load_profile(profile)))


@pytest.mark.parametrize(
    "metric,value",
    [
        ("hallucination_rate", 0.06),
        ("task_completion_rate", 0.80),
        ("grounded_response_rate", 0.90),
        ("policy_violations", 1),
        ("latency_p95_ms", 4500),
        ("error_rate", 0.10),
    ],
)
def test_ci_profile_blocks_regressions(metric, value):
    failed = [c for c in evaluate_gates({**GOOD, metric: value}, load_profile("ci")) if not c["passed"]]
    assert [c["metric"] for c in failed] == [metric]


def test_test_profile_is_stricter_than_ci():
    borderline = {**GOOD, "hallucination_rate": 0.04, "task_completion_rate": 0.92}
    assert all(c["passed"] for c in evaluate_gates(borderline, load_profile("ci")))
    assert not all(c["passed"] for c in evaluate_gates(borderline, load_profile("test")))


def test_token_regression_is_track_only_in_ci():
    assert all(c["passed"] for c in evaluate_gates({**GOOD, "token_regression": 0.5}, load_profile("ci")))
    assert not all(c["passed"] for c in evaluate_gates({**GOOD, "token_regression": 0.5}, load_profile("test")))


def test_missing_metric_fails_unless_allowed():
    metrics = {**GOOD, "hallucination_rate": None}
    assert not all(c["passed"] for c in evaluate_gates(metrics, load_profile("ci")))
    assert all(c["passed"] for c in evaluate_gates(metrics, load_profile("ci"), allow_missing=True))


def test_unknown_profile():
    with pytest.raises(SystemExit):
        load_profile("staging", GATES_FILE)


def test_cli_exit_codes(tmp_path):
    script = str(REPO_ROOT / "scripts" / "check_eval_gates.py")
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps({"metrics": GOOD}))
    bad.write_text(json.dumps({**GOOD, "hallucination_rate": 0.2}))  # flat format also accepted
    def run(f):
        cmd = [sys.executable, script, "--results", str(f), "--profile", "ci"]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    assert run(good).returncode == 0
    result = run(bad)
    assert result.returncode == 1
    assert "GATE FAILED: Hallucination rate" in result.stderr
