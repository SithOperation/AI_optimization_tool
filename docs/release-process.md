# Release process

`VERSION` is the authoritative semantic version. Keep `package.json`, the package-lock root entries, `src-tauri/Cargo.toml`, the application entry in `Cargo.lock`, `tauri.conf.json`, and the backend version assertion synchronized. Validate them with `npm run release:verify-version`.

## Clean Windows build

1. Confirm `git status --short` is empty and record `git rev-parse HEAD`.
2. Stop only development processes owned by this repository.
3. Remove `dist` and `src-tauri/target` build output. Never remove `%LOCALAPPDATA%\AIOptimizationTool`.
4. Run `npm ci` and install `apps/api/requirements.txt` in `.venv`.
5. Run Python tests and compile checks, `npm run build`, `npm audit --audit-level=high`, `cargo fmt --check`, and `cargo check`.
6. Run `npm run backend:package` and `powershell -File scripts/smoke-packaged-backend.ps1`.
7. Run `npm run test:ui`.
8. Run `npm run desktop:build`.
9. Run `npm run release:checksum` and `npm run release:sbom`.
10. Complete `docs/windows-validation.md` and archive the installer, checksum, SBOMs, commit, and build log.

The installer is written to `src-tauri/target/release/bundle/nsis/`. The checksum is written to `artifacts/AI-Optimization-Tool-<version>-SHA256.txt`.

## SBOM

`npm run release:sbom` produces CycloneDX JSON documents for Python, npm, and Rust under `artifacts/sbom`. It installs `cyclonedx-bom` into the release virtual environment, invokes `@cyclonedx/cyclonedx-npm`, and installs `cargo-cyclonedx` if absent. These are separate ecosystem documents; a merged application-level BOM is a future improvement.

## Publishing boundary

CI builds and retains release-candidate artifacts for 14 days but does not publish a GitHub Release. Publishing requires an intentional version tag, completed checklist, clean-machine validation, approved icon, Authenticode signing/timestamping, malware review, and signature verification.

## Branding status

The repository contains one working 256x256 Windows ICO at `src-tauri/icons/icon.ico` and no separately approved production brand package. Tauri uses this resource consistently for the executable, window/taskbar, installer, and shortcut. It remains a temporary release asset; do not replace it with invented artwork. Final brand approval is required before public v1.0 distribution.
