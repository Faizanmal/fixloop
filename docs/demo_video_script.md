# FixLoop: Official Hackathon Video Demo Script & Storyboard

> **Target Duration**: 2 minutes 45 seconds (Strictly under the 3-minute limit)  
> **Format**: Screencast + Voiceover with synchronized picture-in-picture / callout graphics  
> **Hackathon**: Nebius x NVIDIA Global AI Hackathon 2026 (Coding and Agentic Engineering Track)  
> **Key Technologies Highlighted**: Nebius Token Factory, NVIDIA Nemotron-3-Nano-30B-A3B, Next.js Dashboard, FastAPI Engine

---

## Visual Cue & Voiceover Timeline

```mermaid
timeline
    title 2:45 Hackathon Demo Timeline
    00:00 - 00:25 : Problem Hook (Silent Healthcheck Failure)
    00:25 - 00:55 : Evidence Ingestion & Competing Hypotheses
    00:55 - 01:25 : Controlled Diagnostic Probe (Healthz vs Health)
    01:25 - 01:50 : Minimal Unified Diff Patch Generation
    01:50 - 02:15 : Real Sandboxed Verification Check
    02:15 - 02:30 : Honesty Under Ambiguity (Scenario D - Zero Hallucination)
    02:30 - 02:45 : Nebius + NVIDIA Architecture & Closing Impact
```

---

### Segment 1: The Problem Hook — The "Healthy" Container That Fails (0:00 - 0:25)

**Visuals**:
- Split screen: Left shows terminal with clean Docker application startup logs (`INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)`).
- Right shows `docker ps` indicating `(unhealthy)` status with failing streak 4.
- Browser opens to FixLoop dashboard at `http://localhost:3000`.

**Voiceover (Speaker)**:
> *"Every DevOps engineer has lived through this nightmare: your microservice logs show a clean, green boot. No stack traces, no errors. Yet Docker repeatedly marks the container as unhealthy, and orchestrators start killing it in an endless crashloop.*
> 
> *Generic chatbots and naive log-summarizers fail here because the logs contain no errors. They hallucinate non-existent database bugs.*
> 
> *Meet **FixLoop**: an evidence-driven autonomous debugging agent built on Nebius Token Factory and NVIDIA Nemotron."*

---

### Segment 2: Evidence Ingestion & Formulating Competing Hypotheses (0:25 - 0:55)

**Visuals**:
- On FixLoop dashboard, select **Scenario B: Misconfigured Healthcheck Endpoint**.
- Click **"Start Autonomous Investigation"**.
- The **Diagnostic Timeline** activates in real time.
- The **Collected Evidence Store** populates with:
  1. `[ev-1] LOGS`: Uvicorn listening on port 8000.
  2. `[ev-2] DOCKER_INSPECT`: Health Status `unhealthy`, FailingStreak: 4, ExitCode: 0.
  3. `[ev-3] CONFIG_COMPOSE`: Healthcheck command: `curl -f http://localhost:8000/health`.
- The **Competing Hypotheses** panel appears:
  - Hypothesis 1: Healthcheck probing wrong path (Confidence: 65%).
  - Hypothesis 2: Application port 8000 not bound to 0.0.0.0 (Confidence: 25%).
  - Hypothesis 3: Slow container startup timeout (Confidence: 10%).

**Voiceover (Speaker)**:
> *"Instead of guessing, FixLoop initiates an empirical scientific cycle. It ingests container logs, Docker inspect metadata, and runtime compose configurations.*
> 
> *Powered by the `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` model via Nebius Token Factory, FixLoop generates multiple competing root-cause hypotheses with explicit confidence and uncertainty scores."*

---

### Segment 3: Selecting & Executing a Discriminating Probe (0:55 - 1:25)

**Visuals**:
- Timeline highlights step: **"Executing Discriminating Diagnostic Probe"**.
- Probe card shows: `HTTP_GET /healthz` vs `HTTP_GET /health` from strict security allowlist.
- Probe execution output appears in Evidence Store:
  - `GET http://localhost:8000/health` -> `HTTP 404 Not Found`
  - `GET http://localhost:8000/healthz` -> `HTTP 200 OK {"status":"healthy"}`
- Hypothesis confidence jumps from **65% to 98%** for *"Mismatched healthcheck endpoint path"*.
- Competing hypotheses are updated with supporting and contradicting evidence badges.

