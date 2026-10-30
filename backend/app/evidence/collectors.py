"""Modular evidence collectors for FixLoop diagnostic engine.

Collects and normalizes evidence from:
- Application logs
- Docker container state & healthcheck results
- Docker Compose configuration
- Application source files in approved repository
- Service ports & endpoint response codes
- Environment-variable presence (zero secret disclosure)

Enforces strict boundary validation: never inspects arbitrary filesystem paths.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from backend.app.core.models import (
    EvidenceItem,
    EvidenceType,
)

logger = logging.getLogger(__name__)


def compute_fingerprint(content: str) -> str:
    """Computes a deterministic SHA256 hex digest snippet for evidence provenance."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# Common sensitive variable names that must always have their values masked
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(KEY|SECRET|TOKEN|PASS|AUTH|PWD|CREDENTIAL|PRIVATE|CERT|SIG|DATABASE_URL|DB_URL|DSN|CONN|URI)",
    re.IGNORECASE,
)


class SecurityBoundaryError(Exception):
    """Raised when an attempt is made to inspect an unauthorized filesystem path."""


class ApprovedPathValidator:
    """Enforces strict path boundaries to prevent arbitrary filesystem inspection."""

    @staticmethod
    def validate_and_resolve(root_path: Path, relative_file: str) -> Path:
        """Validates that relative_file is contained strictly within root_path.

        Prohibits directory traversal ('..'), absolute paths, Windows drive specifiers,
        and alternate data streams.
        """
        if not relative_file or not isinstance(relative_file, str):
            raise SecurityBoundaryError(
                "Relative file path must be a non-empty string."
            )

        # Disallow null bytes
        if "\0" in relative_file:
            raise SecurityBoundaryError("Null byte detected in path.")

        norm_str = relative_file.strip()
        if not norm_str:
            raise SecurityBoundaryError("Relative file path must be non-empty.")

        # Disallow Windows drive specifiers (e.g. C:) and alternate data streams (file:stream)
        if ":" in norm_str:
            raise SecurityBoundaryError(
                f"Drive letter or stream specifier forbidden in path: '{relative_file}'"
            )

        # Disallow directory traversal and leading root slashes
        if ".." in norm_str or norm_str.startswith(("/", "\\")):
            raise SecurityBoundaryError(
                f"Directory traversal or absolute path detected: '{relative_file}'"
            )

        # Explicitly verify with Path object
        p_obj = Path(norm_str)
        if p_obj.is_absolute():
            raise SecurityBoundaryError(f"Absolute path forbidden: '{relative_file}'")

        for part in p_obj.parts:
            if part in ("..", "/", "\\") or ":" in part:
                raise SecurityBoundaryError(
                    f"Invalid path component '{part}' in '{relative_file}'"
                )

        root_resolved = root_path.resolve()
        target_resolved = (root_resolved / p_obj).resolve()

        try:
            target_resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise SecurityBoundaryError(
                f"Path '{relative_file}' resolves outside approved root '{root_resolved}': {exc}"
            ) from exc

        return target_resolved


class LogCollector:
    """Collects and normalizes application logs."""

    @staticmethod
    def collect_from_text(
        logs_text: str, source_label: str = "logs.user"
    ) -> list[EvidenceItem]:
        """Normalizes raw logs text into labeled EvidenceItems."""
        if not logs_text or not logs_text.strip():
            return []

        lines = [line.strip() for line in logs_text.splitlines() if line.strip()]
        error_lines = [
            l
            for l in lines
            if any(
                k in l.upper()
                for k in ["ERROR", "CRITICAL", "EXCEPTION", "TRACEBACK", "FAIL"]
            )
        ]

        items = []
        tail_content = "\n".join(lines[-50:])
        # Item 1: Complete log tail
        items.append(
            EvidenceItem(
                id="ev-log-tail",
                type=EvidenceType.LOGS,
                source=source_label,
                content=tail_content,
                metadata={"total_lines": len(lines), "has_errors": bool(error_lines)},
                is_initial=True,
                collector="LogCollector",
                target=source_label,
                fingerprint=compute_fingerprint(tail_content),
                provenance_type="RUNTIME_OBSERVATION",
            )
        )

        # Item 2: Explicit error extracts if present
        if error_lines:
            err_content = "\n".join(error_lines[:15])
            items.append(
                EvidenceItem(
                    id="ev-log-errors",
                    type=EvidenceType.LOGS,
                    source=f"{source_label}:extracted_errors",
                    content=err_content,
                    metadata={"error_count": len(error_lines)},
                    is_initial=True,
                    collector="LogCollector",
                    target=f"{source_label}:errors",
                    fingerprint=compute_fingerprint(err_content),
                    provenance_type="RUNTIME_OBSERVATION",
                )
            )

        return items


