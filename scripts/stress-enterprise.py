"""Opt-in end-to-end importer benchmark in a fresh, isolated local data directory.

python scripts/stress-enterprise.py --rows 500000 --output artifacts/stress-500000.json
Run each size in a new process so peak resident memory is attributable to that run.
"""
import argparse
import csv
import ctypes
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument("--rows", type=int, choices=[150000, 500000, 1000000], required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
data = Path(tempfile.mkdtemp(prefix="aiopt-stress-"))
os.environ["AIOPT_DATA_DIR"] = str(data)
for key in ("DATABASE_URL", "TOKENSCOPE_DATABASE_URL", "AIOPT_OPERATING_MODE", "AIOPT_DESKTOP_TOKEN", "TOKENSCOPE_API_KEY"):
    os.environ.pop(key, None)
started = time.perf_counter()
from fastapi.testclient import TestClient
from apps.api.tokenscope_api.main import app
from apps.api.tokenscope_api.database import DEFAULT_DB
import_seconds = time.perf_counter() - started


def peak_memory():
    if os.name != "nt":
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024
    class Counters(ctypes.Structure):
        _fields_ = [("cb",ctypes.c_ulong),("faults",ctypes.c_ulong)] + [(name,ctypes.c_size_t) for name in ("peak_working","working","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.peak_working


result = {"rows": args.rows, "data_directory": str(data), "python_import_seconds": import_seconds,
          "measurement": "TestClient full upload/analyze/commit; process peak working set; one query per route (not browser paint)"}
fixture = data / "telemetry.csv"
fields = ["timestamp", "application", "provider", "model", "input_tokens", "output_tokens", "workload", "padding"]
now = datetime.now(timezone.utc)
with fixture.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle); writer.writerow(fields)
    for i in range(args.rows):
        writer.writerow([(now-timedelta(minutes=i % 40000)).isoformat(), f"application-{i%20}", "local", f"model-{i%5}", 1000, 100, "benchmark", "x"*180])
result["fixture_bytes"] = fixture.stat().st_size
started = time.perf_counter()
with TestClient(app) as client:
    result["lifespan_startup_seconds"] = time.perf_counter()-started
    def query_times():
        measurements = {}
        for name, route in {"dashboard":"/overview", "usage":"/analytics?group_by=application", "costs":"/analytics?group_by=provider", "models":"/models/inventory", "telemetry_page":"/telemetry/events?limit=100"}.items():
            start = time.perf_counter(); response = client.get('/api/v1'+route)
            assert response.status_code == 200, response.text
            measurements[name] = round((time.perf_counter()-start)*1000, 3)
        return measurements
    result["empty_query_ms"] = query_times()
    before_bytes = DEFAULT_DB.stat().st_size
    started = time.perf_counter()
    response = client.post('/api/v1/import/start', json={"filename":fixture.name,"file_size":fixture.stat().st_size,"format":"csv"})
    assert response.status_code == 201, response.text
    import_id = response.json()["import_id"]
    with fixture.open('rb') as handle:
        while chunk := handle.read(5_000_000):
            response = client.post(f'/api/v1/import/{import_id}/upload',files={"file":(fixture.name,chunk,'text/csv')})
            assert response.status_code == 200, response.text
    result['upload_seconds'] = time.perf_counter()-started
    started = time.perf_counter()
    response = client.post(f'/api/v1/import/{import_id}/analyze')
    assert response.status_code == 200, response.text
    result['analyze_seconds'] = time.perf_counter()-started
    started = time.perf_counter()
    response = client.post(f'/api/v1/import/{import_id}/commit',json={"import_id":import_id,"mapping":{key:key for key in fields if key != "padding"},"duplicate_handling":"skip"})
    assert response.status_code == 200, response.text
    assert response.json()['inserted_rows'] == args.rows
    result['commit_seconds'] = time.perf_counter()-started
    result['database_growth_bytes'] = DEFAULT_DB.stat().st_size-before_bytes
    assert client.get('/api/v1/health').json()['events'] == args.rows
    result['populated_query_ms'] = query_times()
    result['peak_process_memory_bytes'] = peak_memory()
    started = time.perf_counter()
    response = client.delete('/api/v1/telemetry')
    assert response.status_code == 200 and response.json()['deleted']['telemetry_events'] == args.rows
    result['reset_seconds'] = time.perf_counter()-started
    assert client.get('/api/v1/health').json()['events'] == 0
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
