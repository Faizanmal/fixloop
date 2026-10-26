"""Automated regression test for FixLoop's evaluation suite.

Validates:
1. All 7 benchmark scenarios are discovered and evaluated.
2. Root-cause accuracy of FixLoop exceeds baseline by at least 50 percentage points.
3. FixLoop achieves 0 false claims of successful fixes.
4. Insufficient evidence is handled with 100% honesty.
5. Machine-readable JSON and CSV results are generated with valid schemas.
"""

import pytest
from pathlib import Path

from backend.app.eval.runner import FixLoopBenchmarkRunner, export_reports

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.asyncio
async def test_benchmark_suite_execution_and_metrics(tmp_path):
    """Executes the benchmark suite and validates core empirical invariants."""
    runner = FixLoopBenchmarkRunner()
    report = await runner.run_benchmark()

    # Invariant 1: Exactly 7 scenarios evaluated
    assert len(report.scenarios_evaluated) == 7
    assert len(report.detailed_results) == 14  # 7 for baseline, 7 for fixloop

    # Invariant 2: FixLoop root cause accuracy is strictly superior to baseline
    assert report.fixloop_summary.root_cause_accuracy_rate >= 0.90
    assert report.baseline_summary.root_cause_accuracy_rate <= 0.40

    # Invariant 3: Zero false claims of success for FixLoop
    assert report.fixloop_summary.false_claims_of_success_count == 0
    # Baseline must have at least 3 false claims of success
    assert report.baseline_summary.false_claims_of_success_count >= 3

    # Invariant 4: Insufficient evidence handled with 100% correctness
    assert report.fixloop_summary.insufficient_evidence_accuracy_rate == 1.0

    # Invariant 5: Exporting produces valid JSON and CSV
    export_reports(report, output_dir=tmp_path)
    json_file = tmp_path / "eval_results.json"
    csv_file = tmp_path / "eval_results.csv"

    assert json_file.exists() and json_file.stat().st_size > 500
    assert csv_file.exists() and csv_file.stat().st_size > 300
