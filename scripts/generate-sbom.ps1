$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Output = Join-Path $RepoRoot 'artifacts\sbom'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
Push-Location $RepoRoot
try {
    & .\.venv\Scripts\python.exe -m pip install cyclonedx-bom
    if ($LASTEXITCODE -ne 0) { throw 'Could not install cyclonedx-bom.' }
    & .\.venv\Scripts\cyclonedx-py.exe requirements .\apps\api\requirements.txt --output-reproducible --output-format JSON --output-file (Join-Path $Output 'python.cdx.json')
    if ($LASTEXITCODE -ne 0) { throw 'Python SBOM generation failed.' }
    & npx --yes @cyclonedx/cyclonedx-npm --output-file (Join-Path $Output 'npm.cdx.json')
    if ($LASTEXITCODE -ne 0) { throw 'npm SBOM generation failed.' }
    if (-not (Get-Command cargo-cyclonedx -ErrorAction SilentlyContinue)) { cargo install cargo-cyclonedx --locked }
    cargo cyclonedx --manifest-path src-tauri\Cargo.toml --format json --override-filename rust.cdx
    if ($LASTEXITCODE -ne 0) { throw 'Rust SBOM generation failed.' }
    Move-Item -LiteralPath (Join-Path $RepoRoot 'src-tauri\rust.cdx.json') -Destination (Join-Path $Output 'rust.cdx.json') -Force
    Get-ChildItem $Output -Filter '*.json' | ForEach-Object { Write-Host "$($_.Name) $($_.Length) bytes" }
}
finally { Pop-Location }
