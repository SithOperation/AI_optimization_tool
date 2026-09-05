$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aiopt-backend-" + [guid]::NewGuid().ToString('N'))
if (-not (Test-Path -LiteralPath $Python)) { python -m venv (Join-Path $RepoRoot '.venv') }
& $Python -m pip install -r (Join-Path $RepoRoot 'apps\api\requirements.txt') pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging dependencies could not be installed.' }
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name aiopt-backend --workpath (Join-Path $BuildRoot 'work') --specpath (Join-Path $BuildRoot 'spec') --distpath (Join-Path $BuildRoot 'dist') --paths (Join-Path $RepoRoot 'apps\api') --paths $RepoRoot --add-data "$(Join-Path $RepoRoot 'VERSION');." --collect-all statsforecast --exclude-module numba.np.ufunc.tbbpool (Join-Path $RepoRoot 'apps\api\desktop_entry.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to package the backend.' }
$Destination = Join-Path $RepoRoot 'src-tauri\binaries\aiopt-backend'
$LegacyOneFile = Join-Path $RepoRoot 'src-tauri\binaries\aiopt-backend.exe'
$LegacyReleaseOneFile = Join-Path $RepoRoot 'src-tauri\target\release\binaries\aiopt-backend.exe'
$VerifiedRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\') + '\'
foreach ($TargetPath in @($Destination, $LegacyOneFile, $LegacyReleaseOneFile)) {
    if (-not [System.IO.Path]::GetFullPath($TargetPath).StartsWith($VerifiedRepoRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Packaging target is outside the repository.' }
}
if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
if (Test-Path -LiteralPath $LegacyOneFile) { Remove-Item -LiteralPath $LegacyOneFile -Force }
if (Test-Path -LiteralPath $LegacyReleaseOneFile) { Remove-Item -LiteralPath $LegacyReleaseOneFile -Force }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
Copy-Item -LiteralPath (Join-Path $BuildRoot 'dist\aiopt-backend') -Destination $Destination -Recurse
