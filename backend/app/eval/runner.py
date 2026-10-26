"""Benchmark evaluation runner for FixLoop.

Executes comparative benchmarks between FixLoop and Log-Only Baseline
across all standardized scenarios, generating machine-readable JSON and CSV.

Usage:
    python -m backend.app.eval.runner
"""

import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

from backend.app.eval.models import (
    BenchmarkComparisonReport,
    BenchmarkSummary,
    ScenarioEvaluationRecord,
)
from backend.app.eval.baseline import LogOnlyBaselineRunner
from backend.app.eval.fixloop_evaluator import FixLoopEvaluator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


class FixLoopBenchmarkRunner:
    """Executes deterministic benchmark suite across all scenarios."""

    def __init__(self, scenarios_dir: Path = SCENARIOS_DIR):
        self.scenarios_dir = scenarios_dir

    def discover_scenarios(self) -> List[Tuple[Path, dict]]:
        scenarios = []
        for entry in sorted(self.scenarios_dir.iterdir()):
            if entry.is_dir():
                manifest_file = entry / "manifest.json"
                if manifest_file.exists():
                    try:
                        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                        scenarios.append((entry, manifest))
                    except Exception as exc:
                        print(f"Warning: Failed loading manifest from {entry.name}: {exc}")
        return scenarios

    @staticmethod
    def compute_summary(records: List[ScenarioEvaluationRecord], agent_type: str) -> BenchmarkSummary:
        agent_records = [r for r in records if r.agent_type == agent_type]
        total = len(agent_records)
        if total == 0:
            raise ValueError(f"No records found for agent type: {agent_type}")

        accurate_count = sum(1 for r in agent_records if r.root_cause_accuracy)
        total_probes = sum(r.diagnostic_tests_required for r in agent_records)
        insufficient_records = [r for r in agent_records if r.scenario_category == "insufficient_evidence"]
        insufficient_accurate = sum(1 for r in insufficient_records if r.correct_insufficient_evidence_use)
        insufficient_rate = (insufficient_accurate / len(insufficient_records)) if insufficient_records else 1.0

        patches_gen = sum(1 for r in agent_records if r.patch_generated)
        clean_patches = sum(1 for r in agent_records if r.patch_applied_cleanly)
        verif_success = sum(1 for r in agent_records if r.actual_verification_success)
        false_claims = sum(1 for r in agent_records if r.false_claims_of_success)
        total_duration = sum(r.duration_ms for r in agent_records)
        total_tokens = sum(r.total_tokens for r in agent_records)
        total_cost = sum(r.estimated_cost_usd for r in agent_records)
        total_retries = sum(r.failures_and_retries for r in agent_records)

        return BenchmarkSummary(
            agent_type=agent_type,
            total_scenarios=total,
            root_cause_accuracy_rate=round(accurate_count / total, 3),
            total_diagnostic_probes=total_probes,
            avg_diagnostic_probes_per_scenario=round(total_probes / total, 2),
            insufficient_evidence_accuracy_rate=round(insufficient_rate, 3),
            patch_generation_rate=round(patches_gen / total, 3),
            clean_patch_application_rate=round(clean_patches / total, 3),
            actual_verification_success_rate=round(verif_success / total, 3),
            false_claims_of_success_count=false_claims,
            avg_duration_ms=round(total_duration / total, 1),
            total_tokens_consumed=total_tokens,
            estimated_inference_cost_usd=round(total_cost, 6),
            total_retries=total_retries,
        )

    async def run_benchmark(self) -> BenchmarkComparisonReport:
        scenarios = self.discover_scenarios()
        print(f"\nDiscovered {len(scenarios)} benchmark scenarios in '{self.scenarios_dir}':")
        for s_dir, s_man in scenarios:
            print(f"  - [{s_man.get('scenario_id')}] {s_man.get('name')}")

        all_records: List[ScenarioEvaluationRecord] = []

        print("\n" + "=" * 80)
        print("RUNNING BENCHMARK EVALUATION (FixLoop vs Log-Only Baseline)")
        print("=" * 80)

        for s_dir, s_man in scenarios:
            s_id = s_man.get("scenario_id")
            print(f"\nEvaluating: {s_id} ...")

            # 1. Run Log-Only Baseline
            baseline_rec = LogOnlyBaselineRunner.evaluate_scenario(s_dir, s_man)
            all_records.append(baseline_rec)
            print(f"  [Baseline] Accurate: {baseline_rec.root_cause_accuracy} | Cause: {baseline_rec.identified_root_cause} | FalseClaims: {baseline_rec.false_claims_of_success}")

            # 2. Run FixLoop
            fixloop_rec = await FixLoopEvaluator.evaluate_scenario(s_dir, s_man)
            all_records.append(fixloop_rec)
            print(f"  [FixLoop]  Accurate: {fixloop_rec.root_cause_accuracy} | Cause: {fixloop_rec.identified_root_cause} | Probes: {fixloop_rec.diagnostic_tests_required} | VerifSuccess: {fixloop_rec.actual_verification_success}")

        # Compute summaries
        fixloop_summary = self.compute_summary(all_records, "fixloop")
        baseline_summary = self.compute_summary(all_records, "log_only_baseline")

        report = BenchmarkComparisonReport(
            scenarios_evaluated=[s[1].get("scenario_id") for s in scenarios],
            fixloop_summary=fixloop_summary,
            baseline_summary=baseline_summary,
            detailed_results=all_records,
        )

        return report


