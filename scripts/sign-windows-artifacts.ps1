param(
    [ValidateSet('Backend', 'Release')]
    [string]$Stage = 'Release'
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$CertificateBase64 = $env:WINDOWS_SIGNING_PFX_BASE64
$CertificatePassword = $env:WINDOWS_SIGNING_PFX_PASSWORD
$TimestampUrl = $env:WINDOWS_SIGNING_TIMESTAMP_URL
if (-not $CertificateBase64 -or -not $CertificatePassword -or -not $TimestampUrl) {
    Write-Warning "Authenticode inputs are absent; $Stage artifacts remain unsigned for this internal build."
    exit 0
}
$SignTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $SignTool) { throw 'signtool.exe is required when signing inputs are configured.' }
$CertificatePath = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-signing-" + [guid]::NewGuid().ToString('N') + '.pfx')
try {
    [System.IO.File]::WriteAllBytes($CertificatePath, [Convert]::FromBase64String($CertificateBase64))
    $Targets = if ($Stage -eq 'Backend') {
        @(Join-Path $RepoRoot 'src-tauri\binaries\aiopt-backend.exe')
    } else {
        @(
            (Join-Path $RepoRoot 'src-tauri\target\release\ai-optimization-tool.exe'),
            (Get-ChildItem (Join-Path $RepoRoot 'src-tauri\target\release\bundle\nsis') -Filter '*-setup.exe' | Select-Object -ExpandProperty FullName)
        )
    }
    foreach ($Target in $Targets) {
        if (-not (Test-Path -LiteralPath $Target)) { throw "Signing target is missing: $Target" }
        & $SignTool sign /fd SHA256 /f $CertificatePath /p $CertificatePassword /tr $TimestampUrl /td SHA256 $Target
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $Target" }
        $Signature = Get-AuthenticodeSignature -LiteralPath $Target
        if ($Signature.Status -ne 'Valid') { throw "Signature validation failed for $Target: $($Signature.Status)" }
    }
}
finally {
    if (Test-Path -LiteralPath $CertificatePath) { Remove-Item -LiteralPath $CertificatePath -Force }
}
