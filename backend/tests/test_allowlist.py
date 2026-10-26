"""Security tests verifying that DiagnosticAllowlist prevents command injection and unauthorized actions."""

import pytest
from backend.app.core.models import DiagnosticProbeType
from backend.app.evidence.allowlist import DiagnosticAllowlist


def test_valid_http_get_probe():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.HTTP_GET,
        target="/healthz",
        parameters={"port": 8000},
    )
    assert valid is True
    assert msg == ""


def test_block_shell_injection_in_target():
    # Attempt command chaining via semicolon
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.HTTP_GET,
        target="/healthz; rm -rf /",
        parameters={},
    )
    assert valid is False
    assert "prohibited shell metacharacters" in msg


def test_block_shell_injection_in_parameters():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.HTTP_GET,
        target="/healthz",
        parameters={"filter": "test && cat /etc/passwd"},
    )
    assert valid is False
    assert "prohibited shell metacharacters" in msg


def test_block_directory_traversal():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.READ_TARGET_FILE,
        target="../../etc/shadow",
        parameters={},
    )
    assert valid is False
    assert "Directory traversal" in msg


def test_block_unauthorized_file_extensions():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.READ_TARGET_FILE,
        target="payload.exe",
        parameters={},
    )
    assert valid is False
    assert "not allowed" in msg


def test_valid_file_inspection():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.READ_TARGET_FILE,
        target="docker-compose.yml",
        parameters={},
    )
    assert valid is True


def test_valid_env_key_check():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.CHECK_ENV_KEY_EXISTS,
        target="DATABASE_URL",
        parameters={"key": "DATABASE_URL"},
    )
    assert valid is True


def test_invalid_env_key_pattern():
    valid, msg = DiagnosticAllowlist.validate_probe(
        DiagnosticProbeType.CHECK_ENV_KEY_EXISTS,
        target="KEY`whoami`",
        parameters={"key": "KEY`whoami`"},
    )
    assert valid is False


def test_human_approval_detection():
    # Passive probe does not need approval
    assert not DiagnosticAllowlist.requires_human_approval(
        DiagnosticProbeType.HTTP_GET, {"port": 8000}
    )

    # Action that requests container restart requires approval
    assert DiagnosticAllowlist.requires_human_approval(
        DiagnosticProbeType.HTTP_GET, {"restart": True}
    )
