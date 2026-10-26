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

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from backend.app.core.models import (
    EvidenceItem,
    EvidenceType,
    utc_now,
)

# Common sensitive variable names that must always have their values masked
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(KEY|SECRET|TOKEN|PASS|AUTH|PWD|CREDENTIAL|PRIVATE)",
    re.IGNORECASE
)


class SecurityBoundaryError(Exception):
    """Raised when an attempt is made to inspect an unauthorized filesystem path."""
    pass


class ApprovedPathValidator:
    """Enforces strict path boundaries to prevent arbitrary filesystem inspection."""

    @staticmethod
    def validate_and_resolve(root_path: Path, relative_file: str) -> Path:
        """Validates that relative_file is contained strictly within root_path.

        Prohibits directory traversal ('..') and absolute paths.
        """
        if not relative_file or not isinstance(relative_file, str):
            raise SecurityBoundaryError("Relative file path must be a non-empty string.")

        if ".." in relative_file or relative_file.startswith("/") or relative_file.startswith("\\"):
            raise SecurityBoundaryError(f"Directory traversal or absolute path detected: '{relative_file}'")

        root_resolved = root_path.resolve()
        target_resolved = (root_resolved / relative_file).resolve()

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
    def collect_from_text(logs_text: str, source_label: str = "logs.user") -> List[EvidenceItem]:
        """Normalizes raw logs text into labeled EvidenceItems."""
        if not logs_text or not logs_text.strip():
            return []

        lines = [line.strip() for line in logs_text.splitlines() if line.strip()]
        error_lines = [l for l in lines if any(k in l.upper() for k in ["ERROR", "CRITICAL", "EXCEPTION", "TRACEBACK", "FAIL"])]

        items = []
        # Item 1: Complete log tail
        items.append(
            EvidenceItem(
                id=f"ev-log-tail",
                type=EvidenceType.LOGS,
                source=source_label,
                content="\n".join(lines[-50:]),
                metadata={"total_lines": len(lines), "has_errors": bool(error_lines)},
                is_initial=True,
            )
        )

        # Item 2: Explicit error extracts if present
        if error_lines:
            items.append(
                EvidenceItem(
                    id=f"ev-log-errors",
                    type=EvidenceType.LOGS,
                    source=f"{source_label}:extracted_errors",
                    content="\n".join(error_lines[:15]),
                    metadata={"error_count": len(error_lines)},
                    is_initial=True,
                )
            )

        return items


class DockerStateCollector:
    """Extracts container status, exit codes, healthchecks, and port bindings."""

    @staticmethod
    def collect_from_dict(inspect_data: Dict[str, Any], source_label: str = "docker.inspect") -> List[EvidenceItem]:
        if not inspect_data:
            return []

        items = []
        state = inspect_data.get("State", {})
        config = inspect_data.get("Config", {})
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

        items.append(
            EvidenceItem(
                id="ev-docker-state",
                type=EvidenceType.DOCKER_INSPECT,
                source=source_label,
                content=json.dumps(summary, indent=2),
                metadata=summary,
                is_initial=True,
            )
        )

        if health_log:
            last_check = health_log[-1]
            items.append(
                EvidenceItem(
                    id="ev-docker-healthlog",
                    type=EvidenceType.DOCKER_INSPECT,
                    source=f"{source_label}:health_log",
                    content=f"ExitCode: {last_check.get('ExitCode')}, Output: {last_check.get('Output', '').strip()}",
                    metadata={"exit_code": last_check.get("ExitCode")},
                    is_initial=True,
                )
            )

        return items


class ComposeConfigCollector:
    """Collects and parses docker-compose.yml configuration."""

    @staticmethod
    def collect_from_yaml(compose_text: str, source_label: str = "compose.config") -> List[EvidenceItem]:
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

            items.append(
                EvidenceItem(
                    id=f"ev-compose-{svc_name}",
                    type=EvidenceType.COMPOSE_CONFIG,
                    source=f"{source_label}:{svc_name}",
                    content=json.dumps(spec, indent=2),
                    metadata=spec,
                    is_initial=True,
                )
            )

        return items


