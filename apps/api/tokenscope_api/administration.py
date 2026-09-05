import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select

from .app_config import VERSION, ensure_application_directories
from .backups import create_backup, restore_backup, validated_backup
from .enterprise_config import EnterpriseConfiguration
from .models import AppSetting, ImportJob, TelemetryEvent
from .secrets_service import credential_status

STARTED_AT = time.monotonic()


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    secret: SecretStr = Field(min_length=1, max_length=2560)


def register_administration(app, db_session, audit):
    @app.put("/api/v1/administration/credentials")
    def save_credential(payload: CredentialRequest, db=Depends(db_session)):
        from .windows_credentials import WindowsCredentials
        try:
            WindowsCredentials().set(payload.reference, payload.secret.get_secret_value())
        except (OSError, ValueError) as error:
            raise HTTPException(400, "Could not save credential in Windows Credential Manager") from error
        audit(db, "credential.updated", "credential_reference", payload.reference)
        db.commit()
        return credential_status(payload.reference)

    @app.delete("/api/v1/administration/credentials/{reference}")
    def delete_credential(reference: str, db=Depends(db_session)):
        from .windows_credentials import WindowsCredentials
        try:
            WindowsCredentials().delete(reference)
        except (OSError, ValueError) as error:
            raise HTTPException(400, "Could not delete stored credential") from error
        audit(db, "credential.deleted", "credential_reference", reference)
        db.commit()
        return {**credential_status(reference), "notice":"Environment credentials, if configured, remain available until removed by the administrator."}

    @app.get("/api/v1/administration/configuration")
    def configuration(db=Depends(db_session)):
        row = db.get(AppSetting, "enterprise")
        return {"configuration": EnterpriseConfiguration(**(row.value if row else {})).model_dump(),
                "active_mode": os.getenv("AIOPT_OPERATING_MODE", "local"),
                "database": db.bind.dialect.name,
                "identity_connected": getattr(app.state, "identity_provider", None) is not None,
                "configuration_only": True,
                "notice": "Deployment intentions only. Remote API, OIDC, log forwarding and updates are not activated by saving."}

    @app.put("/api/v1/administration/configuration")
    def save_configuration(payload: EnterpriseConfiguration, db=Depends(db_session)):
        row = db.get(AppSetting, "enterprise")
        if row:
            row.value = payload.model_dump()
        else:
            db.add(AppSetting(key="enterprise", value=payload.model_dump()))
        audit(db, "enterprise.configured", "setting", "enterprise", operating_mode=payload.operating_mode)
        db.commit()
        return configuration(db)

    @app.get("/api/v1/administration/diagnostics")
    def diagnostics(db=Depends(db_session)):
        count = db.scalar(select(func.count()).select_from(TelemetryEvent)) or 0
        last = db.scalar(select(func.max(ImportJob.completed_at)).where(ImportJob.status == "COMPLETED"))
        active = db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.status == "IMPORTING")) or 0
        return {"app_version": VERSION, "backend_version": VERSION,
                "database": {"connected": True, "dialect": db.bind.dialect.name, "telemetry_records": count},
                "imports": {"available": True, "active": active, "last_successful_import": last},
                "uptime_seconds": round(time.monotonic() - STARTED_AT, 2),
                "backend_process_state": "running", "active_mode": os.getenv("AIOPT_OPERATING_MODE", "local"),
                "credential_store": "Windows Credential Manager" if os.name == "nt" else "Environment references",
                "secrets_included": False}

    @app.get("/api/v1/settings/retention/preview")
    def retention_preview(db=Depends(db_session)):
        row = db.get(AppSetting, "retention")
        days = row.value.get("days") if row else None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        count = db.scalar(select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.timestamp < cutoff)) if cutoff else 0
        return {"days": days, "cutoff": cutoff, "affected_records": count, "automatic_deletion": False}

    @app.get("/api/v1/administration/backups")
    def backups():
        items = sorted(ensure_application_directories()["backups"].glob("*.aiopt-backup"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {"backups": [{"backup_id": p.stem, "bytes": p.stat().st_size,
                             "created_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)} for p in items[:100]]}

    @app.post("/api/v1/administration/backups", status_code=201)
    def backup(db=Depends(db_session)):
        try:
            result = create_backup(db)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        audit(db, "backup.created", "backup", result["backup_id"])
        db.commit()
        return result

    @app.post("/api/v1/administration/backups/{backup_id}/validate")
    def validate(backup_id: str):
        try:
            with validated_backup(backup_id) as (_, manifest):
                return {"valid": True, "manifest": manifest}
        except Exception as error:
            raise HTTPException(400, "Backup validation failed") from error

    @app.post("/api/v1/administration/backups/{backup_id}/restore")
    def restore(backup_id: str, payload: RestoreRequest, db=Depends(db_session)):
        if not payload.confirmed:
            raise HTTPException(400, "Explicit restore confirmation is required")
        try:
            return restore_backup(db, backup_id, audit)
        except Exception as error:
            db.rollback()
            audit(db, "backup.restore_failed", "backup", outcome="failure")
            db.commit()
            raise HTTPException(400, "Restore failed; current data was preserved") from error

    @app.get("/api/v1/telemetry/events")
    def telemetry_events(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0, le=10_000_000),
                         application: str | None = Query(None, max_length=120), db=Depends(db_session)):
        fields = [TelemetryEvent.event_id, TelemetryEvent.timestamp, TelemetryEvent.application,
                  TelemetryEvent.provider, TelemetryEvent.model, TelemetryEvent.total_tokens, TelemetryEvent.estimated_total_cost]
        clauses = [TelemetryEvent.application == application] if application else []
        rows = db.execute(select(*fields).where(*clauses).order_by(TelemetryEvent.timestamp.desc(), TelemetryEvent.event_id).offset(offset).limit(limit + 1)).mappings().all()
        return {"items": [dict(row) for row in rows[:limit]], "offset": offset, "limit": limit, "has_more": len(rows) > limit}
