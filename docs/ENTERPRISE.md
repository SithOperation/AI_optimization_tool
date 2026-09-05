# 0.16.0 enterprise-ready foundation

This release preserves the local desktop product and adds administration foundations. It is **not a validated multi-user enterprise service**. No certification, regulatory compliance, production SSO, hosted API, or managed update service is claimed.

## Architecture and gap analysis

| Area | Baseline gap | 0.16.0 implementation | Remaining priority |
| --- | --- | --- | --- |
| Identity | A desktop launch token identifies a process, not an employee | Immutable identity context and vendor-neutral provider protocol; explicit deployment configuration | Must-have before shared deployment: validated OIDC, issuer/audience/signature/expiry checks, group mapping and revocation |
| Authorization | No employee roles | Global FastAPI authorization dependency; Viewer, Analyst, Administrator; mutation routes default to Administrator | Must-have before shared deployment: tenant and budget ownership boundaries; no employee/role management UI is claimed |
| Storage | SQLite assumed in health and date buckets | Local SQLite default retained; DATABASE_URL alias; PostgreSQL SQL compilation and UTC date buckets | Must-have before server deployment: live PostgreSQL integration tests, migration tooling and operational recovery |
| Secrets | Environment references only | Windows Credential Manager adapter and masked save/replace/delete; portable service protocol | Strongly recommended: enterprise vault adapter, rotation and access reviews |
| Deployment | Unsigned NSIS development builds | Synchronized version and fail-closed optional signing gate; deployment guidance | Must-have for managed production distribution: signing certificate, trusted timestamps and clean-VM deployment acceptance |
| Administration | No enterprise configuration boundary | Saved deployment intentions, retention opt-in, backup/restore and diagnostics GUI | Future: centralized policy distribution, fleet inventory and managed configuration |
| Auditability | Some configuration events, no actor context | Actor/result/resource metadata, startup/auth denial/import/export/request actions; restore and reset preserve audit history | Must-have for regulated shared use: externally protected audit sink, retention and access policy |
| Logging | Local JSON access logs | Local JSON logs retained; forwarding intentions modeled | Strongly recommended: real forwarding adapter, redaction review and log delivery monitoring |
| Backup/restore | No integrated recovery UI | Versioned SQLite snapshots, SHA-256/integrity/schema validation, recovery copy, transaction rollback | Strongly recommended: protected off-device copies and recovery drills; no encrypted archive claim |
| Updates | Manual installation | Signing gate and stable/preview updater build-overlay generator | Must-have before automatic updates: updater runtime, embedded trusted public key, signature tests and real hosting |
| Policy | Retention window with apply action | Explicit Administrator enforcement opt-in, affected-row preview and audited manual transaction | Future: centrally enforced scheduled policies and legal holds |
| Multi-user | Single local administrator | Identity/RBAC seams only; enterprise runtime fails closed without a provider | Must-have: organizational isolation, secure network ingress, TLS and concurrency validation |
| Scale | Proven 150k import; unbounded result groups | 500k/1m opt-in benchmarks; paginated telemetry/analytics/models; bounded rankings and CSV streaming | Strongly recommended: high-cardinality workload tests, query plans and performance budgets |
| Observability | Basic health | Version, DB connectivity/count, import state, last successful import, uptime, backend state; copy/JSON export | Future: metrics endpoint, distributed traces and alerting |
| Compliance readiness | Local security controls but no attestation | Documented controls, limitations and evidence | Must-have for any compliance claim: independent assessment, governance and customer-specific requirements |

## Local Mode

Vite renders the UI; Tauri 2 owns one loopback-only PyInstaller/FastAPI sidecar and a per-launch authentication token. SQLAlchemy persists telemetry and configuration in SQLite. Windows tray behavior, single-instance ownership, importer limits and restrictive CORS/CSP remain in place. Local dashboards, budgets, scenarios, reports, pricing and imports require no paid API key or identity provider. Existing offline functionality remains available.

The installed database remains `%LOCALAPPDATA%\AIOptimizationTool\database\ai-optimization-tool.db`. `AIOPT_DATA_DIR` overrides the root for tests or managed deployment. Do not point test suites at real data: legacy tests recreate their configured database.

## Enterprise configuration and identity

Settings → Enterprise / Administration → Enterprise deployment configuration stores non-secret deployment intentions in `app_settings.enterprise`: planned mode, organization, HTTPS API URL, OIDC issuer/client ID/audience and database mode. The model also includes planned log forwarding and release channel. Unsupported forwarding/update controls are deliberately absent from the UI.

Saving intentions does **not** switch the desktop API connection, initialize PostgreSQL, authenticate with an IdP or start a remote service. The response explicitly reports `configuration_only`, active mode and identity connection state. HTTPS URLs reject embedded credentials, queries and fragments; secret fields and unknown fields are rejected.

