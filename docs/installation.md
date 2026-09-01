# Windows installation

The Tauri NSIS configuration targets a per-machine installation with version/uninstall metadata and a stable upgrade identity. User telemetry stays in `%LOCALAPPDATA%\AIOptimizationTool\`, outside installer resources, so upgrades and normal uninstall preserve it. Removing application data must be explicit.

Run `npm run backend:package`, then `npm run desktop:build`. The NSIS executable is under `src-tauri\target\release\bundle\nsis\`; publishing should name it `AIOptimizationTool-Setup-x64.exe`.

Production requires an Authenticode certificate protected in CI, timestamping, malware scanning, and signature verification. Unsigned development builds can trigger Windows reputation warnings.