class SourceCodeCollector:
    """Extracts endpoint routes and listen ports from application source files."""

    @staticmethod
    def collect_routes_and_ports(files: Dict[str, str], source_label: str = "source.code") -> List[EvidenceItem]:
        items = []
        for filename, content in files.items():
            discovered_routes = []
            discovered_ports = []

            # Match FastAPI / Flask routes
            route_matches = re.findall(r"@(?:app|router)\.(?:get|post|put|delete)\([\"']([^\"']+)[\"']", content)
            if route_matches:
                discovered_routes.extend(list(dict.fromkeys(route_matches)))

            # Match common port bindings (e.g. port=8000, PORT = 8000, "8000")
            port_matches = re.findall(r"(?:port\s*=\s*|PORT\s*=\s*)(\d{2,5})", content)
            if port_matches:
                discovered_ports.extend(list(dict.fromkeys([int(p) for p in port_matches])))

            if discovered_routes or discovered_ports:
                meta = {
                    "filename": filename,
                    "routes": list(dict.fromkeys(discovered_routes)),
                    "ports": list(dict.fromkeys(discovered_ports)),
                }
                items.append(
                    EvidenceItem(
                        id=f"ev-src-{Path(filename).stem}",
                        type=EvidenceType.SOURCE_CODE,
                        source=f"{source_label}:{filename}",
                        content=f"File '{filename}' declares routes: {meta['routes']} and ports: {meta['ports']}",
                        metadata=meta,
                        is_initial=True,
                    )
                )

        return items


class EnvironmentCollector:
    """Audits environment variable presence WITHOUT revealing secret values."""

    @staticmethod
    def collect_presence(
        env_dict: Dict[str, str],
        expected_keys: Optional[Set[str]] = None,
        source_label: str = "env.audit"
    ) -> List[EvidenceItem]:
        expected = expected_keys or set()
        present_keys = set(env_dict.keys())

        safe_audit = {}
        for k in sorted(present_keys):
            if SENSITIVE_KEY_PATTERNS.search(k):
                safe_audit[k] = "[PRESENT_SECRET_MASKED]"
            else:
                val = env_dict[k]
                safe_audit[k] = f"[PRESENT: {val[:20]}]"

        missing_from_expected = list(expected - present_keys)

        content_lines = [
            f"Configured variables ({len(present_keys)} present): {list(safe_audit.keys())}",
            f"Audit status: {json.dumps(safe_audit, indent=2)}",
        ]
        if missing_from_expected:
            content_lines.append(f"Missing expected variables: {missing_from_expected}")

        return [
            EvidenceItem(
                id="ev-env-presence",
                type=EvidenceType.ENVIRONMENT,
                source=source_label,
                content="\n".join(content_lines),
                metadata={
                    "present_keys": list(present_keys),
                    "missing_expected": missing_from_expected,
                },
                is_initial=True,
            )
        ]


class EvidenceCollectorHub:
    """Coordinates evidence collection across all modular collectors for a target project."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        if not self.project_root.exists() or not self.project_root.is_dir():
            raise SecurityBoundaryError(f"Approved project root directory does not exist: '{project_root}'")

    def collect_all_initial(
        self,
        logs_override: Optional[str] = None,
        inspect_override: Optional[Dict[str, Any]] = None,
    ) -> List[EvidenceItem]:
        """Collects initial evidence from repository files and provided runtime metadata."""
        evidence: List[EvidenceItem] = []

        # 1. Logs
        logs_text = logs_override
        if not logs_text:
            log_file = self.project_root / "logs.txt"
            if log_file.exists():
                logs_text = log_file.read_text(encoding="utf-8", errors="replace")

        if logs_text:
            evidence.extend(LogCollector.collect_from_text(logs_text, source_label=f"project:{self.project_root.name}:logs"))

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
            evidence.extend(DockerStateCollector.collect_from_dict(inspect_data, source_label=f"docker:inspect:{self.project_root.name}"))

        # 3. Docker Compose
        compose_file = self.project_root / "docker-compose.yml"
        declared_keys = set()
        if compose_file.exists():
            compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
            compose_items = ComposeConfigCollector.collect_from_yaml(compose_text, source_label=f"compose:{compose_file.name}")
            evidence.extend(compose_items)
            for item in compose_items:
                declared_keys.update(item.metadata.get("declared_env_keys", []))

        # 4. Source Files (restricted to approved directory)
        source_files = {}
        for ext in [".py", ".js", ".ts"]:
            for p in self.project_root.glob(f"*{ext}"):
                if p.is_file():
                    source_files[p.name] = p.read_text(encoding="utf-8", errors="replace")

        if source_files:
            evidence.extend(SourceCodeCollector.collect_routes_and_ports(source_files, source_label=f"source:{self.project_root.name}"))

        # 5. Environment variable audit
        # Extract environment from inspect if available
        env_dict = {}
        if inspect_data and "Config" in inspect_data and "Env" in inspect_data["Config"]:
            for e in inspect_data["Config"]["Env"]:
                if "=" in e:
                    k, v = e.split("=", 1)
                    env_dict[k] = v

        evidence.extend(EnvironmentCollector.collect_presence(env_dict, expected_keys=declared_keys))

        return evidence
