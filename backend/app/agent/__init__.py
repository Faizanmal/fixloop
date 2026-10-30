"""Diagnostic engine and autonomous agent package."""

from backend.app.agent.engine import (
    AuditLog,
    DeterministicFactAnalyzer,
    DiagnosticBudget,
    DiagnosticEngine,
    DiagnosticEngineResult,
    InvalidStateTransitionError,
    InvestigationEvent,
    InvestigationEventType,
    InvestigationState,
    SelectedTestRecord,
    normalize_test_signature,
)
from backend.app.agent.patcher import (
    APPROVED_PATCH_TARGETS,
    ControlledPatchGenerator,
    InsufficientEvidenceError,
    PatchProposal,
    PatchSecurityError,
    PatchValidator,
    PurePythonDiffPatcher,
)

__all__ = [
    "APPROVED_PATCH_TARGETS",
    "AuditLog",
    "ControlledPatchGenerator",
    "DeterministicFactAnalyzer",
    "DiagnosticBudget",
    "DiagnosticEngine",
    "DiagnosticEngineResult",
    "InsufficientEvidenceError",
    "InvalidStateTransitionError",
    "InvestigationEvent",
    "InvestigationEventType",
    "InvestigationState",
    "PatchProposal",
    "PatchSecurityError",
    "PatchValidator",
    "PurePythonDiffPatcher",
    "SelectedTestRecord",
    "normalize_test_signature",
]
