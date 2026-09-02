use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_opener::OpenerExt;

const BACKEND_HOST: &str = "127.0.0.1";
const LEGACY_BACKEND_PORT: u16 = 1042;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(20);
const STARTUP_POLL_INTERVAL: Duration = Duration::from_millis(250);
const MAX_PORT_ATTEMPTS: usize = 3;
const HANDSHAKE_PATH: &str = "/.well-known/aetherdb-desktop";
const IDENTITY_MARKER: &str = "\"product\":\"AetherDB\"";
const BUILD_ID: &str = match option_env!("AETHERDB_BUILD_ID") {
    Some(value) => value,
    None => concat!("dev-", env!("CARGO_PKG_VERSION")),
};

#[derive(Clone)]
struct BackendEndpoint {
    port: u16,
    handshake: String,
    owner_token: String,
    instance_id: String,
}

impl BackendEndpoint {
    fn create() -> Result<Self, BackendFailure> {
        let runtime_identity = generate_random_hex("runtime instance identity")?;
        Ok(Self {
            port: 0,
            handshake: generate_random_hex("desktop handshake")?,
            owner_token: format!("aether_owner_{}", generate_random_hex("owner token")?),
            instance_id: format!("aether_runtime_{}", &runtime_identity[..32]),
        })
    }

    fn address(&self) -> SocketAddr {
        SocketAddr::from(([127, 0, 0, 1], self.port))
    }

    fn base_url(&self) -> String {
        format!("http://{BACKEND_HOST}:{}", self.port)
    }
}

struct ManagedBackend {
    child: Child,
    endpoint: BackendEndpoint,
    started_at: u64,
    log_path: PathBuf,
    descriptor_path: PathBuf,
    legacy_port_status: &'static str,
}

#[derive(Default)]
struct BackendState {
    process: Option<ManagedBackend>,
    last_error: Option<BackendFailure>,
    last_exit_code: Option<i32>,
    log_path: Option<PathBuf>,
}

#[derive(Clone, Default)]
struct BackendManager {
    state: Arc<Mutex<BackendState>>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendFailure {
    code: String,
    message: String,
    reason: String,
    port: Option<u16>,
    exit_code: Option<i32>,
    log_path: Option<String>,
}

impl BackendFailure {
    fn new(code: &str, message: &str, reason: String) -> Self {
        Self {
            code: code.to_string(),
            message: message.to_string(),
            reason,
            port: None,
            exit_code: None,
            log_path: None,
        }
    }