`AIOPT_OPERATING_MODE=local` is the default runtime. `enterprise` requires a trusted server implementation attached to `app.state.identity_provider` that satisfies `IdentityProvider.authenticate(request)`. Without one, all API requests fail with 503; there is no fallback to local Administrator. The provider must independently validate tokens and membership before returning an `Identity`. Entra ID, Okta and other OIDC providers fit this boundary; no provider-specific claims, SAML, unsigned JWT parsing or browser-supplied role headers are trusted. A test provider is only used in regression tests.

## RBAC

| Permission | Viewer | Analyst | Administrator |
| --- | --- | --- | --- |
| Read dashboards, telemetry, existing reports | Yes | Yes | Yes |
| Import telemetry, cancel a pending import | No | Yes | Yes |
| Run scenarios and forecasts, supply model evaluations | No | Yes | Yes |
| Export reports/telemetry, manage budgets | No | Yes | Yes |
| Reset/delete telemetry, configure integrations/policy | No | No | Yes |
| Audit, enterprise configuration, diagnostics, backup/restore and credential management | No | No | Yes |

The existing GET forecast endpoint persists a forecast, so it requires scenario permission. Unknown mutation endpoints require Administrator by default. Local Mode resolves to the local Administrator after the existing transport authentication checks. Analyst budgets are organization-wide in this single-organization foundation; selective ownership and tenant partitioning remain blockers for shared service deployment. There is no implemented role assignment endpoint, and consequently no fictitious role-change audit event.

## Database

Connection precedence is `DATABASE_URL`, then `TOKENSCOPE_DATABASE_URL`, then the existing local SQLite path. SQLAlchemy applies SQLite-specific connection options only to SQLite and checks pooled connections before use. JSON models, timezone-aware datetime declarations, transactions, primary keys and existing timestamp/application/model indexes are retained. UTC day/hour buckets compile to native PostgreSQL expressions while retaining ISO string API values.

