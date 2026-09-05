#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    io::{Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU32, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent, WindowEvent,
};

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
struct Backend {
    runtime: Mutex<BackendRuntime>,
    owned_pid: AtomicU32,
    shutting_down: AtomicBool,
}

impl Backend {
    fn starting() -> Self {
        Self {
            runtime: Mutex::new(BackendRuntime {
                child: None,
                status: StartupStatus::Failed,
                failure: None,
            }),
            owned_pid: AtomicU32::new(0),
            shutting_down: AtomicBool::new(false),
        }
    }
}

fn should_start_backend(status: &StartupStatus) -> bool {
    matches!(status, StartupStatus::Failed)
}

#[derive(Default, Deserialize, Serialize)]
struct LifecyclePreferences {
    keep_running_in_tray: bool,
}

struct Lifecycle(Mutex<LifecyclePreferences>);
struct BackendSession {
    launch_id: String,
    token: String,
    token_fingerprint: String,
}

fn token_fingerprint(token: &str) -> String {
    format!("{:x}", Sha256::digest(token.as_bytes()))[..12].to_string()
}

fn lifecycle_log(app: &AppHandle, message: &str) {
    let Ok(directory) = app.path().app_log_dir() else {
        return;
    };
    if std::fs::create_dir_all(&directory).is_err() {
        return;
    }
    let path = directory.join("desktop-lifecycle.log");
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let record = serde_json::json!({"timestamp_unix": timestamp, "level": "INFO", "component": "desktop.lifecycle", "message": message});
        let _ = writeln!(file, "{record}");
    }
}

fn preferences_path(app: &AppHandle) -> Option<PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|path| path.join("lifecycle.json"))
}

fn load_preferences(app: &AppHandle) -> LifecyclePreferences {
    preferences_path(app)
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|json| serde_json::from_str(&json).ok())
        .unwrap_or_default()
}

fn save_preferences(app: &AppHandle, preferences: &LifecyclePreferences) -> Result<(), String> {
    let path = preferences_path(app).ok_or("Application settings directory is unavailable")?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let json = serde_json::to_string_pretty(preferences).map_err(|error| error.to_string())?;
    std::fs::write(path, json).map_err(|error| error.to_string())
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

fn backend_is_healthy(token: &str) -> bool {
    let Ok(mut stream) =
        TcpStream::connect_timeout(&ADDRESS.parse().unwrap(), Duration::from_millis(500))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(750)));
    if stream
        .write_all(format!("GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\nX-TokenScope-Key: {token}\r\nConnection: close\r\n\r\n").as_bytes())
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
    let relative = PathBuf::from("binaries")
        .join("aiopt-backend")
        .join("aiopt-backend.exe");
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

#[cfg(target_os = "windows")]
fn terminate_pid(pid: u32) {
    if pid == 0 {
        return;
    }
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(not(target_os = "windows"))]
fn terminate_pid(_pid: u32) {}

fn shutdown_owned_backend(app: &AppHandle) {
    let Some(state) = app.try_state::<Backend>() else {
        return;
    };
    state.shutting_down.store(true, Ordering::SeqCst);
    let child = state
        .runtime
        .lock()
        .ok()
        .and_then(|mut runtime| runtime.child.take());
    if let Some(child) = child {
        state.owned_pid.store(0, Ordering::SeqCst);
        terminate_backend(child);
    } else {
        terminate_pid(state.owned_pid.swap(0, Ordering::SeqCst));
    }
}

fn wait_for_backend(
    child: &mut Child,
    executable: &Path,
    token: &str,
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
        if backend_is_healthy(token) {
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
            "Another listener owns the configured port; the application refused to attach.",
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
    let session = app.state::<BackendSession>();
    lifecycle_log(
        app,
        &format!(
            "spawn requested launch={} token={}",
            session.launch_id, session.token_fingerprint
        ),
    );
    let mut child = command
        .env("AIOPT_RUNTIME", "desktop")
        .env("AIOPT_DESKTOP_TOKEN", &session.token)
        .env("AIOPT_DESKTOP_LAUNCH_ID", &session.launch_id)
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
    lifecycle_log(
        app,
        &format!(
            "backend spawned pid={} launch={} token={}",
            child.id(),
            session.launch_id,
            session.token_fingerprint
        ),
    );
    let backend = app.state::<Backend>();
    backend.owned_pid.store(child.id(), Ordering::SeqCst);
    if backend.shutting_down.load(Ordering::SeqCst) {
        backend.owned_pid.store(0, Ordering::SeqCst);
        terminate_backend(child);
        return Err(failure(
            "APPLICATION_EXITING",
            "The application exited while the local backend was starting.",
            &executable,
            "Startup was cancelled.",
            None,
        ));
    }
    if let Err(error) = wait_for_backend(
        &mut child,
        &executable,
        &session.token,
        Duration::from_secs(30),
    ) {
        backend.owned_pid.store(0, Ordering::SeqCst);
        terminate_backend(child);
        lifecycle_log(
            app,
            &format!(
                "backend startup failed and child terminated launch={} token={} category={}",
                session.launch_id, session.token_fingerprint, error.category
            ),
        );
        return Err(error);
    }
    lifecycle_log(
        app,
        &format!(
            "authenticated readiness passed pid={} launch={} token={}",
            child.id(),
            session.launch_id,
            session.token_fingerprint
        ),
    );
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
        let result = wait_for_backend(
            &mut child,
            &executable,
            "test-token",
            Duration::from_secs(2),
        )
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
        let result = wait_for_backend(
            &mut child,
            &executable,
            "test-token",
            Duration::from_millis(10),
        )
        .expect_err("unhealthy process must time out");
        assert_eq!(result.category, "HEALTH_TIMEOUT");
        terminate_backend(child);
    }

    #[test]
    fn tray_mode_is_opt_in() {
        assert!(!LifecyclePreferences::default().keep_running_in_tray);
    }

    #[test]
    fn lifecycle_preferences_round_trip() {
        let json = serde_json::to_string(&LifecyclePreferences {
            keep_running_in_tray: true,
        })
        .expect("preferences should serialize");
        let restored: LifecyclePreferences =
            serde_json::from_str(&json).expect("preferences should deserialize");
        assert!(restored.keep_running_in_tray);
    }

    #[test]
    fn only_failed_state_can_create_a_backend() {
        assert!(should_start_backend(&StartupStatus::Failed));
        assert!(!should_start_backend(&StartupStatus::Starting));
        assert!(!should_start_backend(&StartupStatus::Healthy));
    }

    #[test]
    fn token_fingerprint_is_stable_and_does_not_expose_token() {
        let token = "launch-secret-value";
        let fingerprint = token_fingerprint(token);
        assert_eq!(fingerprint, token_fingerprint(token));
        assert_eq!(fingerprint.len(), 12);
        assert!(!fingerprint.contains(token));
    }
}

