# 0.16.0 validation report

Release classification: **enterprise-ready foundation**, not a production multi-user enterprise platform. Validation date: September 5, 2026. See [enterprise architecture, gap analysis and operating guide](ENTERPRISE.md) for implemented controls and remaining blockers.

## Delivered behavior

- Local SQLite, offline analytics, local budgets/imports/reports and the existing desktop authentication/lifecycle remain available without paid API keys.
- Backend-enforced Viewer/Analyst/Administrator roles, vendor-neutral identity interface and fail-closed enterprise runtime. Local identity remains Administrator. No client role headers are trusted.
- Explicit, validated non-secret enterprise deployment configuration, separate from the active desktop connection. No fake remote API or SSO service is enabled.
- DATABASE_URL support, PostgreSQL-compatible date/hour SQL and ORM schema compilation; live PostgreSQL and migrations remain unvalidated.
- Versioned SQLite backup, integrity/schema validation, recovery snapshot, transactional rollback and audit preservation; GUI backup/restore actions.
- Administrator-enabled manual retention, affected-record preview and audited deletion. Unlimited/no automatic deletion remains the default.
- Windows Credential Manager save/replace/delete, fixed masks and environment reference compatibility. Secret values are excluded from database backup, diagnostics and audit responses.
- Startup, authentication-denial, semantic configuration/import/retention/reset/backup/credential events and authenticated request/export audit coverage. Local desktop lifecycle logging now uses JSON too.
- Paginated telemetry, Usage/Costs breakdowns with independent global totals, paginated Models, bounded rankings, streaming CSV and spreadsheet formula protection.
- Diagnostics with application/backend version, database connectivity/count, import state, last success, uptime and process state; GUI copy/export.
- Signing enforcement option, stable/preview updater configuration generator and Windows deployment documentation. Neither a hosted updater nor a production signing identity is fabricated.
- Shared typography, offline font fallbacks, clearer tables, improved secondary/disabled/placeholder text, visible focus and modal focus containment/restoration.

## Test counts

| Validation | Result |
| --- | --- |
| Backend suite, including existing 150k importer regression | **113 passed, 2 skipped**, 38.23 s |
| Dedicated 500k and 1m stress tests | **2 passed**, 306.04 s |
| JavaScript API base tests | **3 passed** |
| JavaScript API client/upload/error tests | **3 passed** |
| Rust/Tauri unit tests | **6 passed** |
| Playwright full matrix | **91 passed, 4 skipped**, approximately 1 minute |
| npm dependency audit | **0 vulnerabilities** |
| Version verification | All checked sources report **0.16.0** |
| Frontend, PyInstaller backend and NSIS desktop builds | Passed |

The two backend skips are the intentionally opt-in stress cases, run successfully in the separate stress invocation. Four UI skips avoid repeating a dedicated viewport-matrix test outside its primary project. The security subset has **14 passing tests**, including the 150k import; it is already included in the backend total, not an additional 14 tests. The 26 enterprise regression cases are also included in the backend total.

One earlier UI attempt failed because Vite watched an executable during backend packaging. Generated binaries, database and test artifacts were excluded from the watcher; the complete matrix was rerun successfully. No failing tests were removed. Existing audit assertions were updated to locate semantic events among newly added request audit events.

## Large-data results

These are final synthetic single-process API runs, not concurrent enterprise traffic. Fixtures have 20 applications and 5 models. A separate retained 150k regression fixture is 39,750,073 bytes; the generated benchmark fixture is 39,375,082 bytes. This rerun therefore proves roughly 40 MB, rather than claiming an exact 42 MB file.

| Measurement | 150,000 rows | 500,000 rows | 1,000,000 rows |
| --- | ---: | ---: | ---: |
| Fixture size, bytes | 39,375,082 | 131,250,082 | 262,500,082 |
| Upload, seconds | 0.189 | 0.681 | 3.045 |
| Analyze, seconds | 0.332 | 1.060 | 2.087 |
| Commit, seconds | 25.016 | 95.084 | 180.911 |
| Peak process working set, MiB | 286.69 | 309.41 | 357.71 |
| SQLite growth, MiB | 72.22 | 232.32 | 461.17 |
| Dashboard query, ms | 559.397 | 2,003.595 | 4,013.873 |
| Usage query, ms | 356.252 | 1,229.260 | 2,468.971 |
| Costs query, ms | 90.482 | 302.303 | 613.787 |
| Models query, ms | 255.599 | 837.540 | 1,656.476 |
| 100-record telemetry page, ms | 3.296 | 3.244 | 3.464 |
| Reset, seconds | 0.053 | 0.161 | 0.307 |

SQLite passed persistence/count/aggregation/reset checks at all sizes; it was not replaced. Query latency is material at one million rows and should inform future performance budgets. Memory is whole-process peak working set, including imported Python/statistical libraries and multipart upload buffers. Timings are single observations on a shared development machine; they are not p95 measurements or latency guarantees. The stress scripts leave isolated test data for investigation.

An empty database in the final 150k run measured dashboard 7.61 ms, Usage 4.35 ms, Costs 3.45 ms, Models 14.45 ms, and telemetry page 2.23 ms. Importing backend Python modules took 1.45 s and empty application lifespan initialization took 0.086 s. These measurements exclude browser rendering.

