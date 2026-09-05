# AI Optimization Tool

AI Optimization Tool is a free, open-source, local-first application for understanding, forecasting, and optimizing AI usage. Core analytics work entirely on the local machine. Paid API keys and cloud integrations are optional.

Version 0.16.0 is an enterprise-ready foundation: backend roles, optional enterprise configuration, safe local backup/restore, explicit retention enforcement, Windows credential storage, diagnostics, bounded queries, and larger readable text. Local Mode remains the default. Production SSO, shared multi-user hosting and automatic updates are not active. See the [enterprise guide](docs/ENTERPRISE.md) and [validation report](docs/RELEASE_0.16.0.md). Development installer builds remain unsigned.

## Developer quick start

Windows: `.\scripts\dev.ps1`. Linux/macOS: `./scripts/dev.sh`. Open <http://127.0.0.1:3000>.

Manual setup:

```powershell
python -m pip install -r apps/api/requirements.txt
python -m uvicorn tokenscope_api.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
npm install
npm run dev -- --host 127.0.0.1 --port 3000
```

Docker remains supported with `docker compose up --build`.

## Desktop development and installer

Install Rust with the MSVC toolchain and Windows WebView2/NSIS prerequisites, then run `npm install` and `npm run desktop:dev`.

For an installer:

```powershell
npm run backend:package
npm run desktop:build
```

Artifacts appear under `src-tauri\target\release\bundle\nsis\`. See [desktop architecture](docs/desktop.md) and [installation](docs/installation.md).

Before distributing a release candidate, follow [the release process](docs/release-process.md) and [release checklist](docs/release-checklist.md). `VERSION` is the authoritative application version; run `npm run release:verify-version` to validate every manifest.

Desktop user data lives outside the installation directory under `%LOCALAPPDATA%\AIOptimizationTool\`. See [application standards](docs/application-standards.md), [data storage](docs/data-storage.md), and [privacy](docs/privacy.md). Apache-2.0 licensed.