fn schedule_backend_start(app: AppHandle) {
    let backend = app.state::<Backend>();
    backend.shutting_down.store(false, Ordering::SeqCst);
    let previous = {
        let Ok(mut runtime) = backend.runtime.lock() else {
            return;
        };
        if !should_start_backend(&runtime.status) {
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
        if let Ok(mut runtime) = state.runtime.lock() {
            match result {
                Ok(child) => {
                    if state.shutting_down.load(Ordering::SeqCst) {
                        state.owned_pid.store(0, Ordering::SeqCst);
                        terminate_backend(child);
                    } else {
                        runtime.child = Some(child);
                        runtime.status = StartupStatus::Healthy;
                        runtime.failure = None;
                    }
                }
                Err(error) => {
                    state.owned_pid.store(0, Ordering::SeqCst);
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
    let mut runtime = state.runtime.lock().expect("backend state lock poisoned");
    if matches!(runtime.status, StartupStatus::Healthy) {
        let exit = runtime
            .child
            .as_mut()
            .and_then(|child| child.try_wait().ok().flatten())
            .and_then(|status| status.code());
        if exit.is_some() {
            state.owned_pid.store(0, Ordering::SeqCst);
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
    let failed = should_start_backend(
        &app.state::<Backend>()
            .runtime
            .lock()
            .map_err(|_| "Backend state is unavailable")?
            .status,
    );
    if failed {
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
    shutdown_owned_backend(&app);
    app.exit(0)
}

#[tauri::command]
fn get_keep_running_in_tray(state: tauri::State<'_, Lifecycle>) -> bool {
    state
        .0
        .lock()
        .map(|value| value.keep_running_in_tray)
        .unwrap_or(false)
}

#[tauri::command]
fn set_keep_running_in_tray(
    app: AppHandle,
    state: tauri::State<'_, Lifecycle>,
    enabled: bool,
) -> Result<(), String> {
    let mut preferences = state
        .0
        .lock()
        .map_err(|_| "Lifecycle settings are unavailable")?;
    preferences.keep_running_in_tray = enabled;
    save_preferences(&app, &preferences)
}

#[tauri::command]
fn backend_auth_token(state: tauri::State<'_, BackendSession>) -> String {
    state.token.clone()
}

fn restore_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn main() {
    let token = uuid::Uuid::new_v4().to_string();
    let session = BackendSession {
        launch_id: uuid::Uuid::new_v4().to_string(),
        token_fingerprint: token_fingerprint(&token),
        token,
    };
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            restore_main_window(app);
        }))
        .manage(Backend::starting())
        .manage(session)
        .invoke_handler(tauri::generate_handler![
            startup_status,
            retry_backend,
            open_logs,
            exit_application,
            get_keep_running_in_tray,
            set_keep_running_in_tray,
            backend_auth_token
        ])
        .setup(|app| {
            app.manage(Lifecycle(Mutex::new(load_preferences(app.handle()))));
            let open =
                MenuItem::with_id(app, "open", "Open AI Optimization Tool", true, None::<&str>)?;
            let exit = MenuItem::with_id(app, "exit", "Exit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &exit])?;
            let mut tray = TrayIconBuilder::with_id("main-tray")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => restore_main_window(app),
                    "exit" => {
                        shutdown_owned_backend(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::DoubleClick { .. } = event {
                        restore_main_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon().cloned() {
                tray = tray.icon(icon);
            }
            tray.build(app)?;
            schedule_backend_start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build desktop application");
    app.run(|handle, event| match event {
        RunEvent::WindowEvent {
            label,
            event: WindowEvent::CloseRequested { api, .. },
            ..
        } if label == "main" => {
            let keep_running = handle
                .try_state::<Lifecycle>()
                .and_then(|state| state.0.lock().ok().map(|value| value.keep_running_in_tray))
                .unwrap_or(false);
            if keep_running {
                api.prevent_close();
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.hide();
                }
            } else {
                shutdown_owned_backend(handle);
                handle.exit(0);
            }
        }
        RunEvent::ExitRequested { .. } | RunEvent::Exit => shutdown_owned_backend(handle),
        _ => {}
    });
}
