$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = if ($env:AIOPT_DATA_DIR) { [System.IO.Path]::GetFullPath($env:AIOPT_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'AIOptimizationTool' }
$Database = Join-Path $DataRoot 'database\ai-optimization-tool.db'
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$BackendStatus = 'Unavailable'
$BackendEvents = $null
try {
    $Health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
    $BackendStatus = $Health.status
    $BackendEvents = $Health.events
} catch {
    $BackendStatus = $_.Exception.Message
}
$Listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$Integrity = 'Database not found'
$JournalMode = 'Unavailable'
$TelemetryRecords = $null
if ((Test-Path -LiteralPath $Database) -and (Test-Path -LiteralPath $Python)) {
    $Probe = & $Python -c "import json,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(json.dumps({'integrity':c.execute('PRAGMA integrity_check').fetchone()[0],'journal_mode':c.execute('PRAGMA journal_mode').fetchone()[0],'telemetry_records':c.execute('SELECT COUNT(*) FROM telemetry_events').fetchone()[0]})); c.close()" $Database | ConvertFrom-Json
    $Integrity = $Probe.integrity
    $JournalMode = $Probe.journal_mode
    $TelemetryRecords = $Probe.telemetry_records
}
$Node = try { node --version } catch { 'Unavailable' }
$PythonVersion = if (Test-Path -LiteralPath $Python) { & $Python --version } else { 'Unavailable' }
$LastBackendError = Get-ChildItem -LiteralPath (Join-Path $DataRoot 'logs') -Filter 'errors.log*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
[pscustomobject]@{
    Heading = 'TokenScope Diagnostics'
    ApplicationDirectory = $RepoRoot
    DataDirectory = $DataRoot
    DatabasePath = $Database
    DatabaseExists = Test-Path -LiteralPath $Database
    DatabaseSizeBytes = if (Test-Path -LiteralPath $Database) { (Get-Item -LiteralPath $Database).Length } else { 0 }
    TelemetryRecords = $TelemetryRecords
    DatabaseIntegrity = $Integrity
    JournalMode = $JournalMode
    BackendStatus = $BackendStatus
    BackendReportedEvents = $BackendEvents
    BackendPort = 8000
    BackendListenerPid = $Listener.OwningProcess
    FrontendType = 'Tauri embedded webview'
    FrontendOrigin = 'http://tauri.localhost'
    PythonVersion = $PythonVersion
    NodeVersion = $Node
    LastBackendErrorLog = $LastBackendError.FullName
} | Format-List
