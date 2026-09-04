# Desktop architecture

Tauri 2 wraps the existing Vite frontend and starts FastAPI as a child process. This is the least disruptive compatible architecture: working Python analytics remain Python. A single-instance plugin focuses the existing window. Release builds suppress the console and terminate/wait for the owned backend during exit.

Development uses Python plus Vite. Production uses a PyInstaller one-directory backend placed at `src-tauri/binaries/aiopt-backend/`; end users need no Python, Node, Git, or Docker. One-directory packaging keeps one visible backend process per desktop launch and avoids the launcher/worker pair created by PyInstaller one-file mode. `scripts/package-backend.ps1` performs that build and collects StatsForecast assets.

The Rust shell polls FastAPI health with the per-launch token for up to 30 seconds, detects early backend exit, and does not finish native setup until the owned API proves it has the same token. Automated packaged-backend smoke tests cover authenticated health, forecasting, Scenario Lab, loopback binding, database initialization, and cleanup. Production still needs an approved final brand asset, Authenticode signing, and diagnostics export/open-logs UI.

StatsForecast uses Numba's bundled `workqueue` threading layer in packaged builds. The optional `tbbpool` module is excluded because its external `tbb12.dll` runtime is not otherwise required; packaged forecast smoke tests cover this choice.

The frontend contains no remotely hosted runtime scripts, CSS, fonts, icons, or analytics. It uses system font fallbacks and remains usable offline. The Tauri content security policy allows only bundled styles/fonts and the loopback API.
