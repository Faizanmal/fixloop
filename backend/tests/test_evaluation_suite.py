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

    # Invariant 5: Zero unnecessary tests executed by FixLoop
    assert report.fixloop_summary.total_unnecessary_tests == 0
    assert report.fixloop_summary.avg_unnecessary_tests_per_scenario == 0.0

    # Invariant 6: Patch verification rate of FixLoop strictly exceeds baseline
    assert report.fixloop_summary.patch_verification_rate >= 0.70
    assert report.baseline_summary.patch_verification_rate <= 0.30

    # Invariant 7: Methodology, limitations, and highest-impact recommendation are documented
    assert "identical_fixtures" in report.methodology
    assert len(report.limitations) >= 3
    assert "Adaptive Multi-Probe Batching" in report.highest_impact_recommendation.get("title", "")

    # Invariant 8: Exporting produces valid JSON and CSV reports (including summary CSV)
    export_reports(report, output_dir=tmp_path)
    json_file = tmp_path / "eval_results.json"
    csv_file = tmp_path / "eval_results.csv"
    summary_csv = tmp_path / "eval_summary.csv"

    assert json_file.exists() and json_file.stat().st_size > 500
    assert csv_file.exists() and csv_file.stat().st_size > 300
    assert summary_csv.exists() and summary_csv.stat().st_size > 200
