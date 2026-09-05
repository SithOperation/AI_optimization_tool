"""Exercise a running isolated packaged backend. Never run against user data."""
import csv
import io
import os
from pathlib import Path
import sys
import time
import httpx

fixture = Path(sys.argv[1])
headers = {"X-TokenScope-Key":os.environ["AIOPT_DESKTOP_TOKEN"]}
mapping = {name:name for name in ("timestamp","application","provider","model","input_tokens","output_tokens")}
with fixture.open(encoding='utf-8',newline='') as handle:
    expected_rows = sum(1 for _ in csv.DictReader(handle))
with httpx.Client(base_url='http://127.0.0.1:8000/api/v1',headers=headers,timeout=600) as client:
    assert client.get('/health').json()['events']==0, 'Smoke requires a disposable empty database'
    started=time.perf_counter()
    response=client.post('/import/start',json={"filename":fixture.name,"file_size":fixture.stat().st_size,"format":"csv"})
    assert response.status_code==201,response.text
    import_id=response.json()['import_id']
    with fixture.open('rb') as handle:
        while chunk:=handle.read(5_000_000):
            response=client.post(f'/import/{import_id}/upload',files={'file':(fixture.name,chunk,'text/csv')})
            assert response.status_code==200,response.text
    assert client.post(f'/import/{import_id}/analyze').status_code==200
    response=client.post(f'/import/{import_id}/commit',json={'import_id':import_id,'mapping':mapping,'duplicate_handling':'skip'})
    assert response.status_code==200,response.text
    assert response.json()['inserted_rows']==expected_rows
    print(f'Packaged import: {expected_rows} rows in {time.perf_counter()-started:.3f}s')
    for route in ['/analytics?group_by=application','/analytics?group_by=provider','/models/inventory','/administration/configuration','/administration/diagnostics']:
        assert client.get(route).status_code==200,route
    backup=client.post('/administration/backups').json()['backup_id']
    assert client.delete('/telemetry').json()['success']
    assert client.get('/health').json()['events']==0
    assert client.post(f'/administration/backups/{backup}/validate').json()['valid']
    response=client.post(f'/administration/backups/{backup}/restore',json={'confirmed':True})
    assert response.status_code==200,response.text
    assert client.get('/health').json()['events']==expected_rows
    assert any(item['action']=='telemetry.cleared' for item in client.get('/audit').json())
    assert client.delete('/telemetry').json()['success']
    print('Packaged enterprise settings, diagnostics, Usage/Costs/Models, backup/restore and audit preservation passed')
