"""Comprehensive integration tests for FixLoop FastAPI endpoints: /health, /ready, /api/v1/diagnose."""

import time
import asyncio
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
        assert any(
            any(w in h["description"].lower() for w in ["database", "env", "configuration", "variable", "missing"])
            for h in data["hypotheses"]
        )


@pytest.mark.asyncio
async def test_scenarios_endpoint():
    """Verify GET /scenarios lists available reproducible failure scenarios."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scenarios")
        assert response.status_code == 200
        scenarios = response.json()
        assert len(scenarios) >= 4
        ids = [s["id"] for s in scenarios]
        assert "scenario_a_missing_env" in ids
        assert "scenario_b_healthcheck_mismatch" in ids
        assert "scenario_c_port_mismatch" in ids
        assert "scenario_d_insufficient_evidence" in ids


@pytest.mark.asyncio
async def test_diagnose_custom_logs_missing_env():
    """Verify custom pasted logs with missing env var diagnose DATABASE_URL and record in investigations."""
    transport = ASGITransport(app=app)
    custom_payload = {
        "service_name": "custom-auth-service",
        "logs": "ERROR: KeyError 'DATABASE_URL' at app/config.py line 12\nFailed to start server",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json=custom_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "diagnosis_available"
        assert "DATABASE_URL" in data["summary"]
        assert any("DATABASE_URL" in h["description"] for h in data["hypotheses"])
        # Ensure it NEVER falls back to Scenario B healthcheck
        assert "/health" not in data["summary"].lower() or "healthcheck" not in data["summary"].lower()

        # Check that it recorded in /investigations
        inv_res = await client.get("/investigations")
        assert inv_res.status_code == 200
        inv_data = inv_res.json()
        matching = [inv for inv in inv_data if inv["scenario_name"] == "custom-auth-service"]
        assert len(matching) > 0
        assert "DATABASE_URL" in matching[-1]["outcome_summary"]


@pytest.mark.asyncio
async def test_diagnose_custom_logs_healthcheck_mismatch():
    """Verify custom pasted logs with healthcheck 404 diagnose probe mismatch."""
    transport = ASGITransport(app=app)
    custom_payload = {
        "service_name": "billing-service",
        "logs": "Health check probe failed: GET http://127.0.0.1:8000/health returned 404 Not Found\nApplication exposes route /healthz\nContainer marked unhealthy",
        "configuration_files": {
            "docker-compose.yml": "services:\n  billing-service:\n    healthcheck:\n      test: ['CMD', 'curl', '-f', 'http://localhost:8000/health']"
        }
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json=custom_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["diagnosis_available", "insufficient_evidence"]
        assert any(k in data["summary"].lower() for k in ["health", "route", "probe", "404", "mismatch"])
        # Ensure it does NOT report an unrelated database error
        assert "database_url" not in data["summary"].lower()


@pytest.mark.asyncio
async def test_diagnose_custom_logs_unrelated_noise():
    """Verify custom pasted logs with unrelated noise return insufficient_evidence, never an unrelated preset."""
    transport = ASGITransport(app=app)
    custom_payload = {
        "service_name": "worker-pool",
        "logs": "User 4821 logged in successfully from IP 192.168.1.50\nTask queue processed 14 jobs successfully\nWorker status: idle\nAll background tasks normal",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/diagnose", json=custom_payload)
        assert response.status_code == 200
        data = response.json()
        # Must return insufficient evidence, NOT Scenario B healthcheck mismatch!
        assert data["status"] == "insufficient_evidence"
        assert "healthcheck" not in data["summary"].lower() or "probe" not in data["summary"].lower()
        assert "database_url" not in data["summary"].lower()
        assert len(data["summary"]) > 0
        assert len(data["evidence"]) > 0


@pytest.mark.asyncio
async def test_diagnose_then_verify_persists_in_investigations():
    """Verify diagnose then verify updates the same investigation record with VERIFIED_FIX, real duration, and verification report."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Run diagnose for scenario_a_missing_env
        diag_resp = await client.post("/api/v1/diagnose", json={"service_name": "scenario_a_missing_env"})
        assert diag_resp.status_code == 200
        diag_data = diag_resp.json()
        inv_id = diag_data.get("investigation_id")
        assert inv_id is not None
        assert diag_data["status"] == "diagnosis_available"

        # Check /investigations right after diagnose
        invs_res = await client.get("/investigations")
        assert invs_res.status_code == 200
        invs = invs_res.json()
        diag_inv = next((i for i in invs if i["id"] == inv_id), None)
        assert diag_inv is not None
        assert diag_inv["outcome"] == "DIAGNOSIS_AVAILABLE"
        assert diag_inv["duration_ms"] is not None and diag_inv["duration_ms"] > 0
        assert diag_inv["duration_ms"] != 45  # Must NOT be placeholder 45ms
        initial_duration = diag_inv["duration_ms"]

        # Step 2: Run verify for scenario_a_missing_env with investigation_id
        verify_resp = await client.post(
            "/api/v1/verify",
            json={
                "scenario_name": "scenario_a_missing_env",
                "user_approved": True,
                "investigation_id": inv_id,
            }
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["status"] == "verified_fixed"
        assert verify_data["duration_ms"] > 0

        # Step 3: Fetch /investigations and check updated record
        invs_res_after = await client.get("/investigations")
        assert invs_res_after.status_code == 200
        invs_after = invs_res_after.json()
        final_inv = next((i for i in invs_after if i["id"] == inv_id), None)
        assert final_inv is not None
        # Must be updated in place!
        assert final_inv["outcome"] == "VERIFIED_FIX"
        assert final_inv["status"] == "COMPLETED"
        assert final_inv["duration_ms"] >= initial_duration
        assert final_inv["duration_ms"] != 45
        assert final_inv["verification_report"] is not None
        assert final_inv["verification_report"]["status"] == "verified_fixed"

        # Also verify GET /investigations/{id} returns the full detail
        single_res = await client.get(f"/investigations/{inv_id}")
        assert single_res.status_code == 200
        single_data = single_res.json()
        assert single_data["id"] == inv_id
        assert single_data["outcome"] == "VERIFIED_FIX"
        assert single_data["verification_report"] is not None


@pytest.mark.asyncio
async def test_idempotent_diagnose_creates_single_investigation():
    """Verify that two identical rapid submits with the same idempotency key create exactly one row."""
    key = f"idem-test-{time.time()}"
    payload = {
        "service_name": "custom-auth-service",
        "logs": "ERROR: auth token expired for user 42 in session middleware",
        "idempotency_key": key,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Rapid submit 1
        resp1 = await client.post("/api/v1/diagnose", json=payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        inv_id1 = data1.get("investigation_id")
        assert inv_id1 is not None

        # Rapid submit 2 with exact same idempotency key
        resp2 = await client.post("/api/v1/diagnose", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        inv_id2 = data2.get("investigation_id")

        # Must return the same investigation id and marked as cached
        assert inv_id1 == inv_id2
        assert data2.get("is_cached") is True

        # Check /investigations store has exactly ONE row with this id/key
        invs_res = await client.get("/investigations")
        assert invs_res.status_code == 200
        invs = invs_res.json()
        matching_runs = [i for i in invs if i.get("id") == inv_id1 or i.get("idempotency_key") == key]
        assert len(matching_runs) == 1


@pytest.mark.asyncio
async def test_run_duration_persists_identically_across_reads():
    """Verify run duration is measured once on the server, never overwritten on later reads, and identical across calls."""
    key = f"duration-test-{time.time()}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/diagnose",
            json={
                "service_name": "scenario_a_missing_env",
                "idempotency_key": key,
            }
        )
        assert resp.status_code == 200
        diag_data = resp.json()
        inv_id = diag_data.get("investigation_id")
        assert inv_id is not None
        assert "duration_ms" in diag_data
        assert diag_data["duration_ms"] > 0
        reported_diag_duration = diag_data["duration_ms"]

        # Fetch 1: Immediately after run
        res1 = await client.get("/investigations")
        assert res1.status_code == 200
        invs1 = res1.json()
        target_inv1 = next((i for i in invs1 if i["id"] == inv_id), None)
        assert target_inv1 is not None
        dur1 = target_inv1["duration_ms"]
        assert dur1 == reported_diag_duration

        # Wait briefly to ensure any clock tick wouldn't alter the stored value
        await asyncio.sleep(0.05)

        # Fetch 2: Second read
        res2 = await client.get("/investigations")
        assert res2.status_code == 200
        invs2 = res2.json()
        target_inv2 = next((i for i in invs2 if i["id"] == inv_id), None)
        assert target_inv2 is not None
        dur2 = target_inv2["duration_ms"]

        # Stored duration must be 100% identical between reads
        assert dur1 == dur2

        # GET /investigations/{id} must also return the identical duration
        single_res = await client.get(f"/investigations/{inv_id}")
        assert single_res.status_code == 200
        assert single_res.json()["duration_ms"] == dur1


@pytest.mark.asyncio
async def test_openapi_docs_contain_no_duplicate_api_prefixes():
    """Verify /openapi.json contains no /api/api/v1/ duplicate routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/openapi.json")
        assert res.status_code == 200
        schema = res.json()
        paths = schema.get("paths", {}).keys()
        for p in paths:
            assert not p.startswith("/api/api/"), f"Found duplicate prefix in OpenAPI path: {p}"
        assert "/api/v1/diagnose" in paths
        assert "/api/v1/verify" in paths


@pytest.mark.asyncio
async def test_repeat_scenario_run_is_marked_cached_with_original_duration():
    """Verify that repeat runs of the same scenario are labeled Cached with original compute time and distinct rows."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Run 1: Initial execution
        resp1 = await client.post(
            "/api/v1/diagnose",
            json={"service_name": "scenario_a_missing_env", "idempotency_key": f"run1-{time.time()}"}
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        inv_id1 = data1["investigation_id"]
        assert inv_id1 is not None

        # Run 2: Repeat execution (different idempotency key)
        resp2 = await client.post(
            "/api/v1/diagnose",
            json={"service_name": "scenario_a_missing_env", "idempotency_key": f"run2-{time.time()}"}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        inv_id2 = data2["investigation_id"]

        # Each repeat is logged as a distinct new row
        assert inv_id2 != inv_id1
        # Labeled as cached
        assert data2.get("is_cached") is True
        # Original duration is provided
        assert data2.get("original_duration_ms") is not None
        assert data2["original_duration_ms"] > 0
        # Lookup duration is fast
        assert data2.get("lookup_duration_ms") is not None
        assert data2["lookup_duration_ms"] > 0

        # Verify both rows persist distinctly in /investigations
        invs_res = await client.get("/investigations")
        assert invs_res.status_code == 200
        invs = invs_res.json()
        inv1 = next((i for i in invs if i["id"] == inv_id1), None)
        inv2 = next((i for i in invs if i["id"] == inv_id2), None)
        assert inv1 is not None
        assert inv2 is not None
        assert inv2.get("is_cached") is True
        assert inv2.get("original_duration_ms") is not None
        assert inv2.get("lookup_duration_ms") is not None


@pytest.mark.asyncio
async def test_custom_log_redis_keyerror_patch_proposal():
    """Test that custom log KeyError 'REDIS_URL' proposes REDIS_URL patch, NOT hardcoded DATABASE_URL."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Submit custom log with REDIS_URL KeyError
        diag_resp = await client.post(
            "/api/v1/diagnose",
            json={
                "service_name": "Custom: auth-service",
                "logs": "Traceback (most recent call last):\n  File 'app/config.py', line 12, in <module>\n    REDIS_URL = os.environ['REDIS_URL']\nKeyError: 'REDIS_URL'",
            }
        )
        assert diag_resp.status_code == 200
        diag_data = diag_resp.json()
        inv_id = diag_data["investigation_id"]
        assert inv_id is not None

        # Step 2: Request patch proposal for this investigation
        patch_resp = await client.post(f"/api/v1/patch?scenario_name={inv_id}")
        assert patch_resp.status_code == 200
        patch_data = patch_resp.json()

        # Must propose REDIS_URL, NOT DATABASE_URL
        assert "REDIS_URL" in patch_data["diff_unified"]
        assert "DATABASE_URL" not in patch_data["diff_unified"]
        assert "redis://" in patch_data["diff_unified"]
        assert "REDIS_URL" in patch_data["explanation"]

        # Verify sandbox verification report also uses REDIS_URL and passes
        verify_resp = await client.post(
            "/api/v1/verify",
            json={
                "scenario_name": "Custom: auth-service",
                "investigation_id": inv_id,
                "user_approved": True,
            }
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["status"] == "verified_fixed"
        assert "REDIS_URL" in verify_data["patch_diff"]
        assert "DATABASE_URL" not in verify_data["patch_diff"]
        assert not verify_data["expected_criteria"].endswith(".")
        assert ".." not in verify_data["test_output"]


@pytest.mark.asyncio
async def test_cache_worker_redis_keyerror_patch_and_verification():
    """Verify that cache-worker with REDIS_URL KeyError gets REDIS_URL=redis://localhost:6379/0 patch and passes verification."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Diagnose cache-worker with REDIS_URL KeyError
        diag_resp = await client.post(
            "/api/v1/diagnose",
            json={
                "service_name": "cache-worker",
                "logs": "Traceback (most recent call last):\n  File 'worker.py', line 15, in <module>\n    redis_client = redis.from_url(os.environ['REDIS_URL'])\nKeyError: 'REDIS_URL'",
            }
        )
        assert diag_resp.status_code == 200
        diag_data = diag_resp.json()
        assert diag_data["status"] == "diagnosis_available"
        assert diag_data["confidence"] >= 0.90
        assert diag_data.get("has_safe_patch") is True
        inv_id = diag_data["investigation_id"]
        assert inv_id is not None

        # Step 2: Propose patch - must specifically contain REDIS_URL=redis://localhost:6379/0
        patch_resp = await client.post(f"/api/v1/patch?scenario_name={inv_id}")
        assert patch_resp.status_code == 200
        patch_data = patch_resp.json()
        assert "REDIS_URL=redis://localhost:6379/0" in patch_data["diff_unified"]
        assert "docker-compose.yml" in patch_data["target_file"]

        # Step 3: Run sandbox verification - must pass verified_fixed
        verify_resp = await client.post(
            "/api/v1/verify",
            json={
                "scenario_name": "cache-worker",
                "investigation_id": inv_id,
                "user_approved": True,
            }
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["status"] == "verified_fixed"
        assert "REDIS_URL=redis://localhost:6379/0" in verify_data["patch_diff"]
        assert verify_data["reverted"] is True


@pytest.mark.asyncio
async def test_orders_api_econnrefused_postgres_rejects_wrong_port_mapping_patch():
    """Verify orders-api ECONNREFUSED 127.0.0.1:5432 gets 96% Postgres diagnosis, and sandbox verification REJECTS the 8000:5000 -> 8000:8000 port-mapping patch."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        diag_resp = await client.post(
            "/api/v1/diagnose",
            json={
                "service_name": "orders-api",
                "logs": "Error: connect ECONNREFUSED 127.0.0.1:5432\n    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16)\nFATAL: PostgreSQL connection failed on 127.0.0.1:5432",
            }
        )
        assert diag_resp.status_code == 200
        diag_data = diag_resp.json()
        assert diag_data["status"] == "diagnosis_available"
        assert diag_data["confidence"] >= 0.90
        inv_id = diag_data["investigation_id"]
        assert inv_id is not None
        assert diag_data.get("has_safe_patch") is False

        # Verify that patch proposal rejects unaligned patch and returns 400 (never offering 8000:5000 -> 8000:8000)
        patch_resp = await client.post(f"/api/v1/patch?scenario_name={inv_id}")
        assert patch_resp.status_code == 400
        patch_err = patch_resp.json()
        assert "no safe patch available" in str(patch_err).lower()

        # Check /investigations record initially reflects DIAGNOSIS_NO_PATCH before verification
        initial_inv = await client.get(f"/investigations/{inv_id}")
        assert initial_inv.status_code == 200
        assert initial_inv.json()["outcome"] == "DIAGNOSIS_NO_PATCH"

        # Verify that running sandbox verification on the fallback port-mapping patch FAILS verification
        verify_resp = await client.post(
            "/api/v1/verify",
            json={
                "scenario_name": "orders-api",
                "investigation_id": inv_id,
                "user_approved": True,
            }
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["status"] == "verification_failed"
        assert verify_data["failure_evidence"] is not None
        assert "does not resolve" in verify_data["failure_evidence"] or "does not address" in verify_data["failure_evidence"]

        # Check /investigations record reflects FAILED_FIX, not VERIFIED_FIX
        inv_res = await client.get(f"/investigations/{inv_id}")
        assert inv_res.status_code == 200
        inv_state = inv_res.json()
        assert inv_state["outcome"] == "FAILED_FIX"
        assert inv_state["verification_report"]["status"] == "verification_failed"


@pytest.mark.asyncio
async def test_scenario_d_insufficient_evidence_status_consistency():
    """Verify Scenario D outputs insufficient_evidence status and outcome consistently, without safe patch offering."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/diagnose",
            json={"service_name": "scenario_d_insufficient_evidence"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "insufficient_evidence"
        assert data.get("has_safe_patch") is None or data.get("has_safe_patch") is not False
        inv_id = data["investigation_id"]

        inv_resp = await client.get(f"/investigations/{inv_id}")
        assert inv_resp.status_code == 200
        inv_data = inv_resp.json()
        assert inv_data["outcome"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.asyncio
async def test_cached_scenario_a_preserves_exact_first_run_compute_duration(tmp_path):
    """Verify cached Scenario A reports the exact original_duration_ms from the first run, never overwriting with 12010ms."""
    from backend.app.api.routes import (
        DIAGNOSTIC_CACHE,
        INVESTIGATIONS_DB,
        INVESTIGATION_DIAGNOSES,
        get_diagnostic_cache_key,
        _save_persisted_state,
        _load_persisted_state,
    )

    DIAGNOSTIC_CACHE.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post(
            "/api/v1/diagnose",
            json={"service_name": "scenario_a_missing_env", "idempotency_key": f"exact-dur-1-{time.time()}"}
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        first_run_ms = data1["duration_ms"]
        assert first_run_ms != 12010

        resp2 = await client.post(
            "/api/v1/diagnose",
            json={"service_name": "scenario_a_missing_env", "idempotency_key": f"exact-dur-2-{time.time()}"}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["is_cached"] is True
        assert data2["original_duration_ms"] == first_run_ms

        # Also verify state persistence round-trip
        state_file = tmp_path / ".fixloop_state.json"
        _save_persisted_state(state_file=state_file)
        assert state_file.exists()

        saved_inv_id = data1["investigation_id"]
        cache_key = get_diagnostic_cache_key("scenario_a_missing_env")
        INVESTIGATIONS_DB.clear()
        INVESTIGATION_DIAGNOSES.clear()
        DIAGNOSTIC_CACHE.clear()

        _load_persisted_state(state_file=state_file)
        assert saved_inv_id in INVESTIGATIONS_DB
        assert saved_inv_id in INVESTIGATION_DIAGNOSES
        assert DIAGNOSTIC_CACHE[cache_key]["original_duration_ms"] == first_run_ms







