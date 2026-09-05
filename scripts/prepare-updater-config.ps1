param(
    [Parameter(Mandatory=$true)][string]$Endpoint,
    [Parameter(Mandatory=$true)][string]$PublicKey,
    [ValidateSet('stable','preview')][string]$Channel = 'stable'
)
$ErrorActionPreference = 'Stop'
$Uri = [Uri]$Endpoint
if ($Uri.Scheme -ne 'https' -or $Uri.UserInfo -or $Uri.Query -or $Uri.Fragment) {
    throw 'An HTTPS update endpoint without credentials, query, or fragment is required.'
}
try { $Decoded = [Convert]::FromBase64String($PublicKey) } catch { throw 'Public key must be base64 encoded.' }
if ($Decoded.Length -lt 32) { throw 'Public key is too short.' }
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OutputRoot = Join-Path $RepoRoot 'artifacts\updater'
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$Config = @{
    bundle = @{ createUpdaterArtifacts = $true }
    plugins = @{ updater = @{ pubkey = $PublicKey; endpoints = @($Endpoint.TrimEnd('/') + '/' + $Channel + '/latest.json') } }
}
$Config | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputRoot ($Channel + '.json'))
Write-Host "Prepared $Channel build overlay. Runtime updater plugin, signature verification tests, signing keys, and hosting are still required before activation."