    fn with_process(mut self, port: u16, exit_code: Option<i32>, log_path: &Path) -> Self {
        self.port = Some(port);
        self.exit_code = exit_code;
        self.log_path = Some(log_path.display().to_string());
        self
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendStatus {
    available: bool,
    managed: bool,
    phase: &'static str,
    base_url: Option<String>,
    port: Option<u16>,
    pid: Option<u32>,
    owner_token: Option<String>,
    instance_id: Option<String>,
    backend_version: Option<String>,
    build_id: Option<String>,
    database_ready: bool,
    started_at: Option<u64>,
    exit_code: Option<i32>,
    error: Option<BackendFailure>,
    log_path: Option<String>,
    legacy_port: u16,
    legacy_port_status: &'static str,
    protocol_version: &'static str,
    transport: &'static str,
}

impl BackendStatus {
    fn unavailable(state: &BackendState) -> Self {
        Self {
            available: false,
            managed: false,
            phase: "stopped",
            base_url: None,
            port: None,
            pid: None,
            owner_token: None,
            instance_id: None,
            backend_version: None,
            build_id: None,
            database_ready: false,
            started_at: None,
            exit_code: state.last_exit_code,
            error: state.last_error.clone(),
            log_path: state
                .log_path
                .as_ref()
                .map(|path| path.display().to_string()),
            legacy_port: LEGACY_BACKEND_PORT,
            legacy_port_status: inspect_legacy_port(),
            protocol_version: "1.0",
            transport: "dynamic_loopback",
        }
    }

    fn running(managed: &ManagedBackend, available: bool) -> Self {
        let error = (!available).then(|| {
            BackendFailure::new(
                "BACKEND_UNAVAILABLE",
                "The local AetherDB service is not responding.",
                "The managed backend process is running but its identity health check failed."
                    .to_string(),
            )
            .with_process(managed.endpoint.port, None, &managed.log_path)
        });
        Self {
            available,
            managed: true,
            phase: if available { "ready" } else { "unavailable" },
            base_url: Some(managed.endpoint.base_url()),
            port: Some(managed.endpoint.port),
            pid: Some(managed.child.id()),
            owner_token: Some(managed.endpoint.owner_token.clone()),
            instance_id: Some(managed.endpoint.instance_id.clone()),
            backend_version: available.then(|| env!("CARGO_PKG_VERSION").to_string()),
            build_id: available.then(|| BUILD_ID.to_string()),
            database_ready: available,
            started_at: Some(managed.started_at),
            exit_code: None,
            error,
            log_path: Some(managed.log_path.display().to_string()),
            legacy_port: LEGACY_BACKEND_PORT,
            legacy_port_status: managed.legacy_port_status,
            protocol_version: "1.0",
            transport: "dynamic_loopback",
        }
    }
}

impl BackendManager {
    fn start(&self, app: &AppHandle) -> Result<BackendStatus, BackendFailure> {
        let mut state = self.state.lock().map_err(|_| {
            BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not inspect the backend process.",
                "Backend process lock is poisoned.".to_string(),
            )
        })?;

        if let Some(mut managed) = state.process.take() {
            match managed.child.try_wait() {
                Ok(None) if backend_handshake_matches(&managed.endpoint) => {
                    let status = BackendStatus::running(&managed, true);
                    state.process = Some(managed);
                    return Ok(status);
                }
                Ok(None) => stop_managed_backend(&mut managed),
                Ok(Some(exit_status)) => {
                    state.last_exit_code = exit_status.code();
                    remove_runtime_descriptor(&managed.descriptor_path);
                }
                Err(error) => {
                    let failure = BackendFailure::new(
                        "BACKEND_START_FAILED",
                        "AetherDB could not inspect the existing backend process.",
                        error.to_string(),
                    );
                    state.last_error = Some(failure.clone());
                    return Err(failure);
                }
            }
        }

        state.last_error = None;
        state.last_exit_code = None;
        let deadline = Instant::now() + STARTUP_TIMEOUT;

        for attempt in 1..=MAX_PORT_ATTEMPTS {
            if Instant::now() >= deadline {
                break;
            }
            let mut endpoint = BackendEndpoint::create()?;
            let legacy_port_status = inspect_legacy_port();
            let paths = desktop_runtime_paths(app)?;
            let log_path = paths.log_dir.join("backend.log");
            let descriptor_path = paths.runtime_dir.join("backend-runtime.json");
            let startup_descriptor_path = paths
                .runtime_dir
                .join(format!("backend-startup-{}.json", endpoint.instance_id));
            remove_runtime_descriptor(&descriptor_path);
            remove_runtime_descriptor(&startup_descriptor_path);
            state.log_path = Some(log_path.clone());
            append_launcher_log(
                &paths.launcher_log,
                &format!(
                    "starting backend attempt={attempt} port=system transport=sidecar_owned_socket build_id={BUILD_ID}"
                ),
            );
            let (stdout, stderr) = open_backend_log_handles(&log_path)?;
            let mut child = build_backend_command(app, &endpoint, &startup_descriptor_path)?
                .stdout(Stdio::from(stdout))
                .stderr(Stdio::from(stderr))
                .spawn()
                .map_err(|error| {
                    BackendFailure::new(
                        "BACKEND_START_FAILED",
                        "AetherDB could not start its local backend service.",
                        error.to_string(),
                    )
                    .with_process(endpoint.port, None, &log_path)
                })?;
            let started_at = unix_timestamp();
            append_launcher_log(
                &paths.launcher_log,
                &format!(
                    "backend spawned pid={} awaiting_port_descriptor",
                    child.id()
                ),
            );

            loop {
                if Instant::now() >= deadline {
                    remove_runtime_descriptor(&startup_descriptor_path);
                    let mut managed = ManagedBackend {
                        child,
                        endpoint,
                        started_at,
                        log_path,
                        descriptor_path,
                        legacy_port_status,
                    };
                    stop_managed_backend(&mut managed);
                    let failure = BackendFailure::new(
                        "BACKEND_TIMEOUT",
                        "The local AetherDB service did not become ready in time.",
                        format!(
                            "Identity health check did not pass within {} seconds.",
                            STARTUP_TIMEOUT.as_secs()
                        ),
                    )
                    .with_process(
                        managed.endpoint.port,
                        managed
                            .child
                            .try_wait()
                            .ok()
                            .flatten()
                            .and_then(|value| value.code()),
                        &managed.log_path,
                    );
                    append_launcher_log(
                        &paths.launcher_log,
                        &format!(
                            "backend timeout port={} code={}",
                            managed.endpoint.port, failure.code
                        ),
                    );
                    state.last_error = Some(failure.clone());
                    return Err(failure);
                }

                if endpoint.port == 0 {
                    match read_startup_descriptor(&startup_descriptor_path, &endpoint, child.id()) {
                        Ok(Some(port)) => {
                            endpoint.port = port;
                            remove_runtime_descriptor(&startup_descriptor_path);
                            append_launcher_log(
                                &paths.launcher_log,
                                &format!(
                                    "backend reported sidecar_owned_port={} pid={} build_id={BUILD_ID}",
                                    endpoint.port,
                                    child.id()
                                ),
                            );
                        }
                        Ok(None) => {}
                        Err(failure) => {
                            let mut managed = ManagedBackend {
                                child,
                                endpoint,
                                started_at,
                                log_path,
                                descriptor_path,
                                legacy_port_status,
                            };
                            stop_managed_backend(&mut managed);
                            remove_runtime_descriptor(&startup_descriptor_path);
                            state.last_error = Some(failure.clone());
                            return Err(failure);
                        }
                    }
                }

                match child.try_wait() {
                    Ok(Some(exit_status)) => {
                        remove_runtime_descriptor(&startup_descriptor_path);
                        let failure = classify_start_failure(&log_path, endpoint.port, exit_status);
                        append_launcher_log(
                            &paths.launcher_log,
                            &format!(
                                "backend exited port={} exit_code={:?} code={}",
                                endpoint.port,
                                exit_status.code(),
                                failure.code
                            ),
                        );
                        state.last_exit_code = exit_status.code();
                        state.last_error = Some(failure.clone());
                        if failure.code == "BACKEND_PORT_IN_USE" && attempt < MAX_PORT_ATTEMPTS {
                            break;
                        }
                        return Err(failure);
                    }
                    Ok(None) if endpoint.port != 0 && backend_handshake_matches(&endpoint) => {
                        remove_runtime_descriptor(&startup_descriptor_path);
                        let managed = ManagedBackend {
                            child,
                            endpoint,
                            started_at,
                            log_path,
                            descriptor_path,
                            legacy_port_status,
                        };
                        if let Err(failure) = write_runtime_descriptor(&managed) {
                            let mut failed = managed;
                            stop_managed_backend(&mut failed);
                            state.last_error = Some(failure.clone());
                            return Err(failure);
                        }
                        append_launcher_log(
                            &paths.launcher_log,
                            &format!(
                                "backend ready pid={} port={} startup_ms={}",
                                managed.child.id(),
                                managed.endpoint.port,
                                STARTUP_TIMEOUT
                                    .saturating_sub(
                                        deadline.saturating_duration_since(Instant::now())
                                    )
                                    .as_millis()
                            ),
                        );
                        let status = BackendStatus::running(&managed, true);
                        state.process = Some(managed);
                        state.last_error = None;
                        return Ok(status);
                    }
                    Ok(None) => std::thread::sleep(STARTUP_POLL_INTERVAL),
                    Err(error) => {
                        let mut managed = ManagedBackend {
                            child,
                            endpoint,
                            started_at,
                            log_path,
                            descriptor_path,
                            legacy_port_status,
                        };
                        stop_managed_backend(&mut managed);
                        let failure = BackendFailure::new(
                            "BACKEND_START_FAILED",
                            "AetherDB could not monitor its backend process.",
                            error.to_string(),
                        )
                        .with_process(
                            managed.endpoint.port,
                            None,
                            &managed.log_path,
                        );
                        state.last_error = Some(failure.clone());
                        return Err(failure);
                    }
                }
            }
        }

        let failure = state.last_error.clone().unwrap_or_else(|| {
            BackendFailure::new(
                "BACKEND_TIMEOUT",
                "The local AetherDB service did not become ready in time.",
                "No backend startup attempt completed before the deadline.".to_string(),
            )
        });
        Err(failure)
    }

    fn stop(&self) {
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        if let Some(mut managed) = state.process.take() {
            stop_managed_backend(&mut managed);
        }
    }

    fn status(&self) -> Result<BackendStatus, BackendFailure> {
        let mut state = self.state.lock().map_err(|_| {
            BackendFailure::new(
                "BACKEND_UNAVAILABLE",
                "AetherDB could not inspect the local backend service.",
                "Backend process lock is poisoned.".to_string(),
            )
        })?;

        if let Some(mut managed) = state.process.take() {
            match managed.child.try_wait() {
                Ok(None) => {
                    let available = backend_handshake_matches(&managed.endpoint);
                    let status = BackendStatus::running(&managed, available);
                    state.process = Some(managed);
                    return Ok(status);
                }
                Ok(Some(exit_status)) => {
                    let failure = classify_runtime_failure(
                        &managed.log_path,
                        managed.endpoint.port,
                        exit_status,
                    );
                    remove_runtime_descriptor(&managed.descriptor_path);
                    state.last_exit_code = exit_status.code();
                    state.last_error = Some(failure);
                }
                Err(error) => {
                    let failure = BackendFailure::new(
                        "BACKEND_UNAVAILABLE",
                        "AetherDB could not inspect the local backend service.",
                        error.to_string(),
                    );
                    state.last_error = Some(failure.clone());
                    state.process = Some(managed);
                    return Err(failure);
                }
            }
        }

        Ok(BackendStatus::unavailable(&state))
    }
}

struct DesktopRuntimePaths {
    runtime_dir: PathBuf,
    log_dir: PathBuf,
    launcher_log: PathBuf,
}

#[derive(Deserialize)]
struct StartupDescriptor {
    protocol_version: String,
    service: String,
    pid: u32,
    port: u16,
    instance_id: String,
    build_id: String,
}

fn desktop_runtime_root(app: &AppHandle) -> Result<PathBuf, BackendFailure> {
    if let Some(configured) = std::env::var_os("AETHERDB_DESKTOP_RUNTIME_ROOT") {
        let path = PathBuf::from(configured);
        if !path.is_absolute() {
            return Err(BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB received an invalid desktop runtime directory.",
                "AETHERDB_DESKTOP_RUNTIME_ROOT must be an absolute path.".to_string(),
            ));
        }
        return Ok(path);
    }
    app.path().app_data_dir().map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not resolve its writable data directory.",
            error.to_string(),
        )
    })
}

