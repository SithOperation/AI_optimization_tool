# Application standards

The product name is **AI Optimization Tool**, repository name `AI_optimization_tool`, identifier `AIOptimizationTool`, and semantic version source `VERSION`. Releases use `MAJOR.MINOR.PATCH`; package, API, and desktop manifests must match it.

Installed binaries are separate from user data. Desktop data lives at `%LOCALAPPDATA%\AIOptimizationTool\` with `database`, `logs`, `backups`, `exports`, `cache`, and `config` children. `AIOPT_DATA_DIR` is the supported override. Developer mode preserves repository-local data. Configuration must remain backward compatible and must not contain plaintext secrets when a reference is sufficient.

Structured JSON logs rotate at 5 MB with five backups: `application.log`, `api.log`, and `errors.log`. API keys, passwords, authorization headers, prompts, and responses are never logged. API errors use an appropriate HTTP status and `{ "detail": "safe explanation" }`. Fatal UI errors preserve data, offer retry/details, and never render blank pages.

Health states are `Healthy`, `Starting`, `Unavailable`, or `Error`; `Healthy` requires a check. Loading views identify the subsystem and empty views explain how to add data. Navigation stays compact and keyboard-operable. Controls require visible focus, semantic labels, contrast, and descriptive tooltips. Reusable badges distinguish `OBSERVED`, `ESTIMATED`, and `FORECAST`. Modes alter presentation over one database.

Metadata collection defaults on; content and identity default off. APIs bind to `127.0.0.1`, CORS is allowlisted, URLs are validated, ingestion is rate-limited, and secrets are excluded from exports/logs. Desktop shutdown owns its child processes. Web, Python, tests, and Docker development remain supported.
