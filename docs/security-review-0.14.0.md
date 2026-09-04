# Backend security review — version 0.14.0

Reviewed September 4, 2026 against the FastAPI, SQLite/SQLAlchemy, PyInstaller, Tauri 2, Vite, and NSIS implementation in this repository.

## Attack surface

The desktop entry point is `apps/api/desktop_entry.py`; it runs Uvicorn without reload or debug mode on fixed IPv4 loopback `127.0.0.1:8000`. It does not bind IPv6 or a LAN interface. Docker listens on all container interfaces, but Compose publishes both API and web ports to host loopback only. There are no WebSocket routes. HTTP entry points comprise health/application setup, telemetry event and batch ingestion/reset, demo data, analytics/filter/pricing/forecast/anomaly/optimization/budget/simulator/model-evaluation APIs, local integration discovery/configuration/adapters, privacy/retention/audit settings, CSV/configuration reports and exports, SSE live metrics, and the staged multipart import routes.

Filesystem access is limited to application data directories, SQLite, rotating logs, generated exports/cache, and server-generated import temp names. Database access uses SQLAlchemy expression APIs. Backend subprocess execution is absent; desktop subprocess use is limited to the fixed backend executable, `taskkill` with an app-owned numeric PID, and Explorer for the fixed log directory. Configuration uses documented `AIOPT_*`, `TOKENSCOPE_*`, `LOCALAPPDATA`, and optional provider credential environment-variable names. Tauri exposes startup/retry/log/exit, tray preference, and per-launch backend-token commands.

## A. Confirmed vulnerabilities

| ID | Title | Severity | Affected code | Evidence and exploit scenario | Fix | Validation |
|---|---|---:|---|---|---|---|
| SEC-001 | Large imports were buffered fully in RAM | High | `StreamingImporter.analyze_file`, `execute_import` | Each phase called `read()` on a file permitted to reach 500 MB, producing raw bytes plus decoded text and parsed objects. A local caller could force multi-gigabyte peak memory and terminate the backend. | CSV, JSONL, and JSON-array parsing now iterate from disk; encoding/delimiter inspection reads 64 KB. Individual records are capped at 2 MB. | Small imports and malformed/oversized-record tests pass; source contains no unbounded import-file `read()`. |
| SEC-002 | Repeated chunks bypassed declared and maximum file size | High | `upload_chunk`, `receive_file_chunk` | Every request was accepted and appended; neither cumulative size nor the declared size was checked. Repetition could consume arbitrary disk space. | Multipart requests are capped at 6 MB including overhead, file data at 5 MB/chunk, writes are serialized per import, cumulative bytes cannot exceed declared size or 500 MB, and analysis requires an exact final size. | Cumulative-overflow and incomplete-upload regression tests pass. |
| SEC-003 | Desktop privileged mutations had no per-launch authorization | Medium | FastAPI security middleware; Tauri/backend startup | Loopback and CORS reduce remote exposure but do not authenticate non-browser local callers, and CORS alone is not authorization. | Tauri generates a random UUID token for each launch, passes it only to its owned sidecar, and supplies it on frontend API calls. Desktop non-ingestion mutations require constant-time token comparison; optional `TOKENSCOPE_API_KEY` still protects all non-health APIs. External telemetry ingestion remains compatible. | Missing-token telemetry reset returns 401; matching token succeeds; malicious-origin preflight is denied. |
| SEC-004 | Non-finite JSON numbers could break validation response serialization | Low | FastAPI validation error handling | Pydantic correctly rejected `NaN`, but the default error payload repeated the non-finite input and Starlette could not serialize it, raising an internal exception. | Strict request models reject NaN/Infinity and a controlled validation handler omits raw input/context. | NaN now returns a controlled 422 without traceback disclosure. |

## B. Security hardening opportunities

| ID | Title | Severity | Affected code | Evidence / threat | Fix | Validation |
|---|---|---:|---|---|---|---|
| HARD-001 | Production API documentation exposure | Low | FastAPI construction | Interactive docs and schema were enabled in the packaged sidecar. | `/docs`, `/redoc`, and `/openapi.json` are disabled only in desktop runtime and retained for development. | Desktop-runtime configuration test/review. |
| HARD-002 | Broad development CORS origins in production | Low | CORS configuration | Vite localhost origins were present in all modes. | Packaged desktop permits only Tauri origins; development keeps explicit loopback Vite origins. No wildcard origins, credentials, methods, or headers are enabled. | Malicious origin has no allow-origin response. |
| HARD-003 | Abandoned imports and import-start flooding | Medium | import startup/cache | Abandoned files persisted indefinitely and active jobs had no count limit. | Stale temp files older than 24 hours are removed at startup; active jobs are capped at ten; success, cancel, analysis failure, and commit failure clean files. | Cleanup, failure-state, and active workflow tests pass. |
| HARD-004 | Request models accepted unknown fields and some unbounded strings/non-finite floats | Medium | `schemas.py` | Several write models silently ignored extra fields and lacked finite-number/string bounds. | Request models share `extra="forbid"` and `allow_inf_nan=False`; missing identifiers and adapter/model fields gained bounds; mapping size is capped. | Oversized, extra-field, negative, and non-finite input tests pass. |
| HARD-005 | Multipart dependency was unpinned | Low | `requirements.txt` | `python-multipart` could change between builds. | Pinned to the validated installed version `0.0.32`. | `pip check` reports no conflicts. |
| HARD-006 | Chunked bodies could bypass header-only request sizing | Medium | HTTP middleware | Requests without `Content-Length` were not bounded by the 5 MB/6 MB header checks and enabled indefinite request bodies. | Body-bearing API requests now require `Content-Length`; actual file bytes are independently streamed and bounded. | Existing clients/tests send lengths; malformed body tests remain controlled. |