def export_reports(report: BenchmarkComparisonReport, output_dir: Path = REPO_ROOT):
    # 1. Export JSON
    json_path = output_dir / "eval_results.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\n[OK] Machine-readable JSON saved to: {json_path}")

    # 2. Export CSV
    csv_path = output_dir / "eval_results.csv"
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Scenario ID",
            "Scenario Category",
            "Agent Type",
            "Expected Cause",
            "Identified Cause",
            "Root Cause Accuracy",
            "Diagnostic Tests Required",
            "Correct Insufficient Evidence",
            "Patch Generated",
            "Patch Applied Cleanly",
            "Actual Verification Success",
            "False Claims Of Success",
            "Duration (ms)",
            "Total Tokens",
            "Estimated Cost (USD)",
            "Failures/Retries",
            "Notes",
        ])
        for r in report.detailed_results:
            writer.writerow([
                r.scenario_id,
                r.scenario_category,
                r.agent_type,
                r.expected_root_cause_type,
                r.identified_root_cause,
                r.root_cause_accuracy,
                r.diagnostic_tests_required,
                r.correct_insufficient_evidence_use,
                r.patch_generated,
                r.patch_applied_cleanly,
                r.actual_verification_success,
                r.false_claims_of_success,
                r.duration_ms,
                r.total_tokens,
                r.estimated_cost_usd,
                r.failures_and_retries,
                r.notes,
            ])
    print(f"[OK] Machine-readable CSV saved to: {csv_path}")


def print_comparison_table(report: BenchmarkComparisonReport):
    f_sum = report.fixloop_summary
    b_sum = report.baseline_summary

    print("\n" + "=" * 90)
    print(f"{'EVALUATION BENCHMARK METRICS SUMMARY':^90}")
    print("=" * 90)
    print(f"{'Metric':<40} | {'FixLoop (Evidence-Driven)':<22} | {'Log-Only Baseline':<22}")
    print("-" * 90)
    print(f"{'Total Scenarios Evaluated':<40} | {f_sum.total_scenarios:<22} | {b_sum.total_scenarios:<22}")
    print(f"{'Root-Cause Accuracy Rate [MEASURED]':<40} | {f'{f_sum.root_cause_accuracy_rate * 100:.1f}%':<22} | {f'{b_sum.root_cause_accuracy_rate * 100:.1f}%':<22}")
    print(f"{'Avg Diagnostic Tests Required [MEASURED]':<40} | {f_sum.avg_diagnostic_probes_per_scenario:<22} | {b_sum.avg_diagnostic_probes_per_scenario:<22}")
    print(f"{'Insufficient Evidence Accuracy [MEASURED]':<40} | {f'{f_sum.insufficient_evidence_accuracy_rate * 100:.1f}%':<22} | {f'{b_sum.insufficient_evidence_accuracy_rate * 100:.1f}%':<22}")
    print(f"{'Clean Patch Application Rate [MEASURED]':<40} | {f'{f_sum.clean_patch_application_rate * 100:.1f}%':<22} | {f'{b_sum.clean_patch_application_rate * 100:.1f}%':<22}")
    print(f"{'Actual Verification Success Rate [MEASURED]':<40} | {f'{f_sum.actual_verification_success_rate * 100:.1f}%':<22} | {f'{b_sum.actual_verification_success_rate * 100:.1f}%':<22}")
    print(f"{'False Claims of Successful Fixes [MEASURED]':<40} | {f_sum.false_claims_of_success_count:<22} | {b_sum.false_claims_of_success_count:<22}")
    print(f"{'Avg Investigation Duration (ms) [MEASURED]':<40} | {f'{f_sum.avg_duration_ms:.1f} ms':<22} | {f'{b_sum.avg_duration_ms:.1f} ms':<22}")
    print(f"{'Total Tokens Consumed [MEASURED]':<40} | {f_sum.total_tokens_consumed:<22} | {b_sum.total_tokens_consumed:<22}")
    print(f"{'Estimated Inference Cost (USD) [ESTIMATE]':<40} | {f'${f_sum.estimated_inference_cost_usd:.6f}':<22} | {f'${b_sum.estimated_inference_cost_usd:.6f}':<22}")
    print(f"{'Failures & Verification Retries [MEASURED]':<40} | {f_sum.total_retries:<22} | {b_sum.total_retries:<22}")
    print("=" * 90)


async def main():
    runner = FixLoopBenchmarkRunner()
    report = await runner.run_benchmark()
    export_reports(report)
    print_comparison_table(report)


if __name__ == "__main__":
    asyncio.run(main())
