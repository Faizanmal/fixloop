# FixLoop Sample Project: Auth & Payment Microservice

This directory contains a self-contained, safe sample Dockerized microservice designed to demonstrate FixLoop's evidence-driven root-cause analysis.

## Scenario: Service Crashloop & Missing Environment Variable

### 1. Problem Description
The `auth-service` container fails on startup with an unhandled runtime error.
When developers inspect logs, the output indicates a critical database initialization failure:
```text
KeyError: 'DATABASE_URL'
Fatal: Missing required database connection string.
```

### 2. Investigating with FixLoop

You can investigate this project safely through the web interface or via API:

#### Via Web Dashboard:
1. Open the FixLoop dashboard at `http://localhost:3000`.
2. Select **Scenario A: Missing Environment Variable** (or configure workspace path to `sample_project`).
3. Click **Start Investigation**.
4. Observe the diagnostic steps:
   - Initial logs and compose configuration are ingested.
   - Ground-truth facts isolate `DATABASE_URL` as missing from the environment.
   - Hypothesis confidence reaches **98%**.
   - A minimal unified diff patch is generated for `docker-compose.yml`.
   - Sandbox verification applies the patch in isolation, verifies syntax and env presence, and reports **VERIFIED_FIXED**.

#### Via REST API:
```powershell
curl -X POST http://localhost:8000/api/v1/investigate `
  -H "Content-Type: application/json" `
  -d '{\"scenario_name\": \"scenario_a_missing_env\"}'
```
