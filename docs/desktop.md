# Desktop architecture

Tauri 2 wraps the existing Vite frontend and starts FastAPI as a child process. This is the least disruptive compatible architecture: working Python analytics remain Python. A single-instance plugin focuses the existing window. Release builds suppress the console and terminate/wait for the owned backend during exit.

Development uses Python plus Vite. Production uses a real PyInstaller one-file backend placed at `src-tauri/binaries/aiopt-backend.exe`; end users need no Python, Node, Git, or Docker. `scripts/package-backend.ps1` performs that build and collects StatsForecast assets.

The Rust shell polls the checked FastAPI health endpoint for up to 30 seconds, detects early backend exit, and does not finish native setup until the API reports healthy. Production still needs finalized icons, certificate signing, and diagnostics export.

StatsForecast uses Numba's bundled `workqueue` threading layer in packaged builds. The optional `tbbpool` module is excluded because its external `tbb12.dll` runtime is not otherwise required; packaged forecast smoke tests cover this choice.
