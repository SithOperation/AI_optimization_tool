# Windows release-candidate CI

`.github/workflows/ci.yml` includes a non-publishing `windows-release-candidate` job. It installs Python, Node, Rust/rustfmt, and dependencies; verifies synchronized versions; runs backend, frontend, Rust, packaged-backend, forecast, Scenario Lab, UI, Tauri, NSIS, checksum, SBOM, and dependency-security checks.

The job uploads the installer, SHA-256 text file, three CycloneDX JSON documents, and Playwright report as `AI-Optimization-Tool-0.12.0-windows-rc`. It does not create tags or GitHub Releases. Microsoft Defender scans the installer when the hosted runner exposes its command-line scanner; otherwise the log records that limitation for manual follow-up.

Screenshot baselines live under `tests/ui/__screenshots__`. Update them intentionally with `npm run test:ui:update` after reviewing the visual changes at both configured viewport sizes. Dynamic telemetry assertions use a small pixel-difference tolerance and should not be loosened to hide structural regressions.
