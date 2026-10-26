# FixLoop: REST API Contracts & Schema Definitions

Version: `0.1.0`  
Base URL: `http://localhost:8000/api`

---

## 1. System Health & Environment Status

### `GET /api/health`
Returns system status, Nebius Token Factory connectivity, and Docker daemon state.

**Response `200 OK`**:
```json
{
  "status": "online",
  "nebius": {
    "configured": true,
    "base_url": "https://api.tokenfactory.nebius.com/v1/",
    "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "mock_mode": false
  },
  "docker": {
    "available": true,
    "server_version": "27.2.0"
  },
  "active_investigations_count": 0
}
```

---

## 2. Benchmark Scenarios

### `GET /api/scenarios`
Returns the list of reproducible Docker failure scenarios.

**Response `200 OK`**:
```json
[
  {
    "id": "scenario_1_healthcheck",
    "name": "Scenario 1: Misconfigured Healthcheck Endpoint",
    "description": "Container runs normally at /healthz, but docker-compose checks /health, causing repeated unhealthy status.",
    "difficulty": "Easy",
    "requires_probe": true
  },
  {
    "id": "scenario_2_port_mismatch",
    "name": "Scenario 2: Service Port Mapping Mismatch",
    "description": "Application listens on port 8000 internally, but compose publishes 8000:5000, causing connection refused on host.",
    "difficulty": "Easy",
    "requires_probe": true
  },
  {
    "id": "scenario_3_missing_env",
    "name": "Scenario 3: Missing Environment Variable with Ambiguous Logs",
    "description": "App silently fails on boot without explicit missing variable name. Diagnostic probe inspects env schema to pinpoint DATABASE_URL.",
    "difficulty": "Medium",
    "requires_probe": true
  },
  {
    "id": "scenario_4_ambiguous_failure",
    "name": "Scenario 4: Upstream Outage / Insufficient Evidence",
    "description": "Container fails due to an external network dependency. FixLoop detects insufficient evidence and honestly refuses to invent an unverified fix.",
    "difficulty": "Hard",
    "requires_probe": false
  }
]
```

---

## 3. Investigation Lifecycle

### `POST /api/investigations/start`
Starts an autonomous debugging investigation for a scenario or custom project repository.

**Request Body**:
```json
{
  "scenario_name": "scenario_1_healthcheck",
  "custom_repo_path": null,
  "max_iterations": 5
}
```

**Response `201 Created`**:
```json
{
  "id": "inv-20261026-001",
  "scenario_name": "scenario_1_healthcheck",
  "project_path": "scenarios/scenario_1_healthcheck",
  "status": "COLLECTING_INITIAL_EVIDENCE",
  "iteration": 0,
  "max_iterations": 5,
  "evidence_store": [],
  "hypotheses": [],
  "diagnostic_history": [],
  "candidate_patch": null,
  "verification_result": null,
  "outcome": null,
  "started_at": "2026-10-26T14:00:00Z",
  "updated_at": "2026-10-26T14:00:00Z"
}
```

---

### `GET /api/investigations/{id}`
Retrieves the full live state of an active or completed investigation.