class DockerStateCollector:
    """Extracts container status, exit codes, healthchecks, and port bindings."""

    @classmethod
    def collect_from_json(
        cls, json_text: str, source_label: str = "docker.inspect"
    ) -> list[EvidenceItem]:
        """Parses docker inspect JSON string and extracts EvidenceItems."""
        if not json_text or not json_text.strip():
            return []
        try:
            data = json.loads(json_text)
            return cls.collect_from_dict(data, source_label=source_label)
        except Exception as exc:
            logger.warning("Failed parsing docker inspect JSON: %s", exc)
            return []

    @staticmethod
    def collect_from_dict(
        inspect_data: Any, source_label: str = "docker.inspect"
    ) -> list[EvidenceItem]:
        if not inspect_data:
            return []

        if isinstance(inspect_data, list):
            inspect_data = inspect_data[0] if inspect_data else {}

        if not isinstance(inspect_data, dict):
            return []

        items = []
        state = inspect_data.get("State", {})
        network_settings = inspect_data.get("NetworkSettings", {})

        # Health state
        health = state.get("Health", {})
        health_status = health.get("Status", "none")
        health_log = health.get("Log", [])

        summary = {
            "status": state.get("Status"),
            "running": state.get("Running", False),
            "exit_code": state.get("ExitCode"),
            "oom_killed": state.get("OOMKilled", False),
            "health_status": health_status,
            "failing_streak": health.get("FailingStreak", 0),
            "published_ports": network_settings.get("Ports", {}),
        }

        state_content = json.dumps(summary, indent=2)
        items.append(
            EvidenceItem(
                id="ev-docker-state",
                type=EvidenceType.DOCKER_INSPECT,
                source=source_label,
                content=state_content,
                metadata=summary,
                is_initial=True,
                collector="DockerStateCollector",
                target="docker_inspect:State",
                fingerprint=compute_fingerprint(state_content),
                provenance_type="CONTAINER_METADATA",
            )
        )

        if health_log:
            last_check = health_log[-1]
            hl_content = f"ExitCode: {last_check.get('ExitCode')}, Output: {last_check.get('Output', '').strip()}"
            items.append(
                EvidenceItem(
                    id="ev-docker-healthlog",
                    type=EvidenceType.DOCKER_INSPECT,
                    source=f"{source_label}:health_log",
                    content=hl_content,
                    metadata={"exit_code": last_check.get("ExitCode")},
                    is_initial=True,
                    collector="DockerStateCollector",
                    target="docker_inspect:HealthLog",
                    fingerprint=compute_fingerprint(hl_content),
                    provenance_type="CONTAINER_METADATA",
                )
            )

        return items