## Packaged validation

The actual PyInstaller executable passed authenticated loopback health, stale-token rejection, one-process ownership and version checks. Its API imported **150,000 rows in 25.444 seconds**, populated Usage/Costs/Models, loaded enterprise configuration and diagnostics, created and validated a backup, restored after reset, preserved audit records, and reset successfully again. Existing packaged forecast (7 points) and Scenario Lab checks passed too.

Native desktop checks passed clean launch, per-launch authenticated readiness, duplicate launch without a second backend, tray-off exit, tray-on background operation and duplicate launch reopening the tray window. Temporary lifecycle preferences were restored after each test. The tray menu's explicit Exit item was not automated; test cleanup terminated only the owned test binaries.

Fresh-process launch to authenticated backend readiness measured **7.970 s empty** in the performance run and **11.608 s empty** after the final clean rebuild, **4.448 s with 150k existing rows**, and **3.345 s with 500k existing rows**. Existing record counts were checked after startup. The 500k startup database was a disposable SQL replication of the proven synthetic 150k fixture; the separate 500k import benchmark used a full streamed CSV import. OS filesystem caches were not purged, so these timings are not comparable cold-boot benchmarks and the lower populated times do not imply larger databases start faster. Native renderer paint timing was not instrumented.

## Page-by-page readability evidence

All pages below passed rendered text/input/heading checks and navigation/overflow checks at 1920×1080, 1100×700, and 125%, 150%, 200% device scaling. The dedicated desktop matrix also checks 1600×900 and 1366×768. Body is at least 16px; visible inspected help/labels/buttons/table text is at least 14px (shared explicit sizes are normally 15–16px); inputs/selects are at least 16px and page headings at least 30px.

| Page | Readability/navigation result |
| --- | --- |
| Overview | Pass; shared metrics, headings and chart labels |
| Usage | Pass; paginated analytical table and totals |
| Costs | Pass; paginated analytical table and totals |
| Models | Pass; inventory/evaluation labels and bounded model pages |
| Forecasts | Pass; headings, results and chart labels |
| Optimization | Pass; recommendation text and values |
| Anomalies | Pass; status labels and descriptions |
| Budgets | Pass; forms, budget rows and status text |
| Import Data | Pass; upload controls, descriptions and history |
| Scenario Lab | Pass; inputs, labels and results |
| Reports | Pass; report text, metrics and actions |
| Integrations | Pass; connection labels and configuration forms |
| Settings | Pass; retention, enterprise, backups and diagnostics |
| Pricing | Pass; table headers/cells and pricing form |

Automated contrast checks pass the 4.5:1 threshold for secondary page descriptions, analytical headers and footer text in dark and light themes. Modal tests verify Tab/Shift+Tab containment and focus restoration after cancel. Enterprise settings use native details/summary, labeled inputs and status announcements. These checks do not constitute a full screen-reader audit or WCAG certification.

## Security compatibility and limitations

The preserved security regression suite covers loopback binding, per-launch authentication, restrictive CORS and preflight behavior, CSP, destructive-action authentication, chunk/body validation, traversal rejection and temporary-file cleanup. Backend tests cover rollback and large import persistence. New tests exercise roles, identity fail-closed behavior, ignored role headers, non-secret configuration validation, retention opt-in, checksum/version/archive rejection, restore rollback, audit preservation, credential masking/native deletion, diagnostics, pagination/global totals and export formula safety. PostgreSQL validation is SQL compilation only.

Remaining blockers for broad enterprise deployment: a real tested OIDC adapter, tenant/budget ownership isolation, supported server deployment and TLS ingress, live PostgreSQL/migration/recovery validation, concurrency/background importer work, externally protected audit forwarding, signing credentials and controlled update hosting. The Windows desktop remains local-first. No compliance certification is claimed.

Per-machine **install, upgrade, uninstall and reinstall were not executed**: this session is not elevated. Those operations and managed Intune/MECM deployment require acceptance on an elevated disposable Windows environment. Native binary launches and telemetry preservation are not substitutes for installer acceptance. MSI and winget delivery remain documented future paths.

## Release artifacts and repository status

- Packaged backend API version: **0.16.0**.
- Desktop executable Windows file/product version: **0.16.0**.
- Installer: `src-tauri/target/release/bundle/nsis/AI Optimization Tool_0.16.0_x64-setup.exe`.
- Artifacts are unsigned development builds because Authenticode credentials were not supplied. A checksum is generated separately; it does not replace a signature.
- Existing installed copies require running the new installer to receive this release. Back up local data and exit the app before upgrading.
- Release destination: **https://github.com/SithOperation/Tokenscope**, branch `main`. The original `AI_optimization_tool` remote and history remain untouched. Publication uses a separate checkout; the release commit is identified by `feat: enterprise readiness foundation for 0.16.0`.

Machine-readable benchmark evidence is in `docs/validation/0.16.0/`. Local build/test logs and generated artifacts are retained under `.test-data/` and `artifacts/` (ignored by Git). The final delivery records the destination commit and verified push result.
