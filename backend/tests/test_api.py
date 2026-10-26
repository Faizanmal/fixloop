"""Tests for FastAPI endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "nebius" in data
        assert "docker" in data
        assert "mock_mode" in data["nebius"]


@pytest.mark.asyncio
async def test_scenarios_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/scenarios")
        assert response.status_code == 200
        scenarios = response.json()
        assert len(scenarios) == 4
        ids = [s["id"] for s in scenarios]
        assert "scenario_1_healthcheck" in ids
        assert "scenario_2_port_mismatch" in ids
        assert "scenario_3_missing_env" in ids
        assert "scenario_4_ambiguous_failure" in ids