fn read_startup_descriptor(
    path: &Path,
    endpoint: &BackendEndpoint,
    expected_pid: u32,
) -> Result<Option<u16>, BackendFailure> {
    let payload = match std::fs::read(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not read the backend startup descriptor.",
                error.to_string(),
            ))
        }
    };
    let descriptor: StartupDescriptor = serde_json::from_slice(&payload).map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB received an invalid backend startup descriptor.",
            error.to_string(),
        )
    })?;
    if descriptor.build_id != BUILD_ID {
        return Err(BackendFailure::new(
            "BACKEND_BUILD_MISMATCH",
            "The packaged AetherDB components were built from different releases.",
            format!(
                "Desktop build {} does not match backend build {}.",
                BUILD_ID, descriptor.build_id
            ),
        ));
    }
    let pid_matches = descriptor.pid == expected_pid || cfg!(debug_assertions);
    if descriptor.protocol_version != "1.0"
        || descriptor.service != "aetherdb-backend"
        || !pid_matches
        || descriptor.instance_id != endpoint.instance_id
        || descriptor.port == 0
    {
        return Err(BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not verify the backend startup descriptor.",
            "The sidecar identity, process, protocol, or port did not match.".to_string(),
        ));
    }
    Ok(Some(descriptor.port))
}

fn desktop_runtime_paths(app: &AppHandle) -> Result<DesktopRuntimePaths, BackendFailure> {
    let runtime_dir = desktop_runtime_root(app)?;
    let log_dir = runtime_dir.join("logs");
    std::fs::create_dir_all(&log_dir).map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not create its local log directory.",
            error.to_string(),
        )
    })?;
    Ok(DesktopRuntimePaths {
        runtime_dir,
        launcher_log: log_dir.join("launcher.log"),
        log_dir,
    })
}