**Voiceover (Speaker)**:
> *"To eliminate guesswork, FixLoop dispatches a controlled diagnostic probe from a strict security allowlist. It doesn't run arbitrary shell scripts.*
> 
> *It performs an empirical probe comparing the compose test path against the application's registered routes. In milliseconds, the probe confirms: `/health` returns a 404, while `/healthz` returns 200 OK.*
> 
> *Supporting evidence is attached, confidence surges to 98%, and the competing theories are definitively refuted."*

---

### Segment 4: Generating Minimal Unified Diff Patch (1:25 - 1:50)

**Visuals**:
- The **Patch Review** panel slides into view with syntax-highlighted unified diff:
  ```diff
  --- a/docker-compose.yml
  +++ b/docker-compose.yml
  @@ -8,3 +8,3 @@
       healthcheck:
  -      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  +      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
  ```
- Clear badge displayed: `Status: Proposed (Not Applied)`.
- Rationale note: *"Updated compose healthcheck endpoint to match active /healthz route. Preserves existing intervals and retry policies."*

**Voiceover (Speaker)**:
> *"Because confidence exceeded the 90% threshold, FixLoop invokes the NVIDIA Nemotron model to synthesize a minimal unified diff.*
> 
> *Notice that FixLoop does not rewrite the entire compose file or introduce side effects. It alters only the single offending line. The UI clearly signals that this patch is proposed and pending verification."*

---

### Segment 5: Sandboxed Verification Ground Truth (1:50 - 2:15)

**Visuals**:
- User clicks **"Run Sandboxed Verification"** (or engine auto-verifies).
- **Verification Report** card animates:
  - `Isolated Sandbox Execution`: Target container booted with candidate patch.
  - `Health Probe`: `http://localhost:8000/healthz` returns `200 OK`.
  - `Status Indicator`: `PASSED (Exit Code: 0, Duration: 42ms)`.
  - `Outcome`: **`VERIFIED_FIXED`**.
- Baseline Comparison callout appears: *"Log-only LLM: Inconclusive / Failed. FixLoop: Verified Fixed."*

**Voiceover (Speaker)**:
> *"Next comes the core differentiator: FixLoop never trusts an LLM's self-attestation that a bug is fixed. It applies the patch inside an isolated sandbox and executes actual container health checks.*
> 
> *The exit code returns 0, the container transitions to healthy, and FixLoop reports a Verified Fix backed by empirical ground truth."*

---

### Segment 6: Honesty Under Ambiguity — Scenario D (2:15 - 2:30)

**Visuals**:
- Switch to **Scenario D: Upstream Cloud Outage**.
- Click **"Start Autonomous Investigation"**.
- Ingested evidence shows 503 Gateway Timeouts from a third-party payment API.
- Engine inspects local configuration, verifies local DNS and network are intact, and concludes root cause is external.
- Banner displays: **`OUTCOME: INSUFFICIENT_EVIDENCE / EXTERNAL_DEPENDENCY`**.
- Diff view remains empty with badge: `Patch Refused: Local Code Changes Cannot Resolve External Outage`.

**Voiceover (Speaker)**:
> *"Crucially, what happens when an issue is ambiguous or caused by an external cloud outage?*
> 
> *Here in Scenario D, FixLoop recognizes that an upstream payment gateway is timing out. While naive agents hallucinate unnecessary local code rewrites, FixLoop honestly halts at Insufficient Evidence, reporting 0 false claims of success across our benchmark."*

---

### Segment 7: Nebius Token Factory Architecture & Closing (2:30 - 2:45)

**Visuals**:
- Architecture diagram shows Next.js frontend, FastAPI backend, Nebius Token Factory inference calling `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, and isolated Docker sandboxes.
- Benchmark stats pop up:
  - **100% Root-Cause Accuracy**
  - **0 False Claims of Success**
  - **$0.00018 inference cost per investigation**
- GitHub repo and live demo URLs on screen: `https://github.com/Faizanmal/fixloop`.

**Voiceover (Speaker)**:
> *"FixLoop is powered by Nebius Token Factory's ultra-low-latency API, making NVIDIA Nemotron's 30B reasoning fast and affordable at less than two-tenths of a cent per investigation.*
> 
> *FixLoop: Stop guessing logs. Start verifying fixes. Built for the Nebius x NVIDIA Global AI Hackathon 2026."*

---
