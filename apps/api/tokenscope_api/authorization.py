"""Identity boundary and backend permissions. No identity is accepted from role headers."""
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
import os
from typing import Protocol

from fastapi import HTTPException, Request


class Role(str, Enum):
    VIEWER = "Viewer"
    ANALYST = "Analyst"
    ADMINISTRATOR = "Administrator"


@dataclass(frozen=True)
class Identity:
    subject: str
    role: Role
    organization: str | None = None
    issuer: str = "local-desktop"


class IdentityProvider(Protocol):
    async def authenticate(self, request: Request) -> Identity:
        """Validate signature, issuer, audience, expiry and organizational membership."""
        ...


actor_context: ContextVar[str] = ContextVar("audit_actor", default="local-administrator")
PERMISSIONS = {
    Role.VIEWER: frozenset({"read"}),
    Role.ANALYST: frozenset({"read", "import", "scenario", "report", "budget"}),
    Role.ADMINISTRATOR: frozenset({"read", "import", "scenario", "report", "budget", "admin"}),
}


async def resolve_identity(request: Request) -> Identity:
    mode = os.getenv("AIOPT_OPERATING_MODE", "local").lower()
    if mode == "local":
        return Identity("local-administrator", Role.ADMINISTRATOR)
    # Configuration is deliberately insufficient to activate remote identity.
    # A deployment must attach a real, tested validator on the server.
    provider = getattr(request.app.state, "identity_provider", None)
    if mode != "enterprise" or provider is None:
        raise HTTPException(503, "Enterprise identity validation is not configured")
    identity = await provider.authenticate(request)
    if not isinstance(identity, Identity) or not identity.subject or identity.role not in PERMISSIONS:
        raise HTTPException(401, "Invalid organizational identity")
    return identity


def required_permission(method: str, path: str) -> str:
    if path.startswith(("/api/v1/administration", "/api/v1/audit", "/api/v1/export/configuration")):
        return "admin"
    if path.startswith("/api/v1/export/") or path.endswith(("/export", "/rejected", ".csv")):
        return "report"
    if path == "/api/v1/forecasts":  # GET currently persists a forecast run.
        return "scenario"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if path.startswith("/api/v1/budgets"):
        return "budget"
    if path.startswith("/api/v1/simulator/") or path == "/api/v1/evaluations":
        return "scenario"
    if path.startswith("/api/v1/import"):
        return "import" if method != "DELETE" or path.endswith("/cancel") else "admin"
    if path.startswith(("/api/v1/events", "/api/v1/otlp/")) or path.endswith(("/litellm/events", "/compatible/events")):
        return "import"
    return "admin"  # New mutation endpoints fail closed for non-administrators.


async def authorize(request: Request):
    identity = await resolve_identity(request)
    request.state.identity = identity
    actor_context.set(identity.subject)
    if required_permission(request.method, request.url.path) not in PERMISSIONS[identity.role]:
        raise HTTPException(403, "Permission denied")