fn open_backend_log_handles(path: &Path) -> Result<(File, File), BackendFailure> {
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|error| {
            BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not open its backend log.",
                error.to_string(),
            )
        })?;
    let stderr = file.try_clone().map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not prepare backend error logging.",
            error.to_string(),
        )
    })?;
    Ok((file, stderr))
}

fn append_launcher_log(path: &Path, message: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{} {}", unix_timestamp(), message);
    }
}

fn write_runtime_descriptor(managed: &ManagedBackend) -> Result<(), BackendFailure> {
    let payload = serde_json::json!({
        "pid": managed.child.id(),
        "port": managed.endpoint.port,
        "instance_id": managed.endpoint.instance_id,
        "started_at": managed.started_at,
        "backend_version": env!("CARGO_PKG_VERSION"),
        "build_id": BUILD_ID,
    });
    let temporary = managed.descriptor_path.with_extension("json.tmp");
    std::fs::write(
        &temporary,
        serde_json::to_vec_pretty(&payload).expect("serializing a static runtime descriptor"),
    )
    .and_then(|_| std::fs::rename(&temporary, &managed.descriptor_path))
    .map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not publish its runtime descriptor.",
            error.to_string(),
        )
        .with_process(managed.endpoint.port, None, &managed.log_path)
    })
}

