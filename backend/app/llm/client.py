"""Nebius Token Factory / NVIDIA Nemotron LLM Client.

Uses HTTPX for high-performance async requests to Nebius Token Factory endpoints.
Handles model routing, timeouts, fallback to mock mode, and schema validation.
"""

import logging
from typing import Any, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.core.models import (
    EvidenceItem,
    Hypothesis,
    LLMHypothesisResponse,
    LLMPatchResponse,
)
from backend.app.llm.mock_provider import MockLLMProvider
from backend.app.llm.parser import parse_structured_output
from backend.app.llm.prompts import (
    SYSTEM_HYPOTHESIS_PROMPT,
    SYSTEM_PATCH_PROMPT,
    USER_HYPOTHESIS_TEMPLATE,
    USER_PATCH_TEMPLATE,
)

logger = logging.getLogger("fixloop.llm")


class NebiusLLMClient:
    """Client for Nebius Token Factory with NVIDIA models."""

    def __init__(self):
        self.api_key = settings.get_nebius_api_key()
        self.base_url = settings.NEBIUS_BASE_URL.rstrip("/")
        self.model_name = settings.NEBIUS_MODEL
        self.use_mock = settings.USE_MOCK_LLM or not bool(self.api_key)

    async def _call_chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        """Sends an OpenAI-compatible chat completion request to Nebius Token Factory."""
        if self.use_mock:
            raise RuntimeError("Mock mode active; should not call live endpoint directly")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as exc:
                logger.error("Nebius API error (%s): %s", exc.response.status_code, exc.response.text)
                raise RuntimeError(f"Nebius API returned error {exc.response.status_code}: {exc.response.text}") from exc
            except httpx.RequestError as exc:
                logger.error("Failed to connect to Nebius API: %s", exc)
                raise RuntimeError(f"Connection failure to Nebius Token Factory ({url}): {exc}") from exc

    async def generate_hypotheses(
        self,
        scenario_name: str,
        iteration: int,
        max_iterations: int,
        evidence: List[EvidenceItem],
        current_hypotheses: List[Hypothesis],
    ) -> LLMHypothesisResponse:
        """Formulates or updates diagnostic hypotheses based on current evidence."""
        if self.use_mock:
            logger.info("Using MockLLMProvider for hypotheses (Mock/Offline mode)")
            return MockLLMProvider.get_hypotheses_for_scenario(scenario_name, iteration, evidence)

        evidence_str = "\n".join([f"[{e.id}] ({e.type}): {e.content[:500]}" for e in evidence])
        hypotheses_str = "\n".join([f"[{h.id}] {h.title} (conf: {h.confidence_score}): {h.description}" for h in current_hypotheses]) or "None yet"

        prompt = USER_HYPOTHESIS_TEMPLATE.format(
            scenario_name=scenario_name,
            iteration=iteration,
            max_iterations=max_iterations,
            evidence_formatted=evidence_str,
            hypotheses_formatted=hypotheses_str,
        )

        raw_output = await self._call_chat_completion(SYSTEM_HYPOTHESIS_PROMPT, prompt)
        return parse_structured_output(raw_output, LLMHypothesisResponse)

    async def generate_patch(
        self,
        scenario_name: str,
        hypothesis: Hypothesis,
        evidence: List[EvidenceItem],
        files_content: str,
    ) -> LLMPatchResponse:
        """Synthesizes a minimal unified diff for a confirmed hypothesis."""
        if self.use_mock:
            logger.info("Using MockLLMProvider for patch synthesis (Mock/Offline mode)")
            return MockLLMProvider.get_patch_for_scenario(scenario_name)

        evidence_str = "\n".join([f"[{e.id}] ({e.type}): {e.content[:400]}" for e in evidence])
        prompt = USER_PATCH_TEMPLATE.format(
            hypothesis_title=hypothesis.title,
            hypothesis_description=hypothesis.description,
            evidence_formatted=evidence_str,
            files_content=files_content,
        )

        raw_output = await self._call_chat_completion(SYSTEM_PATCH_PROMPT, prompt)
        return parse_structured_output(raw_output, LLMPatchResponse)
