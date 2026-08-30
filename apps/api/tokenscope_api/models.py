from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    organization: Mapped[str] = mapped_column(String(120), default="default")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    team: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    application: Mapped[str] = mapped_column(String(120), index=True)
    workload: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    model_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deployment_type: Mapped[str] = mapped_column(String(30), default="local")
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    time_to_first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_input_cost: Mapped[float] = mapped_column(Float, default=0)
    estimated_output_cost: Mapped[float] = mapped_column(Float, default=0)
    estimated_total_cost: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_utilization: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_tags: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(50), default="sdk")
    telemetry_version: Mapped[str] = mapped_column(String(20), default="1.0")
    identity_mode: Mapped[str] = mapped_column(String(20), default="anonymous")

    __table_args__ = (Index("ix_event_time_app", "timestamp", "application"), Index("ix_event_time_model", "timestamp", "model"))

class PriceOverride(Base):
    __tablename__ = "price_overrides"

    model_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), default="custom")
    input_price_per_million: Mapped[float] = mapped_column(Float)
    output_price_per_million: Mapped[float] = mapped_column(Float)
    cached_input_price_per_million: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    effective_date: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(200), default="User override")
    last_verified: Mapped[str] = mapped_column(String(10))

class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    forecast_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    metric: Mapped[str] = mapped_column(String(30), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer)
    selected_model: Mapped[str] = mapped_column(String(50))
    training_start: Mapped[str] = mapped_column(String(10))
    training_end: Mapped[str] = mapped_column(String(10))
    training_points: Mapped[int] = mapped_column(Integer)
    error_metric: Mapped[str] = mapped_column(String(20), default="sMAPE")
    error_value: Mapped[float] = mapped_column(Float)
    backtest_results: Mapped[list] = mapped_column(JSON)
    history_values: Mapped[list] = mapped_column(JSON)
    forecast_values: Mapped[list] = mapped_column(JSON)
    drivers: Mapped[list] = mapped_column(JSON)

class Budget(Base):
    __tablename__ = "budgets"

    budget_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    scope_type: Mapped[str] = mapped_column(String(30), index=True)
    scope_value: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    period: Mapped[str] = mapped_column(String(20), default="monthly")
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Integration(Base):
    __tablename__ = "integrations"

    integration_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    collect_user_identifiers: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="configured")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class CloudProviderConfig(Base):
    __tablename__ = "cloud_provider_configs"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    credential_env_var: Mapped[str] = mapped_column(String(100))
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)

class AuditEvent(Base):
    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