fn remove_runtime_descriptor(path: &Path) {
    match std::fs::remove_file(path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => {}
    }
}

fn stop_managed_backend(managed: &mut ManagedBackend) {
    if managed.child.try_wait().ok().flatten().is_none() {
        let _ = request_backend_shutdown(&managed.endpoint);
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if managed.child.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        if managed.child.try_wait().ok().flatten().is_none() {
            let _ = managed.child.kill();
        }
        let _ = managed.child.wait();
    }
    remove_runtime_descriptor(&managed.descriptor_path);
}

fn classify_start_failure(path: &Path, port: u16, status: ExitStatus) -> BackendFailure {
    let tail = read_log_tail(path, 32 * 1024).to_ascii_lowercase();
    let (code, message) = if tail.contains("address already in use")
        || tail.contains("only one usage of each socket address")
        || tail.contains("wsaeaddrinuse")
    {
        (
            "BACKEND_PORT_IN_USE",
            "The selected local backend port was occupied before AetherDB could start.",
        )
    } else {
        (
            "BACKEND_START_FAILED",
            "The local AetherDB service exited during startup.",
        )
    };
    BackendFailure::new(
        code,
        message,
        format!("Backend process exited with status {status}."),
    )
    .with_process(port, status.code(), path)
}

fn classify_runtime_failure(path: &Path, port: u16, status: ExitStatus) -> BackendFailure {
    BackendFailure::new(
        "BACKEND_UNAVAILABLE",
        "The local AetherDB service stopped unexpectedly.",
        format!("Backend process exited with status {status}."),
    )
    .with_process(port, status.code(), path)
}

