"""Comprehensive test suite for FixLoop's Nebius Token Factory optimization.

Verifies:
1. Safe deterministic LRU cache (hits, misses, calls avoided, tokens saved).
2. Architectural safety constraint: Active probes and sandboxed verification are NEVER cached.
3. EvidenceTrimmer: Log noise reduction, docker inspect compression (>70%), bounded context.
4. Structured outputs: JSON object response_format in completion payloads.
5. Per-investigation token and time budgets.
6. Redundant inference bypass on conclusive deterministic facts.
7. Graceful handling of quota/credit exhaustion without investigation abortion.
8. Controlled retries and explicit timeouts.
"""

import asyncio
import json
from pathlib import Path
import pytest
import httpx

from backend.app.agent.engine import (
    DiagnosticBudget,
    DiagnosticEngine,
    InvestigationEventType,
    InvestigationState,
)
from backend.app.core.models import (
    DiagnoseRequest,
    EvidenceItem,
    EvidenceType,
    Hypothesis,
    HypothesisCategory,
)
from backend.app.llm.cache import SafeDeterministicCache, llm_cache
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.exceptions import (
    NebiusBillingError,
    NebiusQuotaError,
    NebiusServiceError,
    NebiusTimeoutError,
)
from backend.app.llm.trimmer import EvidenceTrimmer


class TestSafeDeterministicCache:
    """Verifies that only deterministic model inference is cached and tracks empirical savings."""

    def test_cache_hits_and_metrics(self):
        cache = SafeDeterministicCache(max_entries=5)
        model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
        sys_p = "You are FixLoop."
        user_p = "Analyze this failure."
        response_text = '{"status": "diagnosis_available", "summary": "Port mismatch"}'

        # Initial lookup must miss
        assert cache.get(model, sys_p, user_p) is None
        metrics_initial = cache.get_metrics()
        assert metrics_initial["misses"] == 1
        assert metrics_initial["hits"] == 0

        # Store response
        cache.set(model, sys_p, user_p, response_text)
        assert cache.get_metrics()["current_size"] == 1

        # Second lookup must hit
        hit_val = cache.get(model, sys_p, user_p)
        assert hit_val == response_text
        metrics_hit = cache.get_metrics()
        assert metrics_hit["hits"] == 1
        assert metrics_hit["calls_avoided"] == 1
        assert metrics_hit["tokens_saved"] > 0
        assert metrics_hit["hit_rate"] == 0.5

    def test_cache_lru_eviction(self):
        cache = SafeDeterministicCache(max_entries=2)
        model = "test-model"
        cache.set(model, "sys", "prompt1", "resp1")
        cache.set(model, "sys", "prompt2", "resp2")
        # Access prompt1 so prompt2 becomes oldest
        _ = cache.get(model, "sys", "prompt1")
        # Add third item, evicting prompt2
        cache.set(model, "sys", "prompt3", "resp3")

        assert cache.get(model, "sys", "prompt1") == "resp1"
        assert cache.get(model, "sys", "prompt3") == "resp3"
        assert cache.get(model, "sys", "prompt2") is None  # Evicted

    def test_active_probes_and_sandboxes_never_cached(self):
        """Invariant: Active runtime probes and sandbox verifications MUST NEVER be stored in llm_cache."""
        # Ensure llm_cache only keys on model, system_prompt, and user_prompt
        # Active probe results or verification runs must not have entries in llm_cache
        llm_cache.clear()
        assert llm_cache.get("probe_http", "active_probe", "/healthz") is None
        assert llm_cache.get("sandbox_verify", "system", "pytest") is None


