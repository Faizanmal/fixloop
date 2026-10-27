"""Diagnostic engine and autonomous agent package."""

from backend.app.agent.engine import (
    DiagnosticEngine,
    DiagnosticBudget,
    AuditLog,
    SelectedTestRecord,
    DiagnosticEngineResult,
    DeterministicFactAnalyzer,
    InvestigationState,
    InvestigationEventType,
    InvestigationEvent,
    InvalidStateTransitionError,
    normalize_test_signature,
)
from backend.app.agent.patcher import (
    PatchProposal,
    PatchValidator,
    PurePythonDiffPatcher,
    ControlledPatchGenerator,
    InsufficientEvidenceError,
    PatchSecurityError,
    APPROVED_PATCH_TARGETS,
)
