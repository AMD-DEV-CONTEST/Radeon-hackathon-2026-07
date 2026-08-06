use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub log: LogConfig,
    #[serde(default)]
    pub tcp: TcpConfig,
    #[serde(default)]
    pub unix: UnixConfig,
    #[serde(default)]
    pub serial: Option<SerialConfig>,
    #[serde(default)]
    pub telemetry: TelemetryConfig,
    #[serde(default)]
    pub shell: ShellConfig,
    #[serde(default)]
    pub plugins: PluginsConfig,
    #[serde(default)]
    pub alerts: AlertsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogConfig {
    #[serde(default = "default_level")]
    pub level: String,
    /// Directory for the audit + rolling logs. Empty = stderr only.
    #[serde(default)]
    pub dir: String,
}

fn default_level() -> String {
    "info".to_string()
}
impl Default for LogConfig {
    fn default() -> Self {
        Self {
            level: default_level(),
            dir: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TcpConfig {
    #[serde(default = "default_tcp_enabled")]
    pub enabled: bool,
    #[serde(default = "default_tcp_bind")]
    pub bind: String,
}

fn default_tcp_enabled() -> bool {
    true
}
fn default_tcp_bind() -> String {
    "0.0.0.0:7777".to_string()
}
impl Default for TcpConfig {
    fn default() -> Self {
        Self {
            enabled: default_tcp_enabled(),
            bind: default_tcp_bind(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UnixConfig {
    #[serde(default = "default_unix_enabled")]
    pub enabled: bool,
    #[serde(default = "default_unix_path")]
    pub path: String,
}

fn default_unix_enabled() -> bool {
    true
}
fn default_unix_path() -> String {
    "/run/probe-daemon/probe.sock".to_string()
}
impl Default for UnixConfig {
    fn default() -> Self {
        Self {
            enabled: default_unix_enabled(),
            path: default_unix_path(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerialConfig {
    pub path: String,
    pub baud: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryConfig {
    /// Push interval in seconds. 0 disables push.
    #[serde(default = "default_telemetry_interval")]
    pub interval_secs: u64,
}

fn default_telemetry_interval() -> u64 {
    5
}
impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            interval_secs: default_telemetry_interval(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShellConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_shell_timeout")]
    pub timeout_secs: u64,
    #[serde(default)]
    pub deny_patterns: Vec<String>,
}

fn default_shell_timeout() -> u64 {
    30
}
impl Default for ShellConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            timeout_secs: default_shell_timeout(),
            deny_patterns: Vec::new(),
        }
    }
}

/// 动态控制插件配置。插件默认关闭，避免未知目录中的程序获得 daemon 执行入口。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PluginsConfig {
    /// 是否启用 `plugin.list` 与 `plugin.invoke` RPC。
    #[serde(default)]
    pub enabled: bool,
    /// 仅从此 root 管理目录发现 `<id>/plugin.toml`。
    #[serde(default = "default_plugins_dir")]
    pub dir: String,
}

fn default_plugins_dir() -> String {
    "/opt/sophon/plugins".to_string()
}

impl Default for PluginsConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            dir: default_plugins_dir(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertsConfig {
    /// °C threshold for the thermal alert.
    #[serde(default = "default_alert_temp")]
    pub temp_c: f64,
    /// Disk usage % threshold.
    #[serde(default = "default_alert_disk")]
    pub disk_usage_pct: f64,
}

fn default_alert_temp() -> f64 {
    75.0
}
fn default_alert_disk() -> f64 {
    90.0
}
impl Default for AlertsConfig {
    fn default() -> Self {
        Self {
            temp_c: default_alert_temp(),
            disk_usage_pct: default_alert_disk(),
        }
    }
}

impl Config {
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let s = std::fs::read_to_string(path)?;
        let cfg: Config = toml::from_str(&s)?;
        Ok(cfg)
    }
}