## C. Reviewed-safe areas and false positives

| Area | Result |
|---|---|
| SQL injection | No raw SQL, f-string SQL, or user-selected unvalidated columns found. Dynamic analytics columns are selected from fixed allowlists. Injection payload regression remains data and the table remains usable. |
| Filename traversal | Client filename is metadata only; storage uses UUID import IDs. Traversal, absolute, UNC, and separator-bearing names are rejected. Import cache rejects symlink directories/files before sensitive operations. |
| CSV formula injection | Existing `csv_safe()` prefixes dangerous spreadsheet formula characters in event and executive CSV exports. Rejected-row exports contain server-generated error/field-name data, not raw cell values. |
| Unsafe deserialization | No application use of pickle, unsafe YAML, `eval`, `exec`, shelve, or arbitrary module loading was found. JSON and CSV use standard parsers with new depth/record memory bounds. |
| Command injection | No backend subprocess surface exists. Tauri uses argument arrays and fixed executables/paths; `taskkill` receives only the PID of the child it spawned. |
| SSRF | Integration URLs reject credentials and public IPs; DNS results must all be private or loopback. Fixed discovery probes target explicit loopback URLs. DNS rebinding between validation and use remains a low-priority architectural limitation. |
| Tauri/WebView | CSP permits only same-origin assets and loopback API connections; no remote scripts or eval are allowed. Capability file grants `core:default` only—no filesystem, shell, HTTP, opener, process, or updater capability. |
| Secrets | Working tree and filename/history scans found no committed private key, `.env`, credential, or signing-secret file. `.gitignore` covers `.env*` (except the template), keys/runtime databases should remain excluded, import fixtures, build outputs, logs, and sidecar binaries. Pattern hits were documented variable names/examples, not embedded secrets. |
| SQLite confidentiality | The database contains telemetry metadata and is protected by the current Windows account boundary, not encryption. Another process running as that user can read/modify it. Encryption was not added because secure key management is not present and a hardcoded key would provide no protection. Transactions roll back telemetry reset and import failures. |
| Logging | API logs contain timestamp, method, path, status, and duration—not bodies, headers, tokens, credentials, query strings, or imported rows. Application logs currently include local data/database paths for diagnostics; this is local-path disclosure only. Security-relevant configuration/import/reset actions use the database audit log. |

## Dependencies and packaging

- `npm audit`: 0 vulnerabilities across 80 dependencies.
- Python: all runtime requirements are pinned after pinning `python-multipart`; `pip check` reports no conflicts. `pip-audit` is not installed, so no Python advisory-database claim is made.
- Rust: `cargo audit` found no vulnerability advisory, but reported one transitive Linux GTK unsoundness warning (`glib 0.18.5`) and 16 unmaintained transitive crates. These are not reachable in the Windows target; resolving them depends on upstream Tauri/Linux dependency migration. `cargo tree --duplicates` was reviewed.
- PyInstaller: one-file/windowed build, debug disabled, no reload, fixed loopback bind, and no secret configuration embedded. StatsForecast is intentionally collected. Extraction uses PyInstaller's per-run temp behavior. The checked-in `.spec` contains stale developer absolute paths but the packaging script generates a clean temporary spec and does not use it.
- Sidecar: Tauri rejects occupied port 8000 instead of attaching, validates the exact health response, owns the spawned PID, and terminates that process tree on exit. The per-launch token also prevents an unrelated service on the port from satisfying privileged frontend requests.

## Residual recommendations

A random port would reduce port collision but adds coordination complexity without replacing authentication; the per-launch token directly mitigates the more important localhost trust issue, so port 8000 remains fixed. Consider an ASGI-server-level request-body timeout in a future release if Uvicorn exposes a stable supported setting. Consider pinning Python dependencies with hashes/SBOM policy in the release pipeline and monitoring the transitive Linux Rust advisories. Code signing credentials remain a release-environment requirement rather than a repository secret.
