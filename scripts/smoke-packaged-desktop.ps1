param(
    [string]$Executable = "src-tauri\target\release\ai-optimization-tool.exe",
    [int]$StartupTimeoutSeconds = 90
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExecutablePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Executable))
$BackendPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'src-tauri\target\release\binaries\aiopt-backend\aiopt-backend.exe'))
if (-not (Test-Path -LiteralPath $ExecutablePath)) { throw "Desktop executable not found: $ExecutablePath" }
$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-desktop-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
$PreviousLocalAppData = $env:LOCALAPPDATA
$LifecycleLogPath = Join-Path $PreviousLocalAppData 'com.aioptimizationtool.desktop\logs\desktop-lifecycle.log'
$InitialLifecycleLineCount = if (Test-Path -LiteralPath $LifecycleLogPath) { @(Get-Content -LiteralPath $LifecycleLogPath).Count } else { 0 }
$First = $null
try {
    $env:LOCALAPPDATA = $SmokeRoot
    $First = Start-Process -FilePath $ExecutablePath -PassThru
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
    $Second = Start-Process -FilePath $ExecutablePath -PassThru
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
}
finally {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -in @($ExecutablePath, $BackendPath)
    }) | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $env:LOCALAPPDATA = $PreviousLocalAppData
    if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
}
