# FixLoop: Implementation Milestones, Acceptance Criteria & Risk Analysis

This document defines the 5 independently testable development milestones, acceptance criteria, verification commands, and the risk register for FixLoop.

---

## 1. Milestone Roadmap

### Milestone 1: Environment, Domain Schemas & Safety Guardrails (Current Baseline)
- **Scope**:
  - Environment inspection & dependency baseline (Python 3.13, Node v26, Docker).
  - Pydantic domain models for evidence, hypotheses, diagnostic actions, patches, and verification.
  - Strict diagnostic probe allowlist (`DiagnosticAllowlist`) blocking shell injection and path traversal.
  - Mock LLM provider for deterministic offline verification.
- **Acceptance Criteria**:
  - Unit test suite passes for domain model boundaries and allowlist rejection tests.
  - Shell injection characters (`;&|`$<>`) are rejected with explicit `SecurityViolation` or validation failure.
  - Path traversal attempts (`..`) in file inspection probes are prevented.
- **Validation Command**:
  ```powershell
  pytest backend/tests/test_models.py backend/tests/test_allowlist.py -v
  ```

---

### Milestone 2: Evidence Collector & Controlled Diagnostic Probe Engine
- **Scope**:
  - `DockerAdapter` and `MockSandbox`: Ingest container logs, inspect metadata, compose files, and environment definitions.
  - Implement execution handlers for all allowed probe types:
    - `HTTP_GET`: Async HTTP probe querying endpoints and returning status code, headers, and body snippet.
    - `TCP_CONNECT`: Socket connection test on target ports.
    - `READ_TARGET_FILE`: Safe file reader constrained to workspace directory.
    - `CHECK_ENV_KEY_EXISTS`: Safe environment key existence checker.
  - Human approval gate for stateful container operations (restarts, rebuilds).
- **Acceptance Criteria**:
  - Diagnostic probes return structured `EvidenceItem` objects.
  - Unauthorized probe requests raise clear security errors.
  - Simulated container inspects extract `Health.Status` and `ExitCode`.
- **Validation Command**:
  ```powershell
  pytest backend/tests/test_diagnostic_runner.py -v
  ```

---

### Milestone 3: Nebius Token Factory & NVIDIA Nemotron Integration
- **Scope**:
  - Async HTTPX client connecting to `https://api.tokenfactory.nebius.com/v1/chat/completions`.
  - Target model configuration: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`.
  - Externalized prompt templates for hypothesis generation and patch synthesis.
  - Structured output parsing with automatic JSON extraction and Pydantic schema validation.
  - Graceful fallback to `MockLLMProvider` when `NEBIUS_API_KEY` is absent or mock mode is toggled.
- **Acceptance Criteria**:
  - When API key is provided, successfully generates valid `LLMHypothesisResponse` from Nebius.
  - When API key is absent, returns clean diagnostic status and routes through mock provider without crashing.
  - Model responses with markdown fences are cleanly parsed into Pydantic models.
- **Validation Command**:
  ```powershell
  pytest backend/tests/test_llm_client.py -v
  ```

---

### Milestone 4: Autonomous Reasoning Loop & 4 Benchmark Scenarios
- **Scope**:
  - Implement `InvestigationStateMachine` orchestrating the full investigation lifecycle.
  - Build the 4 benchmark Dockerized sample scenarios:
    1. **Scenario 1 (Healthcheck Misconfig)**: App listens at `/healthz`; compose probes `/health`. Agent uses `HTTP_GET` probe to discover mismatch and patches `docker-compose.yml`.
    2. **Scenario 2 (Port Mismatch)**: App listens on 8000; compose exposes 5000. Agent uses `TCP_CONNECT` probe to verify active port and patches port mapping.
    3. **Scenario 3 (Missing Env Variable)**: App crashes silently on boot; agent inspects config/env schema and patches missing `DATABASE_URL`.
    4. **Scenario 4 (Ambiguous / Upstream Outage)**: External dependency failure; agent collects evidence, determines failure cannot be resolved locally, and issues honest `INSUFFICIENT_EVIDENCE` report.
  - Patch verification engine applying unified diffs in staging containers and verifying health.
- **Acceptance Criteria**:
  - All 3 fixable scenarios achieve verified patch and healthy container status.
  - Scenario 4 correctly refuses to generate a fake fix and reports `INSUFFICIENT_EVIDENCE`.
  - No scenario crashes or hangs beyond the 5-iteration limit.
- **Validation Command**:
  ```powershell
  pytest backend/tests/test_agent_loop.py -v
  ```

---

### Milestone 5: Next.js Observability Dashboard & End-to-End Demo Polish
- **Scope**:
  - Next.js 14 App Router frontend with TypeScript, Tailwind CSS, and Shadcn UI.
  - High-density dark mode dashboard:
    - Live Nebius Model Badge (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) & Docker status.
    - One-click scenario runner.
    - State machine stepper showing active phase.
    - Hypotheses matrix with confidence bars and supporting/refuting evidence tags.
    - Diagnostic console logging executed probes.
    - Patch viewer displaying color-coded unified diff.
    - Verification outcome badge (`VERIFIED_FIX`, `INSUFFICIENT_EVIDENCE`).
- **Acceptance Criteria**:
  - Complete end-to-end run executable from UI or CLI.
  - Clean error handling when Docker daemon is stopped (displays clear user guidance).
  - Production-ready documentation, architecture diagrams, and submission assets.
- **Validation Command**:
  ```powershell
  npm --prefix frontend run build
  ```

---

## 2. Technical Risk Register & Mitigations

| # | Technical Risk | Severity | Probability | Mitigation Strategy |
|---|---|---|---|---|
| **R1** | **Docker Daemon Unavailability on Host** | High | Medium | Provide a dual-mode sandbox: full live Docker mode when daemon is running, and an accurate container simulator (`MockSandbox`) with identical filesystem, socket, and healthcheck contracts for testing/grading environments without Docker Desktop active. |
| **R2** | **Nebius Token Factory Rate Limits or Key Absence** | High | Low | Implement robust retry with exponential backoff in HTTPX client. Include deterministic `MockLLMProvider` so evaluation can proceed offline without live cloud credentials. |
| **R3** | **LLM JSON Schema Deviations** | Medium | Medium | Use low temperature (0.1) and strict system prompts. Implement resilient JSON extraction in `parser.py` that strips code fences and extracts raw JSON. Include fallback schema validation. |
| **R4** | **Host Command Injection from Untrusted LLM Output** | Critical | Low | Zero host command execution policy. All diagnostic actions must match the strict `DiagnosticAllowlist`. Any input containing shell metacharacters (`;&|`$<>`) is rejected immediately. |
| **R5** | **Infinite Reasoning Loops** | Medium | Low | Hard ceiling of `max_iterations = 5` per investigation. If confidence threshold is not reached within 5 iterations, state machine terminates with `INSUFFICIENT_EVIDENCE`. |
