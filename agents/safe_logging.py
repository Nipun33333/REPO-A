"""Credential-safe diagnostics: errors expose metadata, never provider text."""
import os
import re


_ERROR_TYPES = {
    "HTTPError", "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
    "SSLError", "JSONDecodeError", "PermissionError", "FileNotFoundError",
    "OSError", "RuntimeError", "ValueError", "TypeError", "ClientError",
    "ServerError", "APIError", "TimeoutError", "UnicodeDecodeError",
}


def _status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


class SanitizedServiceError(RuntimeError):
    """Carries only an allowlisted error type and numeric HTTP status."""

    def __init__(self, error_type, status_code=None):
        self.error_type = error_type if error_type in _ERROR_TYPES else "Exception"
        self.status_code = _status(status_code)
        message = self.error_type
        if self.status_code is not None:
            message += f" (HTTP {self.status_code})"
        super().__init__(message)

    @classmethod
    def from_exception(cls, exc):
        if isinstance(exc, cls):
            return cls(exc.error_type, exc.status_code)
        response = getattr(exc, "response", None)
        # Requests responses with HTTP errors are falsey; do not use `if response`.
        status = _status(getattr(response, "status_code", None))
        if status is None:
            status = _status(getattr(exc, "status_code", None))
        if status is None:
            status = _status(getattr(exc, "code", None))
        return cls(type(exc).__name__, status)


def safe_error_summary(exc):
    # Never call str(exc), inspect its URL, or serialize headers/body/request.
    return str(SanitizedServiceError.from_exception(exc))


def safe_log_text(value):
    """Protect source/topic labels as well as errors, without changing content."""
    import config

    text = str(value)
    for name, secret in list(os.environ.items()) + list(vars(config).items()):
        if (re.search(r"API_KEY|TOKEN|SECRET|PASSWORD|COOKIE|CREDENTIAL|CLIENT_ID", name, re.I)
                and isinstance(secret, str) and len(secret) >= 4):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://\S+", "[URL omitted]", text, flags=re.I)
    text = re.sub(r"AIza[\w-]+|ya29\.[\w.-]+|1//[\w-]+|GOCSPX-[\w-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+|(?:api_key|access_token|refresh_token|client_secret|password|cookie)\s*[=:]\s*)\S+", r"\1[REDACTED]", text)
    return text.replace("\r", " ").replace("\n", " ")
