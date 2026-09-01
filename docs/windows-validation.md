# Windows validation

Use a disposable Windows VM or clean local profile whenever possible. Record Windows version, architecture, display scaling, commit, installer hash, and each result. Do not delete `%LOCALAPPDATA%\AIOptimizationTool` during upgrade/uninstall preservation tests.

## Install and first run

- Install the NSIS package and confirm product/version in Apps & Features and the Start Menu.
- Launch without repository Python, Node, or Docker processes. Confirm no console window appears.
- Confirm the backend listens only on `127.0.0.1:8000` and data is under `%LOCALAPPDATA%\AIOptimizationTool`.
- With a new data directory, verify the wizard, Demo Data path, identity/content defaults off, persisted completion, dashboard, and DEMO DATA label.

## Functional and UI pass

- Validate forecasting and Scenario Lab in the installed application.
- Switch Executive, Operations, and Engineering modes and restart after each persistence change.
- Inspect every navigation page at 1920x1080 and 1100x700, then at 100%, 125%, 150%, and 200% display scaling where available.
- Check overflow, clipping, grids, charts, labels, long model/provider/application/workload/team values, and right-side forms.

## Upgrade, uninstall, reinstall

1. Install the prior test build and create identifiable demo/configuration state.
2. Install the new package over it. Verify telemetry, configuration, setup state, mode, and database integrity.
3. Uninstall. Verify program files, Start Menu entry, Apps & Features entry, and application processes are removed while user data remains.
4. Reinstall. Verify compatible telemetry/configuration reappear and first-run state is not corrupted.

## Failures and cleanup

- Simulate backend startup failure, for example by holding port 8000 with an unrelated process, and verify a useful startup error and details instead of a blank or infinite loader.
- Retry after removing the condition.
- After normal close, first-run close, backend error, and uninstall, verify no owned application/backend process remains. Ignore unrelated Python, Node, Cargo, or Rust processes.

Current limitation: the fatal UI provides Retry and View Details, but Open Logs is not implemented.