class ComposeConfigCollector:
    """Collects and parses docker-compose.yml configuration."""

    @staticmethod
    def collect_from_yaml(
        compose_text: str, source_label: str = "compose.config"
    ) -> list[EvidenceItem]:
        if not compose_text or not compose_text.strip():
            return []

        try:
            parsed = yaml.safe_load(compose_text)
        except Exception as exc:
            return [
                EvidenceItem(
                    id="ev-compose-parse-error",
                    type=EvidenceType.COMPOSE_CONFIG,
                    source=source_label,
                    content=f"Invalid compose YAML: {exc}",
                    is_initial=True,
                )
            ]

        services = parsed.get("services", {}) if isinstance(parsed, dict) else {}
        items = []

        for svc_name, svc_conf in services.items():
            if not isinstance(svc_conf, dict):
                continue

            healthcheck = svc_conf.get("healthcheck", {})
            ports = svc_conf.get("ports", [])
            env_vars = svc_conf.get("environment", [])

            # Extract declared environment variable keys
            env_keys = []
            if isinstance(env_vars, list):
                for e in env_vars:
                    if isinstance(e, str) and "=" in e:
                        env_keys.append(e.split("=", 1)[0].strip())
                    elif isinstance(e, str):
                        env_keys.append(e.strip())
            elif isinstance(env_vars, dict):
                env_keys = list(env_vars.keys())

            spec = {
                "service": svc_name,
                "ports": ports,
                "healthcheck": healthcheck,
                "declared_env_keys": env_keys,
            }

            compose_content = json.dumps(spec, indent=2)
            items.append(
                EvidenceItem(
                    id=f"ev-compose-{svc_name}",
                    type=EvidenceType.COMPOSE_CONFIG,
                    source=f"{source_label}:{svc_name}",
                    content=compose_content,
                    metadata=spec,
                    is_initial=True,
                    collector="ComposeConfigCollector",
                    target=f"docker-compose.yml:{svc_name}",
                    fingerprint=compute_fingerprint(compose_content),
                    provenance_type="STATIC_ANALYSIS",
                )
            )

        return items


class SourceCodeCollector:
    """Extracts endpoint routes and listen ports from application source files."""

    @staticmethod
    def collect_routes_and_ports(
        files: dict[str, str], source_label: str = "source.code"
    ) -> list[EvidenceItem]:
        items = []
        for filename, content in files.items():
            discovered_routes = []
            discovered_ports = []

            # Match FastAPI / Flask routes
            route_matches = re.findall(
                r"@(?:app|router)\.(?:get|post|put|delete)\([\"']([^\"']+)[\"']",
                content,
            )
            if route_matches:
                discovered_routes.extend(list(dict.fromkeys(route_matches)))

            # Match common port bindings (e.g. port=8000, PORT = 8000, "8000")
            port_matches = re.findall(r"(?:port\s*=\s*|PORT\s*=\s*)(\d{2,5})", content)
            if port_matches:
                discovered_ports.extend(
                    list(dict.fromkeys([int(p) for p in port_matches]))
                )

            if discovered_routes or discovered_ports:
                meta = {
                    "filename": filename,
                    "routes": list(dict.fromkeys(discovered_routes)),
                    "ports": list(dict.fromkeys(discovered_ports)),
                }
                src_content = f"File '{filename}' declares routes: {meta['routes']} and ports: {meta['ports']}"
                items.append(
                    EvidenceItem(
                        id=f"ev-src-{Path(filename).stem}",
                        type=EvidenceType.SOURCE_CODE,
                        source=f"{source_label}:{filename}",
                        content=src_content,
                        metadata=meta,
                        is_initial=True,
                        collector="SourceCodeCollector",
                        target=filename,
                        fingerprint=compute_fingerprint(src_content),
                        provenance_type="STATIC_ANALYSIS",
                    )
                )

        return items


