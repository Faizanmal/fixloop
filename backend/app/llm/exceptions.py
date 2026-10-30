"""Actionable, secret-safe custom exceptions for Nebius Token Factory inference."""


class NebiusError(Exception):
    """Base exception for all Nebius client and inference operations."""

    def __init__(
        self, message: str, status_code: int = 500, actionable_advice: str = ""
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.actionable_advice = actionable_advice


class NebiusAuthenticationError(NebiusError):
    """Raised when API key is missing, invalid, or unauthorized (HTTP 401/403)."""

    def __init__(
        self,
        message: str = "Nebius authentication failed. Verify NEBIUS_API_KEY in environment or .env file.",
    ):
        super().__init__(
            message=message,
            status_code=401,
            actionable_advice="Ensure NEBIUS_API_KEY is configured with a valid token from Nebius Token Factory.",
        )


class NebiusModelNotFoundError(NebiusError):
    """Raised when the specified model ID is not available or endpoint does not exist (HTTP 404)."""

    def __init__(self, model_name: str):
        super().__init__(
            message=f"Model '{model_name}' was not found or is not available on Nebius Token Factory.",
            status_code=404,
            actionable_advice=f"Verify that model '{model_name}' is supported and deployed in your Nebius project, or update NEBIUS_MODEL.",
        )


class NebiusQuotaError(NebiusError):
    """Raised when request rate limits or token quotas are exceeded (HTTP 429)."""

    def __init__(
        self, message: str = "Nebius Token Factory rate limit or quota exceeded."
    ):
        super().__init__(
            message=message,
            status_code=429,
            actionable_advice="Check your Nebius account token quota, concurrent request limits, or back off and retry.",
        )


class NebiusBillingError(NebiusError):
    """Raised when payment or active credits are required (HTTP 402)."""

    def __init__(
        self, message: str = "Nebius account billing or credit balance required."
    ):
        super().__init__(
            message=message,
            status_code=402,
            actionable_advice="Check account balance and billing details in the Nebius Console.",
        )


class NebiusTimeoutError(NebiusError):
    """Raised when request times out."""

    def __init__(self, timeout_seconds: float):
        super().__init__(
            message=f"Request to Nebius Token Factory timed out after {timeout_seconds:.1f}s.",
            status_code=504,
            actionable_advice="Consider increasing HTTPX_READ_TIMEOUT or retrying when server load decreases.",
        )


class NebiusServiceError(NebiusError):
    """Raised when Nebius upstream servers encounter 5xx errors."""

    def __init__(self, upstream_status: int, detail: str = ""):
        super().__init__(
            message=f"Nebius Token Factory upstream service error (HTTP {upstream_status}).",
            status_code=502,
            actionable_advice="Nebius upstream service is experiencing issues. Retry in a few moments.",
        )


class NebiusConnectionError(NebiusError):
    """Raised on network connection failures to Nebius endpoints."""

    def __init__(self, base_url: str, detail: str = ""):
        super().__init__(
            message=f"Failed to establish connection to Nebius Token Factory ({base_url}).",
            status_code=503,
            actionable_advice="Verify internet connection and ensure NEBIUS_BASE_URL is reachable.",
        )


class ModelResponseValidationError(NebiusError):
    """Raised when model output fails JSON parsing or Pydantic schema validation."""

    def __init__(self, detail: str):
        super().__init__(
            message=f"Model generated invalid response structure: {detail}",
            status_code=502,
            actionable_advice="The model response did not conform to the required JSON schema.",
        )