fn read_log_tail(path: &Path, max_bytes: usize) -> String {
    let Ok(bytes) = std::fs::read(path) else {
        return String::new();
    };
    let start = bytes.len().saturating_sub(max_bytes);
    String::from_utf8_lossy(&bytes[start..]).to_string()
}

fn build_backend_command(
    _app: &AppHandle,
    endpoint: &BackendEndpoint,
    startup_descriptor_path: &Path,
) -> Result<Command, BackendFailure> {
    #[cfg(debug_assertions)]
    let (mut command, resource_root, runtime_root) = {
        let root = project_root_from_manifest(Path::new(env!("CARGO_MANIFEST_DIR"))).map_err(
            |reason| {
                BackendFailure::new(
                    "BACKEND_START_FAILED",
                    "AetherDB could not resolve its development backend.",
                    reason,
                )
            },
        )?;
        let python = development_python_path(&root, cfg!(windows));
        let entrypoint = root.join("main.py");
        require_file(&python, "development Python runtime")?;
        require_file(&entrypoint, "backend entrypoint")?;

        let mut command = Command::new(python);
        command.arg(entrypoint).current_dir(&root);
        (command, root.clone(), root)
    };

    #[cfg(not(debug_assertions))]
    let (mut command, resource_root, runtime_root) = {
        let resource_dir = _app.path().resource_dir().map_err(|error| {
            BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not resolve its packaged resources.",
                error.to_string(),
            )
        })?;
        let resource_root = resource_dir.join("backend");
        let runtime_root = desktop_runtime_root(_app)?;
        std::fs::create_dir_all(&runtime_root).map_err(|error| {
            BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not create its writable data directory.",
                error.to_string(),
            )
        })?;
        let binary = resource_root.join(backend_binary_name());
        require_file(&binary, "packaged backend sidecar")?;

        let mut command = Command::new(&binary);
        command.current_dir(&runtime_root);
        (command, resource_root, runtime_root)
    };

    let packaged_models_root = resource_root
        .parent()
        .map(|path| path.join("models"))
        .filter(|path| path.is_dir());

    command
        .env("AETHERDB_HOST", BACKEND_HOST)
        .env("AETHERDB_PORT", "0")
        .env("AETHERDB_STARTUP_DESCRIPTOR", startup_descriptor_path)
        .env("AETHERDB_BUILD_ID", BUILD_ID)
        .env("AETHERDB_DESKTOP_HANDSHAKE", &endpoint.handshake)
        .env("AETHERDB_DESKTOP_OWNER_TOKEN", &endpoint.owner_token)
        .env("AETHERDB_RUNTIME_INSTANCE_ID", &endpoint.instance_id)
        .env("AETHERDB_DEPLOYMENT_MODE", "local_desktop")
        .env("AETHERDB_RESOURCE_ROOT", resource_root)
        .env("AETHERDB_RUNTIME_ROOT", runtime_root)
        .env("WORLDVIEW_CORS", "desktop")
        .stdin(Stdio::null());

    if let Some(models_root) = packaged_models_root {
        let bge_model_root = models_root.join("bge-m3");
        command.env("AETHERDB_MODEL_PACKAGE_ROOT", &models_root);
        if bge_model_root.is_dir() {
            command.env("AETHERDB_MODEL_ROOT", bge_model_root);
        }
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    Ok(command)
}

fn development_python_path(root: &Path, windows: bool) -> PathBuf {
    if windows {
        root.join("venv").join("Scripts").join("python.exe")
    } else {
        root.join("venv").join("bin").join("python")
    }
}

fn project_root_from_manifest(manifest_dir: &Path) -> Result<PathBuf, String> {
    manifest_dir
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| "failed to resolve project root from Tauri manifest".to_string())
}

