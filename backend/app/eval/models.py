"""Evaluation and benchmarking models for FixLoop.

Defines schemas for scenario results, agent comparisons, and measured vs estimated metrics.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class ScenarioEvaluationRecord(BaseModel):
    """Detailed evaluation record for a single scenario and agent."""
    scenario_id: str
    scenario_name: str
    scenario_category: str  # supported, insufficient_evidence, misleading_logs, contradictory_evidence, regression
    agent_type: str  # "fixloop" or "log_only_baseline"
    expected_root_cause_type: str
    identified_root_cause: str
    root_cause_accuracy: bool
    diagnostic_tests_required: int
    correct_insufficient_evidence_use: bool
    patch_generated: bool
    patch_applied_cleanly: bool
    actual_verification_success: bool
    false_claims_of_success: bool
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float  # [ESTIMATE] computed from measured tokens @ $0.35/1M tokens
    failures_and_retries: int
    notes: str = ""


class BenchmarkSummary(BaseModel):
    """Aggregated summary of metrics across all benchmark scenarios for an agent."""
    agent_type: str
    total_scenarios: int
    root_cause_accuracy_rate: float  # [MEASURED] 0.0 - 1.0
    total_diagnostic_probes: int  # [MEASURED]
    avg_diagnostic_probes_per_scenario: float  # [MEASURED]
    insufficient_evidence_accuracy_rate: float  # [MEASURED] 0.0 - 1.0
    patch_generation_rate: float  # [MEASURED]
    clean_patch_application_rate: float  # [MEASURED]
    actual_verification_success_rate: float  # [MEASURED]
    false_claims_of_success_count: int  # [MEASURED] Must be 0 for FixLoop
    avg_duration_ms: float  # [MEASURED]
    total_tokens_consumed: int  # [MEASURED]
    estimated_inference_cost_usd: float  # [ESTIMATE] based on published open-weights pricing
    total_retries: int  # [MEASURED]


class BenchmarkComparisonReport(BaseModel):
    """Complete comparative evaluation report between FixLoop and Baseline."""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pricing_basis: str = "Nebius Token Factory open-weights pricing @ $0.35 per 1,000,000 tokens"
    scenarios_evaluated: List[str]
    fixloop_summary: BenchmarkSummary
    baseline_summary: BenchmarkSummary
    detailed_results: List[ScenarioEvaluationRecord]
