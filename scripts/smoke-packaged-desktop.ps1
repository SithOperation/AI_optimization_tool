param(
    [string]$Executable = "src-tauri\target\release\ai-optimization-tool.exe",
    [int]$StartupTimeoutSeconds = 90,
    [string]$SeedDatabase = '',
    [int]$ExpectedEvents = 0
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExecutablePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Executable))
$BackendPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'src-tauri\target\release\binaries\aiopt-backend\aiopt-backend.exe'))
if (-not (Test-Path -LiteralPath $ExecutablePath)) { throw "Desktop executable not found: $ExecutablePath" }
$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-desktop-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
if ($SeedDatabase) {
    $DatabaseDirectory = Join-Path $SmokeRoot 'AIOptimizationTool\database'
    New-Item -ItemType Directory -Force -Path $DatabaseDirectory | Out-Null
    Copy-Item -LiteralPath $SeedDatabase -Destination (Join-Path $DatabaseDirectory 'ai-optimization-tool.db')
}
$PreviousLocalAppData = $env:LOCALAPPDATA
$LifecycleLogPath = Join-Path $PreviousLocalAppData 'com.aioptimizationtool.desktop\logs\desktop-lifecycle.log'
$InitialLifecycleLineCount = if (Test-Path -LiteralPath $LifecycleLogPath) { @(Get-Content -LiteralPath $LifecycleLogPath).Count } else { 0 }
$First = $null
$PreferencesPath = Join-Path $env:APPDATA 'com.aioptimizationtool.desktop\lifecycle.json'
$OriginalPreferences = if (Test-Path -LiteralPath $PreferencesPath) { [System.IO.File]::ReadAllBytes($PreferencesPath) } else { $null }
$StartedAt = Get-Date
try {
    $env:LOCALAPPDATA = $SmokeRoot
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PreferencesPath) | Out-Null
    [System.IO.File]::WriteAllText($PreferencesPath, '{"keep_running_in_tray":false}')
    $First = Start-Process -FilePath $ExecutablePath -PassThru -WindowStyle Hidden
    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $Frontends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $ExecutablePath })
        $Backends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $BackendPath })
    } while (($Frontends.Count -ne 1 -or $Backends.Count -ne 1) -and (Get-Date) -lt $Deadline)
    if ($Frontends.Count -ne 1 -or $Backends.Count -ne 1) {
        throw "Clean launch expected one frontend and one backend; found $($Frontends.Count) and $($Backends.Count)."
    }
    do {
        Start-Sleep -Milliseconds 500
        $LifecycleLines = if (Test-Path -LiteralPath $LifecycleLogPath) { @(Get-Content -LiteralPath $LifecycleLogPath | Select-Object -Skip $InitialLifecycleLineCount) } else { @() }
        $Ready = @($LifecycleLines | Where-Object { $_ -match 'authenticated readiness passed pid=' })
    } while ($Ready.Count -ne 1 -and (Get-Date) -lt $Deadline)
    if ($Ready.Count -ne 1) { throw 'Desktop backend did not pass authenticated readiness.' }
    Write-Host "Desktop cold launch to authenticated readiness: $([math]::Round(((Get-Date)-$StartedAt).TotalSeconds,3)) seconds"
    if ($SeedDatabase) {
        $Observed = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/analytics?days=365'
        if ($Observed.totals.requests -ne $ExpectedEvents) { throw "Existing telemetry was not preserved: $($Observed.totals.requests), expected $ExpectedEvents" }
        Write-Host "Existing telemetry preserved: $ExpectedEvents records"
    }
    $Second = Start-Process -FilePath $ExecutablePath -PassThru -WindowStyle Hidden
    $Second.WaitForExit(15000) | Out-Null
    Start-Sleep -Milliseconds 750
    $Frontends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $ExecutablePath })
    $Backends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $BackendPath })
    if ($Frontends.Count -ne 1 -or $Backends.Count -ne 1) {
        throw "Duplicate launch changed process ownership; found $($Frontends.Count) frontend and $($Backends.Count) backend."
    }
    if (-not (Test-Path -LiteralPath $LifecycleLogPath)) { throw 'Desktop lifecycle diagnostics were not written.' }
    $LifecycleLines = @(Get-Content -LiteralPath $LifecycleLogPath | Select-Object -Skip $InitialLifecycleLineCount)
    $Spawned = @($LifecycleLines | Where-Object { $_ -match 'backend spawned pid=' })
    $Ready = @($LifecycleLines | Where-Object { $_ -match 'authenticated readiness passed pid=' })
    if ($Spawned.Count -ne 1 -or $Ready.Count -ne 1) { throw 'Expected one spawn and one authenticated readiness event.' }
    $Fingerprints = @($LifecycleLines | ForEach-Object { if ($_ -match 'token=([0-9a-f]{12})') { $Matches[1] } } | Select-Object -Unique)
    if ($Fingerprints.Count -ne 1) { throw 'Frontend launch and backend readiness fingerprints did not match.' }
    $First.Refresh()
    if (-not $First.CloseMainWindow()) { throw 'Desktop window could not be closed for lifecycle smoke test.' }
    $First.WaitForExit(15000) | Out-Null
    Start-Sleep -Milliseconds 750
    $Backends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $BackendPath })
    if (-not $First.HasExited -or $Backends.Count -ne 0) { throw 'Tray-off close did not terminate frontend and owned backend.' }
    Write-Host 'Packaged desktop clean launch=1/1; duplicate launch=1/1; tray-off close=0/0'
    [System.IO.File]::WriteAllText($PreferencesPath, '{"keep_running_in_tray":true}')
    $First = Start-Process -FilePath $ExecutablePath -PassThru -WindowStyle Hidden
    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $First.Refresh()
        $LifecycleLines = @(Get-Content -LiteralPath $LifecycleLogPath | Select-Object -Skip $InitialLifecycleLineCount)
        $Ready = @($LifecycleLines | Where-Object { $_ -match 'authenticated readiness passed pid=' })
    } while (($Ready.Count -lt 2 -or $First.MainWindowHandle -eq 0) -and (Get-Date) -lt $Deadline)
    if ($Ready.Count -ne 2 -or -not $First.CloseMainWindow()) { throw 'Tray-on launch did not become ready.' }
    Start-Sleep -Milliseconds 1000
    $First.Refresh()
    $Backends = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $BackendPath })
    if ($First.HasExited -or $Backends.Count -ne 1) { throw 'Tray-on close did not preserve the owned backend.' }
    $Second = Start-Process -FilePath $ExecutablePath -PassThru -WindowStyle Hidden
    $Second.WaitForExit(15000) | Out-Null
    Start-Sleep -Milliseconds 750
    $First.Refresh()
    if ($First.MainWindowHandle -eq 0) { throw 'Duplicate launch did not reopen the tray window.' }
    Write-Host 'Packaged desktop tray-on close=1/1; duplicate launch reopens window; preferences restored after test'
}
finally {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -in @($ExecutablePath, $BackendPath)
    }) | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $env:LOCALAPPDATA = $PreviousLocalAppData
    if ($null -ne $OriginalPreferences) { [System.IO.File]::WriteAllBytes($PreferencesPath, $OriginalPreferences) }
    elseif (Test-Path -LiteralPath $PreferencesPath) { Remove-Item -LiteralPath $PreferencesPath -Force }
    $VerifiedSmokeRoot = [System.IO.Path]::GetFullPath($SmokeRoot)
    $VerifiedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $VerifiedSmokeRoot.StartsWith($VerifiedTempRoot, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $VerifiedSmokeRoot) -notlike 'aiopt-desktop-smoke-*') { throw 'Unsafe smoke cleanup path.' }
    if (Test-Path -LiteralPath $VerifiedSmokeRoot) { Remove-Item -LiteralPath $VerifiedSmokeRoot -Recurse -Force }
}
