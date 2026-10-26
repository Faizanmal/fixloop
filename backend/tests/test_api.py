"""Comprehensive integration tests for FixLoop FastAPI endpoints: /health, /ready, /api/v1/diagnose."""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.config import settings
from backend.app.data.sample_reports import SAMPLE_HEALTHCHECK_FAILURE, SAMPLE_MISSING_ENV_FAILURE


@pytest.mark.asyncio
async def test_top_level_health_endpoint():
    """Verify GET /health responds with 200 OK and service status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "fixloop"
        assert data["version"] == "0.1.0"
        assert "docker" in data


@pytest.mark.asyncio
async def test_top_level_ready_endpoint():
    """Verify GET /ready reports configuration status without leaking any secrets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "ready" in data
        assert "nebius" in data
        assert "api_key_configured" in data["nebius"]
        assert "base_url" in data["nebius"]
        assert "model" in data["nebius"]
        assert "issues" in data

        # CRITICAL: Verify NO secret values or tokens appear anywhere in the response text
        raw_text = response.text
        assert "Bearer" not in raw_text
        if settings.NEBIUS_API_KEY:
            secret = settings.NEBIUS_API_KEY.get_secret_value()
            if secret:
                assert secret not in raw_text


@pytest.mark.asyncio
async def test_diagnose_validation_failure_on_empty_payload():
    """Verify POST /api/v1/diagnose rejects completely empty diagnostic requests with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json={"service_name": "empty-app"})
        assert response.status_code == 422
        assert "At least one diagnostic input" in response.text


@pytest.mark.asyncio
async def test_diagnose_successful_healthcheck_sample():
    """Verify POST /api/v1/diagnose with sample healthcheck failure returns valid DiagnoseResponse."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json=SAMPLE_HEALTHCHECK_FAILURE)
        assert response.status_code == 200
        data = response.json()

        # Validate required root fields
        assert data["status"] in ["diagnosis_available", "insufficient_evidence", "human_intervention_required"]
        assert isinstance(data["summary"], str) and len(data["summary"]) > 0
        assert isinstance(data["hypotheses"], list) and len(data["hypotheses"]) > 0
        assert isinstance(data["evidence"], list)
        assert isinstance(data["recommended_tests"], list)
        assert isinstance(data["missing_information"], list)
        assert 0.0 <= data["confidence"] <= 1.0
        assert isinstance(data["next_action"], str)

        # Validate hypothesis internal fields
        primary_hyp = data["hypotheses"][0]
        assert "description" in primary_hyp
        assert "supporting_evidence" in primary_hyp
        assert "contradicting_evidence" in primary_hyp
        assert 0.0 <= primary_hyp["confidence"] <= 1.0
        assert "recommended_discriminating_test" in primary_hyp


@pytest.mark.asyncio
async def test_diagnose_missing_env_sample():
    """Verify POST /api/v1/diagnose handles missing environment variable sample."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json=SAMPLE_MISSING_ENV_FAILURE)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "diagnosis_available"
        assert any("DATABASE_URL" in h["description"] or "database" in h["description"].lower() for h in data["hypotheses"])


@pytest.mark.asyncio
async def test_scenarios_endpoint():
    """Verify GET /scenarios lists available reproducible failure scenarios."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scenarios")
        assert response.status_code == 200
        scenarios = response.json()
        assert len(scenarios) == 4
        ids = [s["id"] for s in scenarios]
        assert "scenario_a_missing_env" in ids
        assert "scenario_b_healthcheck_mismatch" in ids
        assert "scenario_c_port_mismatch" in ids
        assert "scenario_d_insufficient_evidence" in ids
