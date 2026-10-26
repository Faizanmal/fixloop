"""JSON parsing and Pydantic validation utilities for LLM outputs."""

import json
import re
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json_from_llm_response(text: str) -> str:
    """Extracts raw JSON payload from potentially markdown-wrapped LLM text."""
    text = text.strip()

    # Look for ```json ... ``` code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # Look for outermost curly braces
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1].strip()

    return text


def parse_structured_output(raw_text: str, model_cls: Type[T]) -> T:
    """Extracts and validates structured JSON into the target Pydantic model class."""
    cleaned = extract_json_from_llm_response(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse LLM output as JSON: {exc}. Raw snippet: {raw_text[:200]}") from exc

    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON failed schema validation for {model_cls.__name__}: {exc}") from exc
