"""Credentials remain outside application persistence and backup artifacts."""
import os
import re
from typing import Protocol


class SecretsService(Protocol):
    def get(self, reference: str) -> str | None: ...


class EnvironmentSecrets:
    """Existing deployment contract; future vault adapters implement the same interface."""
    def get(self, reference: str) -> str | None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", reference):
            return None
        return os.getenv(reference)


def credential_status(reference: str, service: SecretsService | None = None) -> dict:
    stored = False
    if service is None and os.name == "nt":
        from .windows_credentials import WindowsCredentials
        try:
            stored = bool(WindowsCredentials().get(reference))
        except OSError:
            pass  # A locked OS vault must not prevent offline local analytics.
    available = stored or bool((service or EnvironmentSecrets()).get(reference))
    return {"credential_available": available, "masked_credential": "********" if available else None,
            "secret_stored": stored}
