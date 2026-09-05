from datetime import datetime, timedelta, timezone
import json
import zipfile
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from apps.api.tokenscope_api import authorization
from apps.api.tokenscope_api.backups import backup_path, restore_backup
from apps.api.tokenscope_api.database import Base, engine, SessionLocal
from apps.api.tokenscope_api.main import app, audit
from apps.api.tokenscope_api.models import TelemetryEvent, AuditEvent
from apps.api.tokenscope_api.sql_functions import day_bucket, hour_bucket


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("AIOPT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AIOPT_OPERATING_MODE", raising=False)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    if hasattr(app.state, "identity_provider"):
        del app.state.identity_provider


def event(application="test"):
    return {"application": application, "model": "local-model", "provider": "local", "input_tokens": 10}


def attach_identity(monkeypatch, role):
    class Provider:
        async def authenticate(self, request):
            return authorization.Identity("employee-123", role, "example-org", "https://id.example")
    monkeypatch.setenv("AIOPT_OPERATING_MODE", "enterprise")
    app.state.identity_provider = Provider()


@pytest.mark.parametrize("role", list(authorization.Role))
def test_backend_role_matrix(monkeypatch, role):
    attach_identity(monkeypatch, role)
    with TestClient(app) as client:
        assert client.get("/api/v1/overview").status_code == 200
        assert client.get("/api/v1/reports/executive").status_code == 200
        assert client.post("/api/v1/events", json=event()).status_code == (403 if role == authorization.Role.VIEWER else 201)
        assert client.post("/api/v1/budgets", json={"name":"team", "scope_type":"organization", "amount":100}).status_code == (403 if role == authorization.Role.VIEWER else 201)
        assert client.delete("/api/v1/telemetry").status_code == (200 if role == authorization.Role.ADMINISTRATOR else 403)
        assert client.put("/api/v1/administration/configuration", json={}).status_code == (200 if role == authorization.Role.ADMINISTRATOR else 403)
        assert client.post("/api/v1/administration/backups").status_code == (201 if role == authorization.Role.ADMINISTRATOR else 403)


def test_identity_fails_closed_and_ignores_client_roles(monkeypatch):
    monkeypatch.setenv("AIOPT_OPERATING_MODE", "enterprise")
    with TestClient(app) as client:
        assert client.get("/api/v1/overview", headers={"X-Role":"Administrator"}).status_code == 503
        attach_identity(monkeypatch, authorization.Role.VIEWER)
        assert client.delete("/api/v1/telemetry", headers={"X-Role":"Administrator"}).status_code == 403


def test_local_authentication_and_configuration_are_independent(monkeypatch):
    monkeypatch.setenv("AIOPT_DESKTOP_TOKEN", "launch-secret")
    with TestClient(app) as client:
        assert client.put("/api/v1/administration/configuration", json={}).status_code == 401
        client.headers["X-TokenScope-Key"] = "launch-secret"
        result = client.put("/api/v1/administration/configuration", json={"operating_mode":"enterprise", "identity_protocol":"oidc", "issuer_url":"https://identity.example", "organization_name":"Example"})
        assert result.status_code == 200
        assert result.json()["active_mode"] == "local"
        assert result.json()["identity_connected"] is False
        assert client.delete("/api/v1/telemetry").status_code == 200


@pytest.mark.parametrize("payload", [{"api_url":"http://remote.example"}, {"issuer_url":"https://secret@id.example"}, {"api_url":"https://api.example?token=secret"}, {"client_secret":"secret"}, {"operating_mode":"unknown"}])
def test_configuration_rejects_unsafe_or_unknown_values(payload):
    with TestClient(app) as client:
        response = client.put("/api/v1/administration/configuration", json=payload)
        assert response.status_code == 422
        assert "secret@" not in response.text


def test_retention_preview_opt_in_and_audit_preservation():
    with TestClient(app) as client:
        client.post("/api/v1/events", json={**event(), "timestamp": (datetime.now(timezone.utc)-timedelta(days=60)).isoformat()})
        client.put("/api/v1/settings/retention", json={"days":30})
        assert client.get("/api/v1/settings/retention/preview").json()["affected_records"] == 1
        assert client.post("/api/v1/settings/retention/apply").status_code == 400
        client.put("/api/v1/settings/retention", json={"days":30,"enforcement_enabled":True})
        assert client.post("/api/v1/settings/retention/apply").json()["deleted"] == 1
        client.delete("/api/v1/telemetry")
        assert any(row["action"] == "retention.applied" for row in client.get("/api/v1/audit").json())


def test_backup_roundtrip_preserves_audit_and_requires_confirmation():
    with TestClient(app) as client:
        client.post("/api/v1/events", json=event("before"))
        backup = client.post("/api/v1/administration/backups").json()["backup_id"]
        client.delete("/api/v1/telemetry")
        prefix = f"/api/v1/administration/backups/{backup}"
        assert client.post(prefix + "/validate").json()["valid"]
        assert client.post(prefix + "/restore", json={}).status_code == 400
        response = client.post(prefix + "/restore", json={"confirmed":True})
        assert response.status_code == 200, response.text
        assert client.get("/api/v1/health").json()["events"] == 1
        actions = [row["action"] for row in client.get("/api/v1/audit").json()]
        assert "telemetry.cleared" in actions and "backup.restored" in actions


