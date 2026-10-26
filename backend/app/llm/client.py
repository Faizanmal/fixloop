"""Nebius Token Factory / NVIDIA Nemotron LLM Client.

Uses HTTPX with explicit timeouts, controlled exponential backoff retries,
actionable error classification, and Pydantic response validation.
Never exposes API secrets in error messages or logs.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.core.models import (
    EvidenceItem,
    Hypothesis,
    LLMHypothesisResponse,
    LLMPatchResponse,
    DiagnoseRequest,
    DiagnoseResponse,
)
from backend.app.llm.exceptions import (
    NebiusError,
    NebiusAuthenticationError,
    NebiusModelNotFoundError,
    NebiusQuotaError,
    NebiusBillingError,
    NebiusTimeoutError,
    NebiusServiceError,
    NebiusConnectionError,
    ModelResponseValidationError,
)
from backend.app.llm.mock_provider import MockLLMProvider
from backend.app.llm.parser import parse_structured_output
from backend.app.llm.prompts import (
    SOFTWARE_DEBUGGING_SYSTEM_PROMPT,
    SYSTEM_HYPOTHESIS_PROMPT,
    SYSTEM_PATCH_PROMPT,
    USER_HYPOTHESIS_TEMPLATE,
    USER_PATCH_TEMPLATE,
    build_diagnose_user_prompt,
)

logger = logging.getLogger("fixloop.llm")

# Status codes considered transient and eligible for controlled retry
TRANSIENT_STATUS_CODES = {429, 502, 503, 504}


def sanitize_message(text: str, secret_key: Optional[str] = None) -> str:
    """Removes API keys and auth bearer tokens from error strings and logs."""
    if not text:
        return ""
    if secret_key and len(secret_key) > 4:
        text = text.replace(secret_key, "[REDACTED_API_KEY]")
    # Also strip generic Bearer patterns
    import re
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]{8,}", "Bearer [REDACTED_TOKEN]", text)
    return text


class NebiusLLMClient:
    """Client for Nebius Token Factory with NVIDIA open-source models."""

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.api_key = settings.get_nebius_api_key()
        self.base_url = settings.normalized_nebius_base_url
        self.default_model = settings.NEBIUS_MODEL
        self.use_mock = settings.USE_MOCK_LLM or not bool(self.api_key)
        self._custom_transport = transport

        # Explicit timeout configuration
        self.timeout = httpx.Timeout(
            connect=settings.HTTPX_CONNECT_TIMEOUT,
            read=settings.HTTPX_READ_TIMEOUT,
            write=settings.HTTPX_WRITE_TIMEOUT,
            pool=10.0,
        )
        self.max_retries = settings.HTTPX_MAX_RETRIES

    def _create_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            transport=self._custom_transport,
        )

    async def _call_chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_override: Optional[str] = None,
    ) -> str:
        """Sends an OpenAI-compatible chat completion request to Nebius Token Factory.

        Implements explicit timeouts, controlled retries with exponential backoff,
        and actionable, secret-safe error mapping.
        """
        if self.use_mock and self._custom_transport is None:
            raise RuntimeError("Mock mode active; live endpoint should not be queried directly")

        target_model = model_override or self.default_model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Content-Type": "application/json",
            "User-Agent": "FixLoop-Diagnostics-Engine/0.1.0",
        }
        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            async with self._create_http_client() as client:
                try:
                    response = await client.post(url, headers=headers, json=payload)

                    if response.status_code == 200:
                        data = response.json()
                        choices = data.get("choices", [])
                        if not choices or "message" not in choices[0]:
                            raise ModelResponseValidationError("Nebius response missing 'choices[0].message'")
                        content = choices[0]["message"].get("content", "")
                        return sanitize_message(content, self.api_key)

                    # Classify non-200 responses
                    status = response.status_code
                    error_body = sanitize_message(response.text, self.api_key)

                    if status in (401, 403):
                        logger.warning("Nebius auth rejected: %s", error_body)
                        raise NebiusAuthenticationError(
                            message=f"Nebius authentication rejected (HTTP {status}). Verify NEBIUS_API_KEY."
                        )

                    if status == 404:
                        logger.warning("Nebius model not found: %s", target_model)
                        raise NebiusModelNotFoundError(model_name=target_model)

                    if status == 402:
                        logger.warning("Nebius billing/credit required: %s", error_body)
                        raise NebiusBillingError(
                            message="Nebius account credits exhausted or billing required."
                        )

                    if status in TRANSIENT_STATUS_CODES:
                        last_error = NebiusQuotaError(
                            message=f"Nebius rate limit or transient error (HTTP {status}): {error_body}"
                        ) if status == 429 else NebiusServiceError(
                            upstream_status=status, detail=error_body
                        )
                        if attempt < self.max_retries:
                            backoff = 0.5 * (2 ** attempt)
                            logger.info("Transient error HTTP %s. Retrying in %.2fs (attempt %d/%d)", status, backoff, attempt + 1, self.max_retries)
                            await asyncio.sleep(backoff)
                            continue
                        raise last_error

                    # Other client errors (400, etc.)
                    raise NebiusError(
                        message=f"Nebius API error (HTTP {status}): {error_body}",
                        status_code=status,
                        actionable_advice="Review request format and parameters.",
                    )

                except httpx.ConnectTimeout as exc:
                    last_error = NebiusTimeoutError(settings.HTTPX_CONNECT_TIMEOUT)
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    raise last_error from exc

                except httpx.ReadTimeout as exc:
                    last_error = NebiusTimeoutError(settings.HTTPX_READ_TIMEOUT)
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    raise last_error from exc

                except (httpx.ConnectError, httpx.NetworkError) as exc:
                    safe_msg = sanitize_message(str(exc), self.api_key)
                    last_error = NebiusConnectionError(base_url=self.base_url, detail=safe_msg)
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    raise last_error from exc

        if last_error:
            raise last_error
        raise NebiusError("Unexpected failure executing request to Nebius Token Factory.")

    async def diagnose(self, request: DiagnoseRequest) -> DiagnoseResponse:
        """Performs root-cause analysis on failing services.

        Returns a validated DiagnoseResponse. In mock/offline mode, dispatches to MockLLMProvider.
        """
        # If running in mock mode and no test mock transport is injected
        if self.use_mock and self._custom_transport is None:
            logger.info("Using MockLLMProvider for diagnosis (Mock/Offline mode)")
            return MockLLMProvider.diagnose(request)

        user_prompt = build_diagnose_user_prompt(
            service_name=request.service_name or "service",
            logs=request.logs,
            docker_inspect=request.docker_inspect,
            configuration_files=request.configuration_files,
            environment_variables=request.environment_variables,
        )

        raw_output = await self._call_chat_completion(
            system_prompt=SOFTWARE_DEBUGGING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_override=request.model,
        )

        return parse_structured_output(raw_output, DiagnoseResponse)

    async def generate_hypotheses(
        self,
        scenario_name: str,
        iteration: int,
        max_iterations: int,
        evidence: List[EvidenceItem],
        current_hypotheses: List[Hypothesis],
    ) -> LLMHypothesisResponse:
        """Formulates or updates diagnostic hypotheses based on current evidence (for investigation loop)."""
        if self.use_mock and self._custom_transport is None:
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
        if self.use_mock and self._custom_transport is None:
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

    async def verify_credentials_and_model(self) -> Dict[str, Any]:
        """Validates that the Nebius API key is authentic and the target model is accessible."""
        if self.use_mock and self._custom_transport is None:
            return {
                "verified": True,
                "mode": "mock",
                "model": self.default_model,
                "message": "Deterministic mock provider active (offline/demo mode)",
            }

        url = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "User-Agent": "FixLoop-Diagnostics-Engine/0.1.0",
        }
        async with self._create_http_client() as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    model_list = [m.get("id") for m in data.get("data", [])] if isinstance(data, dict) else []
                    model_found = (self.default_model in model_list) if model_list else True
                    return {
                        "verified": True,
                        "mode": "live",
                        "model": self.default_model,
                        "model_confirmed": model_found,
                        "message": f"Successfully verified connection to Nebius Token Factory. Model: {self.default_model}",
                    }
                elif response.status_code in (401, 403):
                    return {
                        "verified": False,
                        "mode": "live",
                        "error": "Authentication failed. NEBIUS_API_KEY rejected by Nebius Token Factory.",
                        "status_code": response.status_code,
                    }
                else:
                    return {
                        "verified": False,
                        "mode": "live",
                        "error": f"Nebius Token Factory returned HTTP {response.status_code}",
                        "status_code": response.status_code,
                    }
            except httpx.TimeoutException:
                return {
                    "verified": False,
                    "mode": "live",
                    "error": "Connection to Nebius Token Factory timed out.",
                }
            except Exception as exc:
                return {
                    "verified": False,
                    "mode": "live",
                    "error": sanitize_message(str(exc), self.api_key),
                }
