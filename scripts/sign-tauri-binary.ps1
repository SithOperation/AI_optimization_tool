param([Parameter(Mandatory=$true)][string]$Target)
$ErrorActionPreference = 'Stop'
if (-not $env:WINDOWS_SIGNING_PFX_BASE64 -or -not $env:WINDOWS_SIGNING_PFX_PASSWORD -or -not $env:WINDOWS_SIGNING_TIMESTAMP_URL) {
    Write-Warning "Authenticode inputs are absent; leaving unsigned: $Target"
    exit 0
}
$SignTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $SignTool) { throw 'signtool.exe is required when signing inputs are configured.' }
$CertificatePath = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-tauri-signing-" + [guid]::NewGuid().ToString('N') + '.pfx')
try {
    [System.IO.File]::WriteAllBytes($CertificatePath, [Convert]::FromBase64String($env:WINDOWS_SIGNING_PFX_BASE64))
    & $SignTool sign /fd SHA256 /f $CertificatePath /p $env:WINDOWS_SIGNING_PFX_PASSWORD /tr $env:WINDOWS_SIGNING_TIMESTAMP_URL /td SHA256 $Target
    if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $Target" }
    if ((Get-AuthenticodeSignature -LiteralPath $Target).Status -ne 'Valid') { throw "Signature validation failed for $Target" }
}
finally {
    if (Test-Path -LiteralPath $CertificatePath) { Remove-Item -LiteralPath $CertificatePath -Force }
}