@pytest.mark.parametrize("corruption", ["checksum", "version", "entry"])
def test_backup_validation_preserves_existing_data(corruption):
    with TestClient(app) as client:
        client.post("/api/v1/events", json=event())
        backup = client.post("/api/v1/administration/backups").json()["backup_id"]
        path = backup_path(backup)
        with zipfile.ZipFile(path) as archive:
            data = archive.read("database.sqlite")
            manifest = json.loads(archive.read("manifest.json"))
        if corruption == "checksum": manifest["database_sha256"] = "bad"
        if corruption == "version": manifest["format_version"] = 999
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("database.sqlite", data)
            archive.writestr("manifest.json", json.dumps(manifest))
            if corruption == "entry": archive.writestr("../escape", "bad")
        assert client.post(f"/api/v1/administration/backups/{backup}/restore", json={"confirmed":True}).status_code == 400
        assert client.get("/api/v1/health").json()["events"] == 1


def test_restore_rolls_back_on_write_failure():
    with TestClient(app) as client:
        client.post("/api/v1/events", json=event("before"))
        backup = client.post("/api/v1/administration/backups").json()["backup_id"]
        client.post("/api/v1/events", json=event("after"))
        def fail(*args, **kwargs):
            raise RuntimeError("simulated disk failure")
        with SessionLocal() as db:
            with pytest.raises(RuntimeError):
                restore_backup(db, backup, fail)
        assert client.get("/api/v1/health").json()["events"] == 2


def test_diagnostics_pagination_and_secrets(monkeypatch):
    monkeypatch.setenv("PROVIDER_SECRET", "never-show-this")
    with TestClient(app) as client:
        for i in range(3): client.post("/api/v1/events", json=event(str(i)))
        first = client.get("/api/v1/telemetry/events?limit=2").json()
        second = client.get("/api/v1/telemetry/events?limit=2&offset=2").json()
        assert len(first["items"]) == 2 and first["has_more"]
        assert len(second["items"]) == 1 and not second["has_more"]
        assert client.get("/api/v1/telemetry/events?limit=1001").status_code == 422
        result = client.get("/api/v1/administration/diagnostics")
        assert result.json()["database"]["telemetry_records"] == 3
        client.put("/api/v1/cloud-providers/openai", json={"provider":"openai", "credential_env_var":"PROVIDER_SECRET"})
        assert "never-show-this" not in result.text + client.get("/api/v1/cloud-providers").text + client.get("/api/v1/audit").text


def test_analytics_pagination_preserves_global_totals():
    with TestClient(app) as client:
        for i in range(5): client.post('/api/v1/events',json=event(str(i)))
        first=client.get('/api/v1/analytics?limit=2').json()
        second=client.get('/api/v1/analytics?limit=2&offset=2').json()
        assert len(first['items'])==2 and first['has_more']
        assert first['totals']['requests']==5 and second['totals']['requests']==5
        assert {item['name'] for item in first['items']}.isdisjoint(item['name'] for item in second['items'])
        assert client.get('/api/v1/models/inventory?limit=1').json()['has_more']


def test_postgresql_schema_and_bucket_compilation():
    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=postgresql.dialect()))
    for bucket in (day_bucket, hour_bucket):
        query = select(bucket(TelemetryEvent.timestamp))
        assert "to_char" in str(query.compile(dialect=postgresql.dialect()))
        assert "to_char" not in str(query.compile(dialect=sqlite.dialect()))


@pytest.mark.skipif(os.name != "nt", reason="Windows native credential store")
def test_windows_credential_save_replace_mask_and_delete():
    from apps.api.tokenscope_api.windows_credentials import WindowsCredentials
    reference = "AIOPT_TEST_" + uuid4().hex.upper()
    vault = WindowsCredentials()
    try:
        with TestClient(app) as client:
            for value in ["unique-test-secret", "replacement-test-secret"]:
                result = client.put("/api/v1/administration/credentials", json={"reference":reference,"secret":value})
                assert result.status_code == 200
                assert result.json()["masked_credential"] == "********"
                assert value not in result.text + client.get("/api/v1/audit").text
                assert vault.get(reference) == value
            assert client.delete('/api/v1/administration/credentials/'+reference).status_code == 200
            assert vault.get(reference) is None
    finally:
        vault.delete(reference)


@pytest.mark.parametrize("value", ["=cmd()", "+cmd()", "-cmd()", "@cmd()", "  =cmd()", "\tcmd()"])
def test_export_sanitizes_without_changing_storage(value):
    with TestClient(app) as client:
        client.post("/api/v1/events", json=event(value))
        assert "'" + value in client.get("/api/v1/export/events.csv").text
        assert client.get("/api/v1/telemetry/events").json()["items"][0]["application"] == value
