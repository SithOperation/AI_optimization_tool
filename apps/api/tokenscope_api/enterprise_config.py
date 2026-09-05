"""Non-secret deployment intentions, independent of the active desktop connection."""
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnterpriseConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operating_mode: Literal["local", "enterprise"] = "local"
    organization_name: str = Field(default="", max_length=120)
    api_url: str | None = Field(default=None, max_length=500)
    identity_protocol: Literal["none", "oidc"] = "none"
    issuer_url: str | None = Field(default=None, max_length=500)
    client_id: str | None = Field(default=None, max_length=200)
    audience: str | None = Field(default=None, max_length=200)
    database_mode: Literal["sqlite", "postgresql"] = "sqlite"
    log_forwarding: Literal["disabled", "windows-event-log", "syslog", "siem"] = "disabled"
    release_channel: Literal["stable", "preview"] = "stable"

    @field_validator("api_url", "issuer_url")
    @classmethod
    def secure_url(cls, value):
        if value is None:
            return value
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Use HTTPS without credentials, query strings or fragments")
        return value.rstrip("/")
