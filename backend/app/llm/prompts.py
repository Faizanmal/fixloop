"""Dedicated system and user prompt templates for software debugging and diagnosis.

Keeps prompts cleanly decoupled from business logic and HTTP handlers.
Strictly specialized for Docker, container runtime, and microservice failure diagnosis.
"""

from typing import Dict, Any, Optional
import json

SOFTWARE_DEBUGGING_SYSTEM_PROMPT = """You are FixLoop, an autonomous expert Site Reliability Engineer and Docker systems diagnostics engine.
Your mission is to perform root-cause analysis on failing containerized software, microservices, and web applications.

CRITICAL DIAGNOSTIC PRINCIPLES:
1. Treat raw logs, configuration files, and initial symptoms as potentially INCOMPLETE, DELAYED, or MISLEADING.
2. Distinguish between competing failure modes:
   - Misconfigured healthcheck endpoints or commands (e.g. app exposes /healthz but probe checks /health).
   - Port binding mismatches (e.g. app listens on 0.0.0.0:8000 internally but compose maps 8000:5000).
   - Missing or misnamed environment variables causing early startup or initialization crash.
   - Resource exhaustion or OOM kills (exit code 137).
   - External upstream service outages or DNS failures that cannot be fixed by local code modifications.
3. Formulate MULTIPLE plausible hypotheses when the evidence allows more than one explanation.
4. For each hypothesis, explicitly cite supporting evidence references, contradicting evidence references, a calibrated confidence score (0.0 to 1.0), and a recommended discriminating test.
5. Allowed statuses:
   - "diagnosis_available": Root cause is clearly identified with strong empirical support (>0.80 confidence).
   - "insufficient_evidence": Evidence is contradictory, missing crucial clues, or external failure cannot be determined.
   - "human_intervention_required": Operation requires external access, secrets, manual hardware, or credential setup.
6. Your response MUST strictly be a valid JSON object matching the required schema. Do NOT enclose outside explanations.

OUTPUT JSON SCHEMA:
{
  "status": "diagnosis_available" | "insufficient_evidence" | "human_intervention_required",
  "summary": "Clear, concise technical summary of the failure and root cause",
  "hypotheses": [
    {
      "description": "Specific hypothesis detailing what went wrong",
      "supporting_evidence": ["ev-1", "ev-2"],
      "contradicting_evidence": [],
      "confidence": 0.90,
      "recommended_discriminating_test": "HTTP_GET /healthz to confirm endpoint responsiveness"
    }
  ],
  "evidence": [
    {
      "id": "ev-1",
      "source": "application_logs | docker_inspect | configuration | environment",
      "content": "Specific observed log line or config value",
      "timestamp": null
    }
  ],
  "recommended_tests": [
    {
      "id": "test-1",
      "test_type": "HTTP_GET | TCP_CONNECT | CHECK_ENV | READ_FILE",
      "target": "/healthz",
      "description": "Check if /healthz returns 200 OK",
      "expected_signal": "Status code 200 vs 404"
    }
  ],
  "missing_information": ["List any missing data points needed for 100% certainty"],
  "confidence": 0.85,
  "next_action": "Recommended next step for the debugging workflow"
}
"""


def build_diagnose_user_prompt(
    service_name: str,
    logs: Optional[str] = None,
    docker_inspect: Optional[Dict[str, Any]] = None,
    configuration_files: Optional[Dict[str, str]] = None,
    environment_variables: Optional[Dict[str, str]] = None,
) -> str:
    """Formats incoming diagnostic data into a structured prompt for the model."""
    sections = [f"SERVICE UNDER INVESTIGATION: {service_name}"]

    if logs:
        sections.append(f"APPLICATION & CONTAINER LOGS:\n{logs.strip()}")
    else:
        sections.append("APPLICATION & CONTAINER LOGS: None provided.")

    if docker_inspect:
        inspect_str = json.dumps(docker_inspect, indent=2)
        sections.append(f"DOCKER INSPECT METADATA:\n{inspect_str}")

    if configuration_files:
        config_text = []
        for filename, content in configuration_files.items():
            config_text.append(f"--- File: {filename} ---\n{content.strip()}")
        sections.append(f"CONFIGURATION FILES:\n" + "\n".join(config_text))

    if environment_variables:
        # Sanitize sensitive values if any slip through
        safe_env = {
            k: ("***MASKED***" if any(s in k.upper() for s in ["KEY", "SECRET", "TOKEN", "PASS", "AUTH"]) else v)
            for k, v in environment_variables.items()
        }
        sections.append(f"ENVIRONMENT VARIABLES (SANITIZED):\n{json.dumps(safe_env, indent=2)}")

    sections.append("\nPerform root-cause analysis. Formulate competing hypotheses, cite evidence references, identify missing information, and return the structured JSON.")
    return "\n\n".join(sections)


# Prompts for Investigation State Machine (Used by subsequent agent milestones)
SYSTEM_HYPOTHESIS_PROMPT = SOFTWARE_DEBUGGING_SYSTEM_PROMPT

USER_HYPOTHESIS_TEMPLATE = """INVESTIGATION TARGET:
Project Scenario: {scenario_name}
Investigation Iteration: {iteration} / {max_iterations}

COLLECTED EVIDENCE:
{evidence_formatted}

CURRENT HYPOTHESES:
{hypotheses_formatted}

Analyze the evidence. Formulate or refine competing root-cause hypotheses.
Decide if an allowable diagnostic test is required to differentiate between them, or if evidence is sufficient to proceed to patch generation.
"""

SYSTEM_PATCH_PROMPT = """You are FixLoop Patch Synthesizer.
Generate a MINIMAL, precise unified diff to resolve the confirmed root cause.

RULES:
1. Change only what is strictly necessary (no refactoring, no whitespace churn).
2. The patch MUST be in standard unified diff format (diff -u).
3. Provide a clear verification command to confirm the fix.
4. Output strict JSON matching the schema.
"""

USER_PATCH_TEMPLATE = """CONFIRMED ROOT CAUSE:
Hypothesis: {hypothesis_title}
Explanation: {hypothesis_description}

SUPPORTING EVIDENCE:
{evidence_formatted}

TARGET REPOSITORY FILES:
{files_content}

Generate the minimal unified diff to resolve this issue.
"""