#[cfg(not(debug_assertions))]
fn backend_binary_name() -> &'static str {
    if cfg!(windows) {
        "aetherdb-backend.exe"
    } else {
        "aetherdb-backend"
    }
}

fn require_file(path: &Path, label: &str) -> Result<(), BackendFailure> {
    if path.is_file() {
        Ok(())
    } else {
        Err(BackendFailure::new(
            "BACKEND_START_FAILED",
            "A required AetherDB backend file is missing.",
            format!("{label} is missing: {}", path.display()),
        ))
    }
}

fn generate_random_hex(label: &str) -> Result<String, BackendFailure> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| {
        BackendFailure::new(
            "BACKEND_START_FAILED",
            "AetherDB could not create a private runtime identity.",
            format!("Failed to generate {label}: {error}"),
        )
    })?;
    let mut token = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

fn unix_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn backend_handshake_matches(endpoint: &BackendEndpoint) -> bool {
    let Some(response) = send_http_request(
        endpoint.address(),
        &format!(
            "GET {HANDSHAKE_PATH} HTTP/1.1\r\nHost: {BACKEND_HOST}:{}\r\nX-AetherDB-Desktop-Handshake: {}\r\nConnection: close\r\n\r\n",
            endpoint.port, endpoint.handshake
        ),
    ) else {
        return false;
    };
    response.contains("200 OK")
        && response.contains(IDENTITY_MARKER)
        && response.contains("\"service\":\"aetherdb-backend\"")
        && response.contains("\"status\":\"ok\"")
        && response.contains("\"database_ready\":true")
        && response.contains(&format!("\"build_id\":\"{BUILD_ID}\""))
        && response.contains(&format!("\"instance_id\":\"{}\"", endpoint.instance_id))
        && response.contains("\"transport\":\"dynamic_loopback\"")
}

fn request_backend_shutdown(endpoint: &BackendEndpoint) -> bool {
    send_http_request(
        endpoint.address(),
        &format!(
            "POST {HANDSHAKE_PATH}/shutdown HTTP/1.1\r\nHost: {BACKEND_HOST}:{}\r\nX-AetherDB-Desktop-Handshake: {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            endpoint.port, endpoint.handshake
        ),
    )
    .map(|response| response.contains("202 Accepted"))
    .unwrap_or(false)
}

fn send_http_request(address: SocketAddr, request: &str) -> Option<String> {
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(500)).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = Vec::with_capacity(4096);
    stream.read_to_end(&mut response).ok()?;
    if response.len() > 64 * 1024 {
        return None;
    }
    String::from_utf8(response).ok()
}

fn inspect_legacy_port() -> &'static str {
    let address = SocketAddr::from(([127, 0, 0, 1], LEGACY_BACKEND_PORT));
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {BACKEND_HOST}:{LEGACY_BACKEND_PORT}\r\nConnection: close\r\n\r\n"
    );
    match send_http_request(address, &request) {
        Some(response) if response.contains("\"service\":\"aetherdb-backend\"") => "aetherdb",
        Some(_) => "occupied_other",
        None if TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok() => {
            "occupied_other"
        }
        None => "available",
    }
}

fn task_join_failure(error: impl std::fmt::Display) -> BackendFailure {
    BackendFailure::new(
        "BACKEND_START_FAILED",
        "AetherDB could not complete backend process supervision.",
        error.to_string(),
    )
}

#[tauri::command]
async fn backend_status(state: State<'_, BackendManager>) -> Result<BackendStatus, BackendFailure> {
    let manager = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.status())
        .await
        .map_err(task_join_failure)?
}

#[tauri::command]
async fn start_backend(
    app: AppHandle,
    state: State<'_, BackendManager>,
) -> Result<BackendStatus, BackendFailure> {
    let manager = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || manager.start(&app))
        .await
        .map_err(task_join_failure)?
}

#[tauri::command]
async fn restart_backend(
    app: AppHandle,
    state: State<'_, BackendManager>,
) -> Result<BackendStatus, BackendFailure> {
    let manager = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        manager.stop();
        manager.start(&app)
    })
    .await
    .map_err(task_join_failure)?
}

