param([string]$Installer)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Version = (Get-Content -Raw (Join-Path $RepoRoot 'VERSION')).Trim()
if (-not $Installer) {
    $Installer = (Get-ChildItem (Join-Path $RepoRoot 'src-tauri\target\release\bundle\nsis') -Filter "*$Version*-setup.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $Installer -or -not (Test-Path -LiteralPath $Installer)) { throw "Installer for $Version was not found." }
$ArtifactDir = Join-Path $RepoRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
$Hash = Get-FileHash -LiteralPath $Installer -Algorithm SHA256
$Output = Join-Path $ArtifactDir "AI-Optimization-Tool-$Version-SHA256.txt"
"$($Hash.Hash)  $([System.IO.Path]::GetFileName($Installer))" | Set-Content -LiteralPath $Output -Encoding ascii
Write-Host "SHA-256 $($Hash.Hash)"
Write-Host "Checksum $Output"
