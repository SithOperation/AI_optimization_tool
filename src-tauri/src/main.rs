#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use serde::Serialize;
use std::{
    io::{Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager, RunEvent};

const ADDRESS: &str = "127.0.0.1:8000";

#[derive(Clone, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
enum StartupStatus {
    Starting,
    Healthy,
    Failed,
}

#[derive(Clone, Serialize)]
struct StartupFailure {
    category: String,
    summary: String,
    timestamp_unix: u64,
    backend_executable: String,
    bind_address: String,
    health_check: String,
    child_exit_code: Option<i32>,
    application_version: String,
}

#[derive(Serialize)]
struct StartupSnapshot {
    status: StartupStatus,
    failure: Option<StartupFailure>,
}

struct BackendRuntime {
    child: Option<Child>,
    status: StartupStatus,
    failure: Option<StartupFailure>,
}
struct Backend(Mutex<BackendRuntime>);

impl Backend {
    fn starting() -> Self {
        Self(Mutex::new(BackendRuntime {
            child: None,
            status: StartupStatus::Failed,
            failure: None,
        }))
    }
}

fn failure(
    category: &str,
    summary: &str,
    executable: &Path,
    health: &str,
    exit: Option<i32>,
) -> StartupFailure {
    StartupFailure {
        category: category.into(),
        summary: summary.into(),
        timestamp_unix: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
        backend_executable: executable.display().to_string(),
        bind_address: ADDRESS.into(),
        health_check: health.into(),
        child_exit_code: exit,
        application_version: env!("CARGO_PKG_VERSION").into(),
    }
}

fn backend_is_healthy() -> bool {
    let Ok(mut stream) =
        TcpStream::connect_timeout(&ADDRESS.parse().unwrap(), Duration::from_millis(500))
    else {
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

fn port_is_in_use() -> bool {
    TcpStream::connect_timeout(&ADDRESS.parse().unwrap(), Duration::from_millis(400)).is_ok()
}

fn development_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn backend_executable(app: &AppHandle) -> Result<PathBuf, StartupFailure> {
    if cfg!(debug_assertions) {
        let venv = development_root()
            .join(".venv")
            .join("Scripts")
            .join("python.exe");
        return Ok(if venv.is_file() {
            venv
        } else {
            PathBuf::from("python")
        });
    }
    let relative = PathBuf::from("binaries").join("aiopt-backend.exe");
    app.path()
        .resource_dir()
        .map(|path| path.join(&relative))
        .map_err(|_| {
            failure(
                "RESOURCE_PATH_UNAVAILABLE",
                "The application resource directory is unavailable.",
                &relative,
                "Health check was not attempted.",
                None,
            )
        })
}

fn terminate_backend(mut child: Child) {
    #[cfg(target_os = "windows")]
    let _ = Command::new("taskkill")
        .args(["/PID", &child.id().to_string(), "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    #[cfg(not(target_os = "windows"))]
    let _ = child.kill();
    let _ = child.wait();
}

fn wait_for_backend(
    child: &mut Child,
    executable: &Path,
    timeout: Duration,
) -> Result<(), StartupFailure> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        match child.try_wait() {
            Ok(Some(status)) => {
                return Err(failure(
                    "CHILD_EXITED",
                    "The local backend exited before it became ready.",
                    executable,
                    "Backend process exited before a healthy response.",
                    status.code(),
                ))
            }
            Err(_) => {
                return Err(failure(
                    "PROCESS_INSPECTION_FAILED",
                    "The local backend process could not be inspected.",
                    executable,
                    "Health readiness could not be confirmed.",
                    None,
                ))
            }
            Ok(None) => {}
        }
        if backend_is_healthy() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err(failure(
        "HEALTH_TIMEOUT",
        "The local backend did not become healthy before the startup timeout.",
        executable,
        "No healthy response within 30 seconds.",
        None,
    ))
}

fn attempt_backend_start(app: &AppHandle) -> Result<Child, StartupFailure> {
    let executable = backend_executable(app)?;
    if port_is_in_use() {
        return Err(failure(
            "PORT_IN_USE",
            "Port 8000 is already in use by another process.",
            &executable,
            if backend_is_healthy() {
                "An unowned healthy service responded; the application refused to attach."
            } else {
                "Another listener owns the configured port."
            },
            None,
        ));
    }
    if !cfg!(debug_assertions) && !executable.is_file() {
        return Err(failure(
            "EXECUTABLE_MISSING",
            "The packaged local backend executable is missing.",
            &executable,
            "Health check was not attempted.",
            None,
        ));
    }
    let mut command = if cfg!(debug_assertions) {
        let mut command = Command::new(&executable);
        command.current_dir(development_root()).args([
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
        command
    } else {
        Command::new(&executable)
    };
    let mut child = command
        .env("AIOPT_RUNTIME", "desktop")
        .env("NUMBA_THREADING_LAYER", "workqueue")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| {
            let category = match error.kind() {
                std::io::ErrorKind::PermissionDenied => "PERMISSION_DENIED",
                std::io::ErrorKind::NotFound => "EXECUTABLE_MISSING",
                _ => "LAUNCH_FAILED",
            };
            failure(
                category,
                "The local backend executable could not be launched.",
                &executable,
                "Health check was not attempted.",
                error.raw_os_error(),
            )
        })?;
    if let Err(error) = wait_for_backend(&mut child, &executable, Duration::from_secs(30)) {
        terminate_backend(child);
        return Err(error);
    }
    Ok(child)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn child_exit_is_reported_without_sensitive_data() {
        let executable = PathBuf::from("test-backend.exe");
        let mut child = Command::new("cmd")
            .args(["/C", "exit", "7"])
            .spawn()
            .expect("cmd should launch");
        let result = wait_for_backend(&mut child, &executable, Duration::from_secs(2))
            .expect_err("early exit must fail");
        assert_eq!(result.category, "CHILD_EXITED");
        assert_eq!(result.child_exit_code, Some(7));
        assert!(!result.summary.contains("environment"));
    }

    #[test]
    fn readiness_timeout_is_classified_and_process_can_be_cleaned_up() {
        let executable = PathBuf::from("test-backend.exe");
        let mut child = Command::new("powershell")
            .args(["-NoProfile", "-Command", "Start-Sleep -Seconds 2"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("PowerShell should launch");
        let result = wait_for_backend(&mut child, &executable, Duration::from_millis(10))
            .expect_err("unhealthy process must time out");
        assert_eq!(result.category, "HEALTH_TIMEOUT");
        terminate_backend(child);
    }
}

fn schedule_backend_start(app: AppHandle) {
    let previous = {
        let state = app.state::<Backend>();
        let Ok(mut runtime) = state.0.lock() else {
            return;
        };
        if matches!(runtime.status, StartupStatus::Starting) && runtime.failure.is_none() {
            return;
        }
        runtime.status = StartupStatus::Starting;
        runtime.failure = None;
        runtime.child.take()
    };
    if let Some(child) = previous {
        terminate_backend(child)
    }
    thread::spawn(move || {
        let result = attempt_backend_start(&app);
        let state = app.state::<Backend>();
        if let Ok(mut runtime) = state.0.lock() {
            match result {
                Ok(child) => {
                    runtime.child = Some(child);
                    runtime.status = StartupStatus::Healthy;
                    runtime.failure = None;
                }
                Err(error) => {
                    runtime.child = None;
                    runtime.status = StartupStatus::Failed;
                    runtime.failure = Some(error);
                }
            }
        };
    });
}

#[tauri::command]
fn startup_status(state: tauri::State<'_, Backend>) -> StartupSnapshot {
    let mut runtime = state.0.lock().expect("backend state lock poisoned");
    if matches!(runtime.status, StartupStatus::Healthy) {
        let exit = runtime
            .child
            .as_mut()
            .and_then(|child| child.try_wait().ok().flatten())
            .and_then(|status| status.code());
        if exit.is_some() {
            let executable = PathBuf::from("binaries").join("aiopt-backend.exe");
            runtime.child = None;
            runtime.status = StartupStatus::Failed;
            runtime.failure = Some(failure(
                "UNEXPECTED_BACKEND_EXIT",
                "The local backend stopped unexpectedly.",
                &executable,
                "The backend was previously healthy but is no longer running.",
                exit,
            ));
        }
    }
    StartupSnapshot {
        status: runtime.status.clone(),
        failure: runtime.failure.clone(),
    }
}

#[tauri::command]
fn retry_backend(app: AppHandle) -> Result<(), String> {
    let starting = matches!(
        app.state::<Backend>()
            .0
            .lock()
            .map_err(|_| "Backend state is unavailable")?
            .status,
        StartupStatus::Starting
    );
    if !starting {
        schedule_backend_start(app)
    }
    Ok(())
}

#[tauri::command]
fn open_logs() -> Result<String, String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .ok_or("The Windows local application-data directory is unavailable.")?;
    let logs = PathBuf::from(local).join("AIOptimizationTool").join("logs");
    std::fs::create_dir_all(&logs)
        .map_err(|_| "The application log directory could not be created.")?;
    Command::new("explorer.exe")
        .arg(&logs)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Windows File Explorer could not open the log directory.")?;
    Ok(logs.display().to_string())
}

#[tauri::command]
fn exit_application(app: AppHandle) {
    app.exit(0)
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .manage(Backend::starting())
        .invoke_handler(tauri::generate_handler![
            startup_status,
            retry_backend,
            open_logs,
            exit_application
        ])
        .setup(|app| {
            schedule_backend_start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build desktop application");
    app.run(|handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut runtime) = state.0.lock() {
                    if let Some(child) = runtime.child.take() {
                        terminate_backend(child)
                    }
                }
            }
        }
    });
}
