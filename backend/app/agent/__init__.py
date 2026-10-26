"""Diagnostic engine and autonomous agent package."""

from backend.app.agent.engine import (
    DiagnosticEngine,
    DiagnosticBudget,
    AuditLog,
    SelectedTestRecord,
    DiagnosticEngineResult,
    DeterministicFactAnalyzer,
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