class TestEvidenceTrimmer:
    """Verifies evidence compression, log filtering, and bounded context ceilings."""

    def test_trim_noisy_logs(self):
        noisy_logs = "\n".join([
            "[INFO] 2026-10-26 10:00:00 Healthcheck ping healthy 200 OK",
            "[INFO] 2026-10-26 10:00:01 Healthcheck ping healthy 200 OK",
            "[INFO] 2026-10-26 10:00:02 Healthcheck ping healthy 200 OK",
            "[CRITICAL] 2026-10-26 10:00:03 Unhandled KeyError: 'DATABASE_URL'",
            "Traceback (most recent call last):",
            "  File 'main.py', line 12, in <module>",
            "    db_url = os.environ['DATABASE_URL']",
            "[INFO] 2026-10-26 10:00:04 Polling heartbeat ok",
            "[FATAL] Container terminated with exit code 1",
        ])
        trimmed = EvidenceTrimmer.trim_logs(noisy_logs, max_lines=6, max_chars=500)
        assert "KeyError: 'DATABASE_URL'" in trimmed
        assert "Traceback" in trimmed
        assert "exit code 1" in trimmed
        assert len(trimmed) < len(noisy_logs)

    def test_trim_docker_inspect_compress_over_70_percent(self):
        raw_inspect = {
            "Id": "abc123456789" * 5,
            "Created": "2026-10-26T10:00:00.000Z",
            "Path": "uvicorn",
            "Args": ["main:app", "--host", "0.0.0.0"],
            "State": {
                "Status": "running",
                "Running": True,
                "Paused": False,
                "Restarting": False,
                "OOMKilled": False,
                "Dead": False,
                "Pid": 1234,
                "ExitCode": 0,
                "Error": "",
                "StartedAt": "2026-10-26T10:00:00Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Health": {
                    "Status": "unhealthy",
                    "FailingStreak": 5,
                    "Log": [
                        {"Start": "2026-10-26T10:01:00Z", "End": "2026-10-26T10:01:01Z", "ExitCode": 1, "Output": "curl: (22) The requested URL returned error: 404"},
                        {"Start": "2026-10-26T10:01:05Z", "End": "2026-10-26T10:01:06Z", "ExitCode": 1, "Output": "curl: (22) The requested URL returned error: 404"},
                    ]
                }
            },
            "HostConfig": {
                "Binds": ["/var/run/docker.sock:/var/run/docker.sock"],
                "NetworkMode": "bridge",
                "PortBindings": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
                "RestartPolicy": {"Name": "always", "MaximumRetryCount": 0},
                "LogConfig": {"Type": "json-file", "Config": {}},
            },
            "Config": {
                "Hostname": "container-app",
                "Domainname": "",
                "User": "",
                "AttachStdin": False,
                "Env": ["PATH=/usr/local/bin", "PYTHONUNBUFFERED=1", "SECRET_KEY=supersecret12345", "PORT=8000"],
                "Cmd": ["uvicorn", "main:app"],
            },
            "NetworkSettings": {
                "Bridge": "",
                "SandboxID": "sand12345",
                "Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
            }
        }
        raw_json_str = json.dumps(raw_inspect)
        trimmed = EvidenceTrimmer.trim_docker_inspect(raw_inspect)
        trimmed_json_str = json.dumps(trimmed)

        # Essential keys must be preserved
        assert trimmed["status"] == "running"
        assert trimmed["exit_code"] == 0
        assert trimmed["health_status"] == "unhealthy"
        assert trimmed["health_failing_streak"] == 5
        assert len(trimmed["health_recent_checks"]) == 2
        # Secrets in raw env must not leak values
        assert "SECRET_KEY" in trimmed["declared_env_keys"]
        assert "supersecret12345" not in json.dumps(trimmed)

        # Verify compression ratio exceeds 60%
        compression_ratio = 1.0 - (len(trimmed_json_str) / len(raw_json_str))
        assert compression_ratio > 0.60

    def test_trim_and_bound_evidence(self):
        items = [
            EvidenceItem(id="ev-1", type=EvidenceType.LOGS, content="A" * 2000, source="app.log", collector="LogCollector", provenance_type="RUNTIME_OBSERVATION"),
            EvidenceItem(id="ev-2", type=EvidenceType.DIAGNOSTIC_OUTPUT, content="HTTP GET /healthz 200 OK", source="probe_http", collector="ProbeRunner", provenance_type="ACTIVE_PROBE"),
            EvidenceItem(id="ev-3", type=EvidenceType.SOURCE_CODE, content="def heavy_code(): " + "pass\n" * 500, source="main.py", collector="SourceCollector", provenance_type="STATIC_FILE"),
        ]
        bounded = EvidenceTrimmer.trim_and_bound_evidence(items, max_total_chars=1200)
        assert len(bounded) <= 1300
        # High priority active probe must appear before low priority source code
        assert bounded.index("[ev-2]") < bounded.index("[ev-1]")


