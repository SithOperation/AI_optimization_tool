$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Expected = (Get-Content -Raw (Join-Path $RepoRoot 'VERSION')).Trim()
$Package = Get-Content -Raw (Join-Path $RepoRoot 'package.json') | ConvertFrom-Json
$Tauri = Get-Content -Raw (Join-Path $RepoRoot 'src-tauri\tauri.conf.json') | ConvertFrom-Json
$CargoToml = Get-Content -Raw (Join-Path $RepoRoot 'src-tauri\Cargo.toml')
$CargoLock = Get-Content -Raw (Join-Path $RepoRoot 'src-tauri\Cargo.lock')
$TestFile = Get-Content -Raw (Join-Path $RepoRoot 'tests\test_api.py')

$Checks = [ordered]@{
    'package.json' = $Package.version
    'package-lock.json' = (& node -p "require('./package-lock.json').version")
    'package-lock root package' = (& node -p "require('./package-lock.json').packages[''].version")
    'tauri.conf.json' = $Tauri.version
}
foreach ($Item in $Checks.GetEnumerator()) {
    if ($Item.Value -ne $Expected) { throw "$($Item.Key) is $($Item.Value); expected $Expected" }
}
if ($CargoToml -notmatch "(?m)^version = `"$([regex]::Escape($Expected))`"$") { throw 'Cargo.toml version is not synchronized.' }
if ($CargoLock -notmatch "(?ms)name = `"ai-optimization-tool`"\r?\nversion = `"$([regex]::Escape($Expected))`"") { throw 'Cargo.lock version is not synchronized.' }
if ($TestFile -notmatch "VERSION==`"$([regex]::Escape($Expected))`"") { throw 'Version assertion is not synchronized.' }
Write-Host "All application metadata matches VERSION=$Expected"
