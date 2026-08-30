$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$Root\.venv")) { python -m venv "$Root\.venv" }
& "$Root\.venv\Scripts\python.exe" -m pip install -r "$Root\apps\api\requirements.txt"
Start-Process -WindowStyle Hidden -FilePath "$Root\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','tokenscope_api.main:app','--app-dir',"$Root\apps\api",'--host','127.0.0.1','--port','8000','--reload'
Set-Location $Root
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 3000
