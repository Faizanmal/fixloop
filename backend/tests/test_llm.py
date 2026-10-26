"""Tests for LLM Client, MockLLMProvider, and JSON structured parsing."""

import pytest
from backend.app.core.models import (
    LLMHypothesisResponse,
    LLMPatchResponse,
    HypothesisCategory,
    DiagnosticProbeType,
)
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.mock_provider import MockLLMProvider
from backend.app.llm.parser import extract_json_from_llm_response, parse_structured_output


def test_extract_json_from_markdown():
    raw_md = "Here is the response:\n```json\n{\"reasoning\": \"ok\", \"hypotheses\": [], \"needs_diagnostic_probe\": false}\n```\nHope that helps!"
    extracted = extract_json_from_llm_response(raw_md)
    assert extracted.startswith("{")
    assert extracted.endswith("}")


def test_parse_structured_output():
    json_str = '{"reasoning": "Port mismatch detected", "hypotheses": [{"id": "hyp-1", "title": "Port bug", "description": "8000 mapped to 5000", "category": "PORT_MISMATCH", "confidence_score": 0.95}], "needs_diagnostic_probe": false, "is_evidence_sufficient": true}'
    parsed = parse_structured_output(json_str, LLMHypothesisResponse)
    assert parsed.is_evidence_sufficient is True
    assert parsed.hypotheses[0].category == HypothesisCategory.PORT_MISMATCH
    assert parsed.hypotheses[0].confidence_score == 0.95


@pytest.mark.asyncio
async def test_mock_llm_client_hypothesis_generation():
    client = NebiusLLMClient()
    # In mock mode, should return deterministic hypothesis response
    res = await client.generate_hypotheses(
        scenario_name="scenario_1_healthcheck",
        iteration=0,
        max_iterations=5,
        evidence=[],
        current_hypotheses=[],
    )
    assert isinstance(res, LLMHypothesisResponse)
    assert len(res.hypotheses) == 2
    assert res.needs_diagnostic_probe is True
    assert res.recommended_probe is not None
    assert res.recommended_probe.probe_type == DiagnosticProbeType.HTTP_GET


@pytest.mark.asyncio
async def test_mock_llm_client_patch_synthesis():
    client = NebiusLLMClient()
    res = await client.generate_patch(
        scenario_name="scenario_1_healthcheck",
        hypothesis=MockLLMProvider.get_hypotheses_for_scenario("scenario_1_healthcheck", 1, []).hypotheses[0],
        evidence=[],
        files_content="docker-compose.yml content",
    )
    assert isinstance(res, LLMPatchResponse)
    assert "docker-compose.yml" in res.target_file
    assert "/healthz" in res.diff_unified


def test_ambiguous_scenario_honestly_refuses_fix():
    res = MockLLMProvider.get_hypotheses_for_scenario("scenario_4_ambiguous_failure", 0, [])
    assert res.is_evidence_sufficient is False
    assert res.refusal_reason is not None
    assert "Insufficient evidence" in res.refusal_reason
    assert res.hypotheses[0].category == HypothesisCategory.EXTERNAL_DEPENDENCY