#[tauri::command]
fn open_backend_logs(app: AppHandle) -> Result<(), BackendFailure> {
    let paths = desktop_runtime_paths(&app)?;
    app.opener()
        .open_path(paths.log_dir.display().to_string(), None::<&str>)
        .map_err(|error| {
            BackendFailure::new(
                "BACKEND_START_FAILED",
                "AetherDB could not open the log directory.",
                error.to_string(),
            )
        })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(BackendManager::default())
        .setup(|app| {
            let app_handle = app.handle().clone();
            let manager = app.state::<BackendManager>().inner().clone();
            tauri::async_runtime::spawn(async move {
                let _ =
                    tauri::async_runtime::spawn_blocking(move || manager.start(&app_handle)).await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_status,
            start_backend,
            restart_backend,
            open_backend_logs
        ])
        .build(tauri::generate_context!())
        .expect("failed to build the AetherDB desktop application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            app_handle.state::<BackendManager>().stop();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_root_is_two_levels_above_manifest() {
        let manifest = Path::new("C:/workspace/frontend/src-tauri");
        assert_eq!(
            project_root_from_manifest(manifest).unwrap(),
            PathBuf::from("C:/workspace")
        );
    }

    #[test]
    fn development_python_path_is_host_native() {
        let root = Path::new("/workspace");
        assert_eq!(
            development_python_path(root, false),
            PathBuf::from("/workspace/venv/bin/python")
        );
        assert_eq!(
            development_python_path(Path::new("C:/workspace"), true),
            PathBuf::from("C:/workspace/venv/Scripts/python.exe")
        );
    }

    #[test]
    fn sidecar_endpoint_starts_unbound_and_has_private_runtime_identity() {
        let endpoint = BackendEndpoint::create().unwrap();
        assert!(endpoint.address().ip().is_loopback());
        assert_eq!(endpoint.port, 0);
        assert_eq!(endpoint.handshake.len(), 64);
        assert!(endpoint
            .handshake
            .chars()
            .all(|value| value.is_ascii_hexdigit()));
        assert!(endpoint.owner_token.starts_with("aether_owner_"));
        assert_eq!(endpoint.owner_token.len(), 77);
        assert!(endpoint.instance_id.starts_with("aether_runtime_"));
        assert_eq!(endpoint.instance_id.len(), 47);
    }

    #[test]
    fn independently_created_endpoints_do_not_share_identity() {
        let first = BackendEndpoint::create().unwrap();
        let second = BackendEndpoint::create().unwrap();
        assert_ne!(first.handshake, second.handshake);
        assert_ne!(first.owner_token, second.owner_token);
        assert_ne!(first.instance_id, second.instance_id);
    }

    #[test]
    fn startup_descriptor_requires_matching_build_and_identity() {
        let endpoint = BackendEndpoint::create().unwrap();
        let path = std::env::temp_dir().join(format!(
            "aetherdb-startup-test-{}.json",
            endpoint.instance_id
        ));
        let payload = serde_json::json!({
            "protocol_version": "1.0",
            "service": "aetherdb-backend",
            "pid": std::process::id(),
            "port": 43127,
            "instance_id": endpoint.instance_id.clone(),
            "build_id": BUILD_ID,
        });
        std::fs::write(&path, serde_json::to_vec(&payload).unwrap()).unwrap();
        assert_eq!(
            read_startup_descriptor(&path, &endpoint, std::process::id()).unwrap(),
            Some(43127)
        );

        let mut mismatched = payload;
        mismatched["build_id"] = serde_json::Value::String("different-build".to_string());
        std::fs::write(&path, serde_json::to_vec(&mismatched).unwrap()).unwrap();
        let failure = read_startup_descriptor(&path, &endpoint, std::process::id()).unwrap_err();
        assert_eq!(failure.code, "BACKEND_BUILD_MISMATCH");
        let _ = std::fs::remove_file(path);
    }
}
