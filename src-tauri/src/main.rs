#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{
    io::{Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

fn backend_is_healthy() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().expect("valid backend address"),
        Duration::from_millis(500),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(750)));
    if stream
        .write_all(b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.starts_with("HTTP/1.1 200")
        && response.contains("\"status\":\"healthy\"")
}

fn wait_for_backend(child: &mut Child, timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("could not inspect backend process: {error}"))?
        {
            return Err(format!("backend exited before becoming healthy: {status}"));
        }
        if backend_is_healthy() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err(format!(
        "backend did not become healthy within {} seconds",
        timeout.as_secs()
    ))
}

fn development_python() -> PathBuf {
    let venv = development_root()
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    if venv.is_file() {
        venv
    } else {
        PathBuf::from("python")
    }
}

fn development_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must be inside the repository root")
        .to_path_buf()
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .setup(|app| {
            if backend_is_healthy() {
                return Err(
                    "port 8000 is already serving an API; refusing to attach to an unowned backend"
                        .into(),
                );
            }
            let resource = app.path().resource_dir()?;
            let mut backend = if cfg!(debug_assertions) {
                let mut cmd = Command::new(development_python());
                cmd.current_dir(development_root());
                cmd.args([
                    "-m",
                    "uvicorn",
                    "tokenscope_api.main:app",
                    "--app-dir",
                    "apps/api",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ]);
                cmd
            } else {
                Command::new(resource.join("binaries").join("aiopt-backend.exe"))
            };
            let mut child = backend
                .env("AIOPT_RUNTIME", "desktop")
                .env("NUMBA_THREADING_LAYER", "workqueue")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?;
            if let Err(error) = wait_for_backend(&mut child, Duration::from_secs(30)) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error.into());
            }
            app.manage(Backend(Mutex::new(Some(child))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build desktop application");
    app.run(|handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