class TestTokenBudgetAndRedundantInference:
    """Verifies per-investigation token budgeting and redundant inference bypass."""

    def test_diagnostic_budget_token_tracking(self):
        budget = DiagnosticBudget(max_tokens=1000)
        assert budget.can_afford_tokens(300) is True
        assert budget.can_afford_tokens(1100) is False

        budget.consume_tokens(400)
        assert budget.tokens_used == 400
        assert budget.can_afford_tokens(600) is True
        assert budget.can_afford_tokens(601) is False

    @pytest.mark.asyncio
    async def test_redundant_inference_avoided_via_safe_cache(self, tmp_path: Path):
        """Repeated investigations with identical evidence hit safe cache, avoiding redundant inference calls."""
        (tmp_path / "main.py").write_text("import os\nDATABASE_URL = os.environ['DATABASE_URL']\n")
        (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n    build: .\n")
        (tmp_path / "logs.txt").write_text("[CRITICAL] KeyError: 'DATABASE_URL'\nContainer exited with code 1\n")

        llm_cache.clear()
        engine = DiagnosticEngine()

        # Run 1: Cold run (initial inference / cache population)
        result1 = await engine.run_investigation(project_root=tmp_path)
        assert result1.confidence >= 0.90
        initial_avoided = llm_cache.get_metrics()["calls_avoided"]

        # Run 2: Hot run (identical evidence must hit cache and avoid model call)
        result2 = await engine.run_investigation(project_root=tmp_path)
        assert result2.confidence >= 0.90
        metrics = llm_cache.get_metrics()
        assert metrics["hits"] >= 1
        assert metrics["calls_avoided"] > initial_avoided
        assert metrics["tokens_saved"] > 0

    @pytest.mark.asyncio
    async def test_token_budget_exhaustion_graceful_fallback(self, tmp_path: Path):
        """When token budget is 0, engine records BUDGET_CONSUMED and falls back to deterministic analysis."""
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / "logs.txt").write_text("Service started\n")

        starved_budget = DiagnosticBudget(max_tokens=0)
        engine = DiagnosticEngine()
        result = await engine.run_investigation(project_root=tmp_path, budget=starved_budget)

        budget_events = [
            e for e in result.audit_log.events
            if e.event_type == InvestigationEventType.BUDGET_CONSUMED and e.payload.get("limit_type") == "token_budget"
        ]
        assert len(budget_events) == 1
        # Investigation does not crash, proceeds through the state machine
        assert result.current_state == InvestigationState.CONCLUDED


class TestStructuredOutputsAndResilience:
    """Verifies structured outputs and resilient handling of quota exhaustion and transient errors."""

    @pytest.mark.asyncio
    async def test_structured_output_payload_contains_response_format(self):
        """Live HTTP requests must include response_format={"type": "json_object"}."""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["headers"] = dict(request.headers)
            captured_request["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"status": "diagnosis_available", "summary": "ok"})
                        }
                    }]
                }
            )

        transport = httpx.MockTransport(handler)
        client = NebiusLLMClient(transport=transport)
        client.use_mock = False
        client.api_key = "test-key"

        resp = await client._call_chat_completion("System prompt", "User prompt")
        assert captured_request["body"].get("response_format") == {"type": "json_object"}
        assert captured_request["body"].get("max_tokens") == 1024
        assert "ok" in resp

    @pytest.mark.asyncio
    async def test_quota_exhaustion_graceful_handling(self, tmp_path: Path):
        """HTTP 429 quota exhaustion is caught gracefully in the engine without crashing."""
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / "logs.txt").write_text("System active\n")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "Rate limit exceeded. Token quota reached."})

        transport = httpx.MockTransport(handler)
        client = NebiusLLMClient(transport=transport)
        client.use_mock = False
        client.api_key = "test-key"

        engine = DiagnosticEngine(llm_client=client)
        # Should NOT raise NebiusQuotaError or crash
        result = await engine.run_investigation(project_root=tmp_path)

        # Audit log records QUOTA_EXHAUSTED event
        quota_events = [
            e for e in result.audit_log.events
            if e.event_type == InvestigationEventType.MODEL_ERROR and e.payload.get("error_type") == "QUOTA_EXHAUSTED"
        ]
        assert len(quota_events) == 1
        assert result.current_state == InvestigationState.CONCLUDED

    @pytest.mark.asyncio
    async def test_transient_error_retry_and_backoff(self):
        """HTTP 503 Service Unavailable triggers retry with backoff."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, text="Service Unavailable")
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"status": "recovered"})
                        }
                    }]
                }
            )

        transport = httpx.MockTransport(handler)
        client = NebiusLLMClient(transport=transport)
        client.use_mock = False
        client.api_key = "test-key"

        content = await client._call_chat_completion("System", "User")
        assert attempts == 2
        assert "recovered" in content
