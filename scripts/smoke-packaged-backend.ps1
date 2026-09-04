param(
    [string]$Executable = "src-tauri\binaries\aiopt-backend.exe",
    [int]$StartupTimeoutSeconds = 90
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExecutablePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Executable))
if (-not (Test-Path -LiteralPath $ExecutablePath)) { throw "Packaged backend not found: $ExecutablePath" }
$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-packaged-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
$PreviousDataDir = $env:AIOPT_DATA_DIR
$PreviousRuntime = $env:AIOPT_RUNTIME
$Process = $null
try {
    $env:AIOPT_DATA_DIR = $SmokeRoot
    $env:AIOPT_RUNTIME = 'desktop'
    $Process = Start-Process -FilePath $ExecutablePath -PassThru -WindowStyle Hidden
    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        if ($Process.HasExited) { throw "Packaged backend exited early with code $($Process.ExitCode)." }
        try { $Health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2 } catch { $Health = $null }
        if ($Health.status -eq 'healthy') { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $Deadline)
    if ($Health.status -ne 'healthy') { throw 'Packaged backend did not become healthy.' }
    $Listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop
    if ($Listeners | Where-Object LocalAddress -NotIn @('127.0.0.1','::1')) {
        throw 'Packaged backend opened a non-loopback listener.'
    }
    $Application = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/application'
    if ($Application.version -ne '0.14.0') { throw "Unexpected packaged backend version: $($Application.version)" }
    $ImportHistory = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/import/history'
    if ($null -eq $ImportHistory) { throw 'Packaged import-history route failed.' }
    Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/demo?days=30' -Method Post | Out-Null
    $Forecast = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/forecasts?metric=total_tokens&horizon=7'
    if (-not $Forecast.forecast -or $Forecast.forecast.Count -ne 7) { throw 'Packaged forecast smoke test failed.' }
    $ScenarioBody = @{ name='RC smoke'; employees=100; adoption_percent=50; requests_per_user_day=5; average_input_tokens=500; average_output_tokens=150; working_days_month=22; monthly_growth_percent=5; cache_hit_percent=10; retry_percent=2; application_growth_percent=5; model_mix=@(@{model='Economy';share_percent=100;input_price_per_million=.5;output_price_per_million=1.5}) } | ConvertTo-Json -Depth 5
    $Scenario = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/simulator/scenario' -Method Post -ContentType 'application/json' -Body $ScenarioBody
    if ($Scenario.monthly_spend -le 0) { throw 'Packaged Scenario Lab smoke test failed.' }
    $Reset = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/telemetry' -Method Delete
    if (-not $Reset.success) { throw 'Packaged telemetry reset route failed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot 'database'))) { throw 'Packaged database directory was not initialized.' }
    Write-Host "Packaged backend $($Application.version) healthy on loopback; import history and reset routes passed; forecast points=$($Forecast.forecast.Count); scenario spend=$($Scenario.monthly_spend)"
}
finally {
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id
        $Process.WaitForExit(10000) | Out-Null
    }
    # A PyInstaller one-file executable uses a launcher/worker pair. Stop only
    # workers whose executable path is this exact packaged backend.
    $BackendWorkers = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'aiopt-backend.exe' -and $_.ExecutablePath -eq $ExecutablePath
    })
    $BackendWorkers | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    if ($BackendWorkers.Count -gt 0) { Start-Sleep -Milliseconds 500 }
    $env:AIOPT_DATA_DIR = $PreviousDataDir
    $env:AIOPT_RUNTIME = $PreviousRuntime
    if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
}
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'aiopt-backend.exe' -and $_.ExecutablePath -eq $ExecutablePath }) {
    throw 'Packaged backend process remained after shutdown.'
}
