from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(default_factory=lambda: str(uuid4()), max_length=100)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    organization: str = Field(default="default", max_length=120)
    department: str | None = Field(default=None, max_length=100)
    team: str | None = Field(default=None, max_length=100)
    application: str = Field(min_length=1, max_length=120)
    workload: str | None = Field(default=None, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    model_family: str | None = None
    deployment_type: Literal["local", "cloud", "hybrid"] = "local"
    request_id: str | None = None
    session_id: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    time_to_first_token_ms: float | None = Field(default=None, ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0)
    success: bool = True
    status_code: int | None = None
    error_type: str | None = None
    retry_count: int = Field(default=0, ge=0)
    cache_hit: bool = False
    estimated_input_cost: float | None = Field(default=None, ge=0)
    estimated_output_cost: float | None = Field(default=None, ge=0)
    estimated_total_cost: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    context_window: int | None = Field(default=None, gt=0)
    context_utilization: float | None = Field(default=None, ge=0, le=1)
    request_tags: dict[str, str] = Field(default_factory=dict)
    source: str = Field(default="sdk", max_length=50)
    telemetry_version: str = "1.0"
    identity_mode: Literal["anonymous", "hashed", "explicit"] = "anonymous"

    @model_validator(mode="after")
    def totals(self):
        computed = self.input_tokens + self.output_tokens + self.reasoning_tokens
        if self.total_tokens is None:
            self.total_tokens = computed
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        return self

class BatchCreate(BaseModel):
    events: list[EventCreate] = Field(min_length=1, max_length=1000)

class PriceOverrideCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="custom", max_length=80)
    input_price_per_million: float = Field(ge=0)
    output_price_per_million: float = Field(ge=0)
    cached_input_price_per_million: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    effective_date: str = Field(pattern="^\\d{4}-\\d{2}-\\d{2}$")
    source: str = Field(default="User override", max_length=200)
    last_verified: str = Field(pattern="^\\d{4}-\\d{2}-\\d{2}$")

class ImportRequest(BaseModel):
    format: Literal["csv", "json"]
    content: str = Field(min_length=2, max_length=4_500_000)
    mapping: dict[str, str] = Field(default_factory=dict)

class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope_type: Literal["organization", "department", "team", "application", "provider", "model"] = "organization"
    scope_value: str | None = Field(default=None, max_length=120)
    period: Literal["monthly", "quarterly", "annual"] = "monthly"
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    active: bool = True

    @model_validator(mode="after")
    def scope_required(self):
        if self.scope_type != "organization" and not self.scope_value:
            raise ValueError("scope_value is required outside organization scope")
        return self

class ModelMixItem(BaseModel):
    model: str
    share_percent: float = Field(ge=0, le=100)
    input_price_per_million: float = Field(ge=0)
    output_price_per_million: float = Field(ge=0)

class ScenarioRequest(BaseModel):
    name: str = "Expected"
    employees: int = Field(ge=1, le=1_000_000)
    active_ai_users: int | None = Field(default=None, ge=0)
    adoption_percent: float = Field(default=50, ge=0, le=100)
    requests_per_user_day: float = Field(default=10, ge=0, le=10000)
    average_input_tokens: int = Field(default=4000, ge=0)
    average_output_tokens: int = Field(default=500, ge=0)
    working_days_month: int = Field(default=22, ge=1, le=31)
    monthly_growth_percent: float = Field(default=0, ge=-100, le=1000)
    cache_hit_percent: float = Field(default=0, ge=0, le=100)
    retry_percent: float = Field(default=0, ge=0, le=100)
    application_growth_percent: float = Field(default=0, ge=-100, le=1000)
    model_mix: list[ModelMixItem] = Field(min_length=1, max_length=20)

class MigrationRequest(BaseModel):
    application: str = Field(min_length=1, max_length=120)
    alternative_model: str = Field(min_length=1, max_length=120)
    alternative_input_price_per_million: float | None = Field(default=None, ge=0)
    alternative_output_price_per_million: float | None = Field(default=None, ge=0)
    days: int = Field(default=30, ge=1, le=365)

class LocalCloudRequest(BaseModel):
    monthly_input_tokens: float = Field(ge=0)
    monthly_output_tokens: float = Field(ge=0)
    cloud_input_price_per_million: float = Field(ge=0)
    cloud_output_price_per_million: float = Field(ge=0)
    gpu_name: str = "Local GPU"
    gpu_quantity: int = Field(default=1, ge=1, le=10000)
    gpu_purchase_price: float = Field(ge=0)
    power_draw_watts: float = Field(ge=0)
    electricity_rate_kwh: float = Field(default=.15, ge=0)
    utilization_percent: float = Field(default=50, gt=0, le=100)
    estimated_tokens_second: float = Field(gt=0)
    hardware_life_months: int = Field(default=36, ge=1, le=240)
    monthly_maintenance_cost: float = Field(default=0, ge=0)
    monthly_hosting_cost: float = Field(default=0, ge=0)

class IntegrationRequest(BaseModel):
    kind: Literal["ollama", "vllm", "generic-openai-compatible", "litellm"]
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=500)
    collect_user_identifiers: bool = False

class AdapterEvent(BaseModel):
    payload: dict
    application: str = Field(default="OpenAI-compatible application", max_length=120)
    department: str | None = None
    team: str | None = None
    workload: str | None = None
    provider: str | None = None
    source: Literal["ollama", "vllm", "generic-openai-compatible"] = "generic-openai-compatible"