**Response `200 OK`**:
```json
{
  "id": "inv-20261026-001",
  "scenario_name": "scenario_1_healthcheck",
  "status": "COMPLETED",
  "iteration": 2,
  "max_iterations": 5,
  "evidence_store": [
    {
      "id": "ev-1",
      "type": "LOGS",
      "source": "docker.logs",
      "timestamp": "2026-10-26T14:00:01Z",
      "content": "INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)",
      "is_initial": true
    },
    {
      "id": "ev-2",
      "type": "DOCKER_INSPECT",
      "source": "docker.inspect",
      "timestamp": "2026-10-26T14:00:02Z",
      "content": "{\"Health\": {\"Status\": \"unhealthy\", \"FailingStreak\": 4}}",
      "is_initial": true
    },
    {
      "id": "ev-3",
      "type": "DIAGNOSTIC_OUTPUT",
      "source": "probe.http_get",
      "timestamp": "2026-10-26T14:00:04Z",
      "content": "GET http://localhost:8000/healthz returned HTTP 200 OK. Body: {\"status\":\"ok\"}",
      "is_initial": false
    }
  ],
  "hypotheses": [
    {
      "id": "hyp-1",
      "title": "Mismatched healthcheck endpoint path",
      "description": "Application exposes /healthz; docker-compose.yml mistakenly probes /health",
      "category": "HEALTHCHECK_MISCONFIG",
      "confidence_score": 0.98,
      "supporting_evidence_ids": ["ev-1", "ev-2", "ev-3"],
      "contradicting_evidence_ids": []
    }
  ],
  "candidate_patch": {
    "id": "patch-1",
    "hypothesis_id": "hyp-1",
    "target_file": "docker-compose.yml",
    "diff_unified": "--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,3 +8,3 @@\n     healthcheck:\n-      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/health\"]\n+      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/healthz\"]\n",
    "explanation": "Updated healthcheck test endpoint to match the active /healthz route.",
    "is_minimal": true
  },
  "verification_result": {
    "status": "PASSED",
    "exit_code": 0,
    "test_output": "Container scenario1_app transitioned to healthy state.",
    "duration_ms": 1250,
    "verified_at": "2026-10-26T14:00:10Z"
  },
  "outcome": "VERIFIED_FIX",
  "outcome_summary": "Root cause confirmed and patch verified: healthcheck path corrected from /health to /healthz."
}
```

---

### `POST /api/investigations/{id}/approve`
Human approval gate for sensitive or state-altering diagnostic operations.

**Request Body**:
```json
{
  "action_id": "act-restart-1",
  "approved": true,
  "comments": "Approved container restart in isolated test network"
}
```

**Response `200 OK`**:
```json
{
  "status": "APPROVED",
  "action_id": "act-restart-1",
  "resumed": true
}
```

---

## 4. Direct Diagnostic & Verification Endpoints

### `POST /api/v1/diagnose`
Performs one-shot root-cause analysis on failing services without running the multi-step investigation state machine.

**Request Body**:
```json
{
  "service_name": "payment-api",
  "logs": "KeyError: 'DATABASE_URL'",
  "docker_inspect": { "State": { "ExitCode": 1 } },
  "configuration_files": { "docker-compose.yml": "version: '3.8'..." },
  "environment_variables": { "PORT": "8080" },
  "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
}
```

**Response `200 OK`**:
```json
{
  "status": "diagnosis_available",
  "summary": "Service failed during boot due to missing DATABASE_URL.",
  "hypotheses": [
    {
      "description": "Missing required environment variable DATABASE_URL",
      "supporting_evidence": ["ev-1"],
      "contradicting_evidence": [],
      "confidence": 0.98,
      "recommended_discriminating_test": "check_env_key DATABASE_URL"
    }
  ],
  "confidence": 0.98,
  "next_action": "Configure DATABASE_URL in docker-compose.yml"
}
```

---

### `POST /api/v1/verify`
Executes an isolated, sandboxed verification check on a proposed unified diff patch.

**Request Body**:
```json
{
  "scenario_name": "scenario_a_missing_env",
  "patch_proposal": {
    "id": "patch-1",
    "hypothesis_id": "hyp-1",
    "target_file": "docker-compose.yml",
    "diff_unified": "--- a/docker-compose.yml\n+++ b/docker-compose.yml\n...",
    "explanation": "Add DATABASE_URL",
    "verification_procedure": "verify_env_presence"
  },
  "user_approved": true
}
```

**Response `200 OK`**:
```json
{
  "status": "verified_fixed",
  "patch_id": "patch-1",
  "target_file": "docker-compose.yml",
  "test_output": "Verified: DATABASE_URL successfully declared in docker-compose.yml environment block.",
  "expected_criteria": "DATABASE_URL is declared in compose environment",
  "attempts": 1,
  "reverted": true,
  "duration_ms": 45
}
```

---

## 5. System Liveness & Readiness Probes

- `GET /health`: Liveness probe returning `{ "status": "online", "version": "0.1.0" }`.
- `GET /ready`: Readiness probe evaluating Nebius Token Factory credentials and system dependencies `{ "ready": true, "issues": [] }`.
