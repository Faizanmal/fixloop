"""Tests for Nebius LLM Client, MockLLMProvider, structured parsing, and error mapping."""

import json

import httpx
import pytest

from backend.app.core.models import (
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnosisStatus,
    HypothesisCategory,
    LLMHypothesisResponse,
)
from backend.app.data.sample_reports import (
    MOCK_NEBIUS_HEALTHCHECK_RESPONSE,
    SAMPLE_HEALTHCHECK_FAILURE,
)
from backend.app.llm.client import NebiusLLMClient, sanitize_message
from backend.app.llm.exceptions import (
    ModelResponseValidationError,
    NebiusAuthenticationError,
    NebiusBillingError,
    NebiusModelNotFoundError,
    NebiusQuotaError,
)
from backend.app.llm.parser import (
    extract_json_from_llm_response,
    parse_structured_output,
)
from backend.app.llm.prompts import (
    SOFTWARE_DEBUGGING_SYSTEM_PROMPT,
    build_diagnose_user_prompt,
)


def test_software_debugging_system_prompt_rules():
    """Verify that the system prompt specifically enforces container software debugging principles."""
    prompt = SOFTWARE_DEBUGGING_SYSTEM_PROMPT
    assert "Site Reliability Engineer" in prompt or "Docker" in prompt
    assert "healthcheck" in prompt.lower()
    assert "port" in prompt.lower()
    assert "diagnosis_available" in prompt
    assert "insufficient_evidence" in prompt
    assert "human_intervention_required" in prompt


def test_build_diagnose_user_prompt():
    """Verify user prompt correctly formats logs, inspect, and config files."""
    user_prompt = build_diagnose_user_prompt(
        service_name="web-service",
        logs="Error 404 Not Found",
        configuration_files={"docker-compose.yml": "ports: 8000:8000"},
        environment_variables={"API_SECRET_KEY": "supersecret123", "PORT": "8000"},
    )
    assert "SERVICE UNDER INVESTIGATION: web-service" in user_prompt
    assert "Error 404 Not Found" in user_prompt
    assert "ports: 8000:8000" in user_prompt
    # Ensure sensitive env keys are masked in prompt
    assert "supersecret123" not in user_prompt
    assert "***MASKED***" in user_prompt


def test_sanitize_message_strips_secrets():
    """Verify secrets and bearer tokens are redacted from error logs."""
    raw = "Failed Authorization with Bearer neb_secret_key_123456789 and key neb_secret_key_123456789"
    sanitized = sanitize_message(raw, secret_key="neb_secret_key_123456789")
    assert "neb_secret_key_123456789" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized or "[REDACTED_TOKEN]" in sanitized


def test_extract_json_from_markdown():
    raw_md = 'Here is the response:\n```json\n{"reasoning": "ok", "hypotheses": [], "needs_diagnostic_probe": false}\n```\nHope that helps!'
    extracted = extract_json_from_llm_response(raw_md)
    assert extracted.startswith("{")
    assert extracted.endswith("}")


def test_parse_structured_output():
    json_str = '{"reasoning": "Port mismatch detected", "hypotheses": [{"id": "hyp-1", "title": "Port bug", "description": "8000 mapped to 5000", "category": "PORT_MISMATCH", "confidence_score": 0.95}], "needs_diagnostic_probe": false, "is_evidence_sufficient": true}'
    parsed = parse_structured_output(json_str, LLMHypothesisResponse)
    assert parsed.is_evidence_sufficient is True
    assert parsed.hypotheses[0].category == HypothesisCategory.PORT_MISMATCH


# =========================================================================
# Integration Tests with Mocked HTTPX Transport (0 Credits Spent)
# =========================================================================


@pytest.mark.asyncio
async def test_live_client_with_mocked_http_transport_success():
    """Simulates successful Nebius /chat/completions response via httpx.MockTransport."""
    mock_chat_completion = {
        "id": "chatcmpl-test-1",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(MOCK_NEBIUS_HEALTHCHECK_RESPONSE),
                },
                "finish_reason": "stop",
            }
        ],
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert "Authorization" in request.headers
        return httpx.Response(200, json=mock_chat_completion)

    mock_transport = httpx.MockTransport(handler)
    client = NebiusLLMClient(transport=mock_transport)

    req = DiagnoseRequest.model_validate(SAMPLE_HEALTHCHECK_FAILURE)
    resp = await client.diagnose(req)

    assert isinstance(resp, DiagnoseResponse)
    assert resp.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert len(resp.hypotheses) == 2
    assert resp.hypotheses[0].confidence == 0.98


@pytest.mark.asyncio
async def test_client_error_mapping_401_auth_failure():
    """Verify HTTP 401 raises actionable NebiusAuthenticationError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized: Invalid API key")

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest(service_name="app", logs="error")

    with pytest.raises(NebiusAuthenticationError) as exc_info:
        await client.diagnose(req)
    assert exc_info.value.status_code == 401
    assert "NEBIUS_API_KEY" in exc_info.value.actionable_advice
    assert "Verify NEBIUS_API_KEY" in exc_info.value.message


@pytest.mark.asyncio
async def test_client_error_mapping_404_model_not_found():
    """Verify HTTP 404 raises actionable NebiusModelNotFoundError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Model not found")

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest(service_name="app", logs="error", model="unknown/model")

    with pytest.raises(NebiusModelNotFoundError) as exc_info:
        await client.diagnose(req)
    assert exc_info.value.status_code == 404
    assert "unknown/model" in exc_info.value.message


@pytest.mark.asyncio
async def test_client_error_mapping_429_quota():
    """Verify HTTP 429 raises actionable NebiusQuotaError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit exceeded")

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest(service_name="app", logs="error")

    with pytest.raises(NebiusQuotaError) as exc_info:
        await client.diagnose(req)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_client_error_mapping_402_billing():
    """Verify HTTP 402 raises actionable NebiusBillingError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="Payment Required")

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest(service_name="app", logs="error")

    with pytest.raises(NebiusBillingError) as exc_info:
        await client.diagnose(req)
    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_client_retry_on_transient_503_recovers():
    """Verify client automatically retries transient 503 and recovers on retry."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(MOCK_NEBIUS_HEALTHCHECK_RESPONSE)
                        }
                    }
                ]
            },
        )

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest.model_validate(SAMPLE_HEALTHCHECK_FAILURE)
    resp = await client.diagnose(req)

    assert attempts == 2
    assert resp.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE


@pytest.mark.asyncio
async def test_client_invalid_json_raises_model_response_validation_error():
    """Verify malformed JSON from model raises ModelResponseValidationError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Sorry, I cannot diagnose this failure."}}
                ]
            },
        )

    client = NebiusLLMClient(transport=httpx.MockTransport(handler))
    req = DiagnoseRequest(service_name="app", logs="error")

    with pytest.raises(ModelResponseValidationError):
        await client.diagnose(req)
