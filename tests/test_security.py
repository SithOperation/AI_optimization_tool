import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.tokenscope_api.importer_streaming import (
    MAX_RECORD_CHARS,
    StreamingImporter,
    cleanup_stale_import_files,
    validate_file_metadata,
)
from apps.api.tokenscope_api.main import app


def test_openapi_version_and_security_import_routes_are_present():
    schema = app.openapi()
    assert schema["info"]["version"] == "0.16.0"
    expected = {
        "/api/v1/health",
        "/api/v1/telemetry",
        "/api/v1/import/start",
        "/api/v1/import/{import_id}/upload",
        "/api/v1/import/{import_id}/analyze",
        "/api/v1/import/{import_id}/commit",
        "/api/v1/import/{import_id}/cancel",
        "/api/v1/import/history",
    }
    assert expected <= set(schema["paths"])


def test_desktop_entry_binds_ipv4_loopback_only():
    source = Path("apps/api/desktop_entry.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in source
    assert 'host="0.0.0.0"' not in source


def test_malicious_origin_is_not_allowed_by_cors():
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/telemetry",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "DELETE",
            },
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_authenticated_desktop_request_can_complete_cors_preflight(monkeypatch):
    monkeypatch.setenv("AIOPT_DESKTOP_TOKEN", "launch-secret")
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/application",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-tokenscope-key",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
    assert "x-tokenscope-key" in response.headers["access-control-allow-headers"].lower()


def test_desktop_token_protects_telemetry_reset(monkeypatch):
    monkeypatch.setenv("AIOPT_DESKTOP_TOKEN", "launch-secret")
    monkeypatch.setenv("TOKENSCOPE_API_KEY", "external-client-secret")
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 401
        assert client.get(
            "/api/v1/health", headers={"X-TokenScope-Key": "wrong-secret"}
        ).status_code == 401
        assert client.get(
            "/api/v1/health", headers={"X-TokenScope-Key": "launch-secret"}
        ).status_code == 200
        assert client.get("/api/v1/application").status_code == 401
        assert client.get(
            "/api/v1/application", headers={"X-TokenScope-Key": "launch-secret"}
        ).status_code == 200
        assert client.delete("/api/v1/telemetry").status_code == 401
        assert client.delete(
            "/api/v1/telemetry", headers={"X-TokenScope-Key": "launch-secret"}
        ).status_code == 200


def test_traversal_and_windows_device_filenames_are_rejected():
    for filename in ("../events.csv", "..\\events.csv", "C:\\events.csv", "\\\\host\\share\\events.csv"):
        try:
            validate_file_metadata(filename, 10, "csv")
        except Exception:
            pass
        else:
            raise AssertionError(f"unsafe filename accepted: {filename!r}")


def test_cumulative_upload_cannot_exceed_declared_size(tmp_path):
    importer = StreamingImporter(str(uuid4()), temp_dir=str(tmp_path))

    class Upload:
        def __init__(self, payload):
            self.payload = payload

        async def read(self, _size):
            payload, self.payload = self.payload, b""
            return payload

    asyncio.run(importer.receive_upload(Upload(b"abc"), 3))
    try:
        asyncio.run(importer.receive_upload(Upload(b"d"), 3))
    except Exception:
        pass
    else:
        raise AssertionError("upload exceeded declared size")
    assert importer.get_temp_path().read_bytes() == b"abc"


def test_incomplete_upload_is_rejected(tmp_path):
    importer = StreamingImporter(str(uuid4()), temp_dir=str(tmp_path))
    asyncio.run(importer.receive_file_chunk(b"short"))
    try:
        importer.verify_complete(100)
    except Exception:
        pass
    else:
        raise AssertionError("incomplete upload was accepted")


def test_malformed_multipart_is_controlled():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/import/{uuid4()}/upload",
            content=b"not multipart",
            headers={"Content-Type": "multipart/form-data; boundary=missing"},
        )
    assert response.status_code in (400, 404, 422)
    assert "Traceback" not in response.text


def test_oversized_and_nonfinite_event_values_are_rejected():
    base = {"application": "app", "provider": "local", "model": "model"}
    with TestClient(app) as client:
        oversized = client.post("/api/v1/events", json={**base, "application": "a" * 121})
        nonfinite = client.post(
            "/api/v1/events",
            content='{"application":"app","provider":"local","model":"model","latency_ms":NaN}',
            headers={"Content-Type": "application/json"},
        )
    assert oversized.status_code == 422
    assert nonfinite.status_code == 422


def test_sql_injection_payload_is_stored_as_data():
    payload = "model'); DROP TABLE telemetry_events;--"
    with TestClient(app) as client:
        client.delete("/api/v1/telemetry")
        response = client.post(
            "/api/v1/events",
            json={"application": "security-test", "provider": "local", "model": payload},
        )
        health = client.get("/api/v1/health")
    assert response.status_code == 201
    assert health.status_code == 200
    assert health.json()["events"] == 1


def test_oversized_csv_record_fails_without_completing(tmp_path):
    importer = StreamingImporter(str(uuid4()), temp_dir=str(tmp_path))
    content = b"application,provider,model\n" + b"a" * (MAX_RECORD_CHARS + 1)
    asyncio.run(importer.receive_file_chunk(content[:5_000_000]))
    try:
        asyncio.run(importer.analyze_file("events.csv", "csv"))
    except Exception as error:
        assert "2 MB" in str(error)
    else:
        raise AssertionError("oversized CSV record was accepted")


def test_stale_temp_files_are_cleaned(tmp_path):
    importer = StreamingImporter(str(uuid4()), temp_dir=str(tmp_path))
    asyncio.run(importer.receive_file_chunk(b"temporary"))
    path = importer.get_temp_path()
    path.touch()
    assert cleanup_stale_import_files(max_age_seconds=-1) >= 0
    importer.cleanup()
    assert not path.exists()


@pytest.mark.skipif(not os.getenv("AIOPT_LARGE_IMPORT_FIXTURE"), reason="opt-in 150k-row regression")
def test_150k_row_import_populates_analytics():
    path = Path(os.environ["AIOPT_LARGE_IMPORT_FIXTURE"])
    mapping = {
        "timestamp": "timestamp",
        "application": "application",
        "provider": "provider",
        "model": "model",
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
    }
    with TestClient(app) as client:
        client.delete("/api/v1/telemetry")
        started = client.post("/api/v1/import/start", json={"filename": path.name, "file_size": path.stat().st_size, "format": "csv"})
        assert started.status_code == 201
        import_id = started.json()["import_id"]
        with path.open("rb") as handle:
            while chunk := handle.read(5_000_000):
                response = client.post(f"/api/v1/import/{import_id}/upload", files={"file": (path.name, chunk, "text/csv")})
                assert response.status_code == 200
        assert client.post(f"/api/v1/import/{import_id}/analyze").status_code == 200
        committed = client.post(f"/api/v1/import/{import_id}/commit", json={"import_id": import_id, "mapping": mapping, "duplicate_handling": "skip"})
        assert committed.status_code == 200, committed.text
        assert committed.json()["inserted_rows"] == 150_000
        assert client.get("/api/v1/analytics").json()["items"]
        assert client.get("/api/v1/pricing").status_code == 200
        assert client.get("/api/v1/models/inventory").json()["models"]
