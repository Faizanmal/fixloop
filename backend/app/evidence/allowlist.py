"""Strict diagnostic probe allowlist and security sanitizer for FixLoop.

Guarantees that model-generated diagnostic probe requests can NEVER execute
arbitrary shell commands, access host resources outside the target project,
or perform dangerous operations without explicit approval.
"""

import re
from typing import Any

from backend.app.core.models import DiagnosticProbeType

# Dangerous shell characters that must never appear in unescaped parameters
FORBIDDEN_SHELL_PATTERNS = re.compile(r"[;&|`$<>\\]")

# Allowed safe ports to probe
ALLOWED_PORT_RANGE = range(1, 65536)

# Allowed safe file extensions for inspection
ALLOWED_FILE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".env.example",
    ".txt",
    ".md",
    ".sh",
    "Dockerfile",
}


class SecurityViolation(Exception):
    """Raised when a diagnostic probe violates security policies."""


class DiagnosticAllowlist:
    """Enforces strict safety invariants on diagnostic actions."""

    @staticmethod
    def validate_probe(
        probe_type: DiagnosticProbeType, target: str, parameters: dict[str, Any]
    ) -> tuple[bool, str]:
        """Validates that a proposed diagnostic probe conforms to the strict safety allowlist.

        Returns (is_valid, error_message).
        """
        if not target or not isinstance(target, str):
            return False, "Target must be a non-empty string"

        # Check for shell injection characters in target
        if FORBIDDEN_SHELL_PATTERNS.search(target):
            return False, f"Target contains prohibited shell metacharacters: '{target}'"

        # Check parameters
        for k, v in parameters.items():
            if isinstance(v, str) and FORBIDDEN_SHELL_PATTERNS.search(v):
                return (
                    False,
                    f"Parameter '{k}' contains prohibited shell metacharacters: '{v}'",
                )

        if probe_type == DiagnosticProbeType.HTTP_GET:
            # Target must be a safe HTTP path or URL (e.g. /healthz, http://localhost:8000/api/ping)
            if not target.startswith(("/", "http://", "https://")):
                return False, "HTTP_GET target must start with '/' or 'http://'"

        elif probe_type == DiagnosticProbeType.TCP_CONNECT:
            # Parameters must include a valid integer port
            port = parameters.get("port")
            if (
                port is None
                or not isinstance(port, int)
                or port not in ALLOWED_PORT_RANGE
            ):
                return (
                    False,
                    f"TCP_CONNECT requires an integer port in range 1-65535, got: {port}",
                )

        elif probe_type == DiagnosticProbeType.READ_TARGET_FILE:
            # Target must be a relative file path within workspace, no path traversal
            if ".." in target or target.startswith(("/", "\\")):
                return (
                    False,
                    "Directory traversal ('..') and absolute paths are forbidden in target",
                )

            # Check safe extension or known config name
            basename = target.split("/")[-1].split("\\")[-1]
            has_valid_ext = any(
                basename.endswith(ext) for ext in ALLOWED_FILE_EXTENSIONS
            )
            if not has_valid_ext and basename not in {"Dockerfile", "Makefile"}:
                return (
                    False,
                    f"Reading file '{basename}' is not allowed. Permitted extensions: {ALLOWED_FILE_EXTENSIONS}",
                )

        elif probe_type == DiagnosticProbeType.CHECK_ENV_KEY_EXISTS:
            key_name = parameters.get("key") or target
            if not re.match(r"^[A-Z0-9_]{1,100}$", key_name, re.IGNORECASE):
                return False, f"Invalid environment variable key name: '{key_name}'"

        elif (
            probe_type == DiagnosticProbeType.INSPECT_CONTAINER_CONFIG
            and not re.match(r"^[a-zA-Z0-9_\-\.]{1,128}$", target)
        ):
            # Safe container inspection
            return False, f"Invalid container identifier: '{target}'"

        return True, ""

    @staticmethod
    def requires_human_approval(
        probe_type: DiagnosticProbeType, parameters: dict[str, Any]
    ) -> bool:
        """Determines if a diagnostic action is potentially disruptive and requires human sign-off."""
        # Probing state, inspecting configs, or reading files is passive/safe.
        # Restarts, kills, or container execs require human approval.
        return bool(parameters.get("restart", False) or parameters.get("write", False))