class EnvironmentCollector:
    """Audits environment variable presence WITHOUT revealing secret values."""

    @staticmethod
    def collect_presence(
        env_dict: dict[str, str],
        expected_keys: set[str] | None = None,
        source_label: str = "env.audit",
    ) -> list[EvidenceItem]:
        expected = expected_keys or set()
        present_keys = set(env_dict.keys())

        def _sanitize_env_val(val: Any) -> str:
            str_val = str(val)
            # Mask embedded credentials in URLs (e.g. postgres://user:password@host:port/db)
            sanitized = re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://\1:***@", str_val)
            # Mask bearer tokens or private key material
            if re.search(
                r"(bearer\s+[a-zA-Z0-9_\-\.]+|BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY)",
                sanitized,
                re.IGNORECASE,
            ):
                return "[PRESENT_SECRET_MASKED]"
            return sanitized[:20]

        safe_audit = {}
        for k in sorted(present_keys):
            if SENSITIVE_KEY_PATTERNS.search(k):
                safe_audit[k] = "[PRESENT_SECRET_MASKED]"
            else:
                safe_audit[k] = f"[PRESENT: {_sanitize_env_val(env_dict[k])}]"

        missing_from_expected = list(expected - present_keys)

        content_lines = [
            f"Configured variables ({len(present_keys)} present): {list(safe_audit.keys())}",
            f"Audit status: {json.dumps(safe_audit, indent=2)}",
        ]
        if missing_from_expected:
            content_lines.append(f"Missing expected variables: {missing_from_expected}")

        env_content = "\n".join(content_lines)
        return [
            EvidenceItem(
                id="ev-env-presence",
                type=EvidenceType.ENVIRONMENT,
                source=source_label,
                content=env_content,
                metadata={
                    "present_keys": list(present_keys),
                    "missing_expected": missing_from_expected,
                },
                is_initial=True,
                collector="EnvironmentCollector",
                target="container_env",
                fingerprint=compute_fingerprint(env_content),
                provenance_type="ENVIRONMENT_INSPECTION",
            )
        ]


class EvidenceCollectorHub:
    """Coordinates evidence collection across all modular collectors for a target project."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        if not self.project_root.exists() or not self.project_root.is_dir():
            raise SecurityBoundaryError(
                f"Approved project root directory does not exist: '{project_root}'"
            )

    def collect_all_initial(
        self,
        logs_override: str | None = None,
        inspect_override: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """Collects initial evidence from repository files and provided runtime metadata."""
        evidence: list[EvidenceItem] = []

        # 1. Logs
        logs_text = logs_override
        if not logs_text:
            log_file = self.project_root / "logs.txt"
            if log_file.exists():
                logs_text = log_file.read_text(encoding="utf-8", errors="replace")

        if logs_text:
            evidence.extend(
                LogCollector.collect_from_text(
                    logs_text, source_label=f"project:{self.project_root.name}:logs"
                )
            )

        # 2. Docker Inspect
        inspect_data = inspect_override
        if not inspect_data:
            inspect_file = self.project_root / "docker_inspect.json"
            if inspect_file.exists():
                try:
                    inspect_data = json.loads(inspect_file.read_text(encoding="utf-8"))
                except Exception:
                    inspect_data = None

        if inspect_data:
            evidence.extend(
                DockerStateCollector.collect_from_dict(
                    inspect_data,
                    source_label=f"docker:inspect:{self.project_root.name}",
                )
            )

        # 3. Docker Compose
        compose_file = self.project_root / "docker-compose.yml"
        declared_keys = set()
        if compose_file.exists():
            compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
            compose_items = ComposeConfigCollector.collect_from_yaml(
                compose_text, source_label=f"compose:{compose_file.name}"
            )
            evidence.extend(compose_items)
            for item in compose_items:
                declared_keys.update(item.metadata.get("declared_env_keys", []))

        # 4. Source Files (restricted to approved directory)
        source_files = {}
        for ext in [".py", ".js", ".ts"]:
            for p in self.project_root.glob(f"*{ext}"):
                if p.is_file():
                    source_files[p.name] = p.read_text(
                        encoding="utf-8", errors="replace"
                    )

        if source_files:
            evidence.extend(
                SourceCodeCollector.collect_routes_and_ports(
                    source_files, source_label=f"source:{self.project_root.name}"
                )
            )

        # 5. Environment variable audit
        # Extract environment from inspect if available
        env_dict = {}
        target_inspect = (
            inspect_data[0]
            if (isinstance(inspect_data, list) and inspect_data)
            else (inspect_data if isinstance(inspect_data, dict) else {})
        )
        if (
            target_inspect
            and "Config" in target_inspect
            and "Env" in target_inspect["Config"]
        ):
            for e in target_inspect["Config"]["Env"]:
                if "=" in e:
                    k, v = e.split("=", 1)
                    env_dict[k] = v

        evidence.extend(
            EnvironmentCollector.collect_presence(env_dict, expected_keys=declared_keys)
        )

        return evidence
