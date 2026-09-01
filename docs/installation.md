# Windows installation

The Tauri NSIS configuration targets a per-machine installation with version/uninstall metadata and a stable upgrade identity. User telemetry stays in `%LOCALAPPDATA%\AIOptimizationTool\`, outside installer resources, so upgrades and normal uninstall preserve it. Removing application data must be explicit.

Run `npm run backend:package`, then `npm run desktop:build`. The NSIS executable is under `src-tauri\target\release\bundle\nsis\`; publishing should name it `AIOptimizationTool-Setup-x64.exe`.

For a clean release build, follow `docs/release-process.md`. Normal upgrade and uninstall preserve `%LOCALAPPDATA%\AIOptimizationTool`; application data is never stored under Program Files and is removed only by an explicit user action. Validate upgrade, uninstall, and reinstall behavior with `docs/windows-validation.md` before publishing.

Production requires an Authenticode certificate protected in CI, timestamping, malware scanning, and signature verification. Unsigned development builds can trigger Windows reputation warnings.