For a separately managed Python backend, install the PostgreSQL driver and supply `DATABASE_URL=postgresql+psycopg://...` through a protected process environment or vault launcher. Never save a password-bearing URL in the application settings or a checked-in file. See [SQLAlchemy's PostgreSQL dialect documentation](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html). The desktop bundle does not include a PostgreSQL server or driver and does not become a server deployment when this setting is saved. No live PostgreSQL server was available for this release's local validation; SQL compilation is readiness evidence, not database certification.

## Query bounds and scale

`GET /telemetry/events` returns explicit fields, stable ordering, offset/limit and `has_more` (default 100, maximum 1,000). Usage/Costs `/analytics` supports the same pagination; totals are calculated separately across all matching telemetry. The UI provides Previous/Next controls. Model inventory pages default to 100 and cap at 500. CSV exports stream rows instead of materializing ORM objects and the complete file; offset/limit permits export in batches of up to 100,000. JSON telemetry is available through the paginated endpoint; executive reports remain JSON/CSV and browser print-to-PDF.

Overview totals/daily series remain whole-period aggregates; rankings show at most 100 groups. Filter dropdowns show at most 500 values; API filters accept an exact value outside that list. Forecast application drivers are capped at 100. Optimization rejects more than 10,000 application/model groups and anomalies reject more than 100,000 application/day groups with an explicit error asking for a narrower period, rather than returning misleading partial analysis. These are documented limits, not claims of unlimited cardinality.

The importer continues its existing all-or-nothing telemetry transaction and chunked upload/validation. Million-row tests are opt-in:

```powershell
$env:AIOPT_ENTERPRISE_STRESS='1'
python -m pytest tests/test_enterprise_stress.py -q
python scripts/stress-enterprise.py --rows 150000 --output artifacts/stress-150000.json
```

Each benchmark uses a fresh disposable data directory and generates its fixture. It measures full API upload/analyze/commit, peak process working set, database growth, empty/populated query times and reset. These are single-machine synthetic results, not multi-user load tests or browser paint timings. Large import commit currently occupies the async worker; background job isolation, cancellable in-flight execution and shared-service concurrency need a separate validation pass. The existing importer is deliberately retained.

## Retention

Local default is Unlimited with no automatic deletion. Choose 30/90/180/365 days (the API retains its previously supported 30–3650-day range), explicitly enable manual enforcement, and save. Apply first previews the number of affected records and asks for confirmation. The backend refuses enforcement unless enabled with a finite window. Deletion and its audit event commit together; configuration and audit records are preserved. Saving a policy never starts a scheduler or silently deletes data.

## Backup and restore

Settings → Data Management → Backup Application Data saves `<uuid>.aiopt-backup` under the application data `backups` directory. Copy that file to protected storage using your organization's file tools. To restore a copy on a new installation, place it in that installation's `backups` directory, retaining its UUID filename, then select it in Settings. Only the latest 100 files are listed.

Format 1 is a ZIP containing `manifest.json` and a consistent SQLite snapshot. The manifest includes application version, creation time and SHA-256. Restore accepts the exact current application version/schema, checks ZIP membership/size, checksum and SQLite integrity, rejects views/triggers, and checks tables/columns before touching live data. It creates a recovery backup, restores persistent tables inside a write transaction, retains current audit history, and rolls back on failure. No archive paths are extracted into the live application directory. Pending imports must be finished or cancelled first. The API requires an explicit confirmation boolean and the GUI validates before asking for confirmation.

Included: telemetry, budgets, pricing overrides, integration/provider metadata, privacy/retention/enterprise/application settings, evaluations, forecast/import history and a snapshot of audit history. Restore intentionally keeps the current audit history rather than replaying imported audit events. Excluded: Windows credentials, environment secret values, temporary uploads, browser preferences and Tauri's separate tray preference. Restore does not reconfigure the running database engine or identity provider. Backups contain sensitive telemetry in plaintext; use access-controlled/encrypted storage. SHA-256 detects corruption, not malicious replacement by someone with filesystem write access. Server databases require database-native recovery tooling.

## Secrets and audit

Provider settings store reference names, not keys. Windows users can save or replace a referenced credential under Secure provider credentials. `WindowsCredentials` uses the current user's [Windows Credential Manager APIs](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew). Reads exposed through the API return only availability and a fixed mask. The password field clears after a save attempt. Deleting a stored Windows credential does not erase an independently managed environment variable. Existing environment references remain supported. Other platforms retain environment references; enterprise vault integration is an interface, not an implemented service.

Audit entries contain timestamp, action, actor in safe metadata, outcome and resource. Semantic events cover configuration, budgets, imports, reset, retention, credentials and backups; request events cover mutations and exports and record route templates/status rather than bodies. Startup and denied desktop authentication are audited. No tokens, passwords or provider values are returned in audit/diagnostics. Audit history survives telemetry reset and restore. Local audit files/database are not tamper-proof against the Windows account owner. Authentication success is represented by authenticated request actions, not by a separate identity-provider login lifecycle.

## Diagnostics and logging

IT diagnostics report application/backend version, SQL dialect/connectivity, record count, active imports, last successful import, uptime and running backend state. Copy or export JSON from Settings. No database connection URL or environment values are included. Frontend startup failures retain the existing native startup diagnostics. Backend application/access logs remain local JSON with rotation. Forwarding destinations are modeled as deployment intentions only; no Event Log/syslog/SIEM transmission occurs.

## Windows deployment, upgrade and updates

The release remains a Tauri NSIS x64 per-machine installer. Version comes from synchronized sources, including the VERSION file bundled with the backend, not from a renamed installer. Exit the desktop app before upgrading; protect a database backup first. Normal installer replacement should preserve the separate per-user data directory. Verify the running version and existing telemetry after installation. Run the 0.16.0 installer to use new code; source changes alone do not update an installed application.

NSIS supports silent installation with `/S` (case-sensitive); per-machine installation still requires elevation. For Intune, package the installer using the Win32 Content Prep Tool and configure system-context install/uninstall commands, architecture requirements and file-version detection for `ai-optimization-tool.exe`. MECM uses a similar application deployment/detection model. Validate uninstall commands against the generated installation's registration. See [Microsoft's Win32 deployment guidance](https://learn.microsoft.com/en-us/intune/app-management/deployment/add-win32) and [Tauri Windows installer documentation](https://v2.tauri.app/distribute/windows-installer/). MSI is a future separately validated `msi` bundle target; no MSI is delivered. winget requires published immutable URLs, checksums and a reviewed package manifest; no listing is claimed.

Existing signing scripts accept `WINDOWS_SIGNING_PFX_BASE64`, `WINDOWS_SIGNING_PFX_PASSWORD`, and `WINDOWS_SIGNING_TIMESTAMP_URL` from protected CI secrets. `AIOPT_REQUIRE_SIGNING=1` now makes missing inputs a hard failure. Sign the sidecar before desktop bundling. Authenticode signing credentials were not available for local builds, so artifacts remain unsigned development artifacts.

Automatic updating remains disabled. `scripts/prepare-updater-config.ps1 -Endpoint <real HTTPS base> -PublicKey <real public key> -Channel stable` generates an optional build overlay under `artifacts/updater`; preview is separate. This does not install an updater, download or execute anything, or establish production hosting. Before activating it, integrate Tauri's updater runtime, embed the trusted public key, supply the private signing key only in CI, publish signed artifacts/manifests at controlled endpoints, and test rejected/expired/wrong-key updates and rollback policy. [Tauri updater documentation](https://v2.tauri.app/plugin/updater/) explains detached signatures and endpoint configuration. Authenticode and updater signatures serve different checks and both need operational ownership.

## Readability and accessibility

All 14 inner pages share normalized font sizing: 16px body/inputs, 15px-or-larger labels/help/badges, 16px table cells, 22px section headings and 30–34px page headings. Font fallbacks work offline. Row spacing, sticky native headers, secondary text contrast, light-theme text, focus outlines and modal focus trapping are shared controls. Enterprise options use native expandable details and labeled forms. Automated page/viewport checks are evidence for these specific properties, not a complete WCAG conformance assessment.

See [0.16.0 validation report](RELEASE_0.16.0.md) for exact build/test results and remaining acceptance items.
