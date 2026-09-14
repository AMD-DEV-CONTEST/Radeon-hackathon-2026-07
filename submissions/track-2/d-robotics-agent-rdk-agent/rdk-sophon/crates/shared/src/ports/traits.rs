//! 端口 trait：硬件读取、采集、shell 执行的抽象接口。
//!
//! 所有方法均为同步或 async，具体由实现决定。infra crate 提供真实实现，
//! tests-common crate 提供假实现。Collector 在构造期注入 SysfsReader/ProcReader/HrutGateway，
//! ShellRunner 由 application 层注入到 shell 执行用例。

use async_trait::async_trait;
use std::time::Duration;

use crate::protocol::StateSnapshotFragment;

/// 单个硬件采集器：返回一个状态片段。返回 None 表示该采集器在该板上无可用数据（正常情况，不报错）。
#[async_trait]
pub trait Collector: Send + Sync {
    /// 采集器名称，用于日志与排障。
    fn name(&self) -> &'static str;
    /// 执行一次采集，返回片段或 None。失败时记录日志后返回 None，绝不 panic。
    async fn collect(&self) -> Option<StateSnapshotFragment>;
}

/// sysfs 读取抽象：读 `/sys/class/thermal` 等目录与单值文件。
/// 真实实现见 infra::RealSysfsReader；测试用 FakeSysfsReader（HashMap）。
#[async_trait]
pub trait SysfsReader: Send + Sync {
    /// 列举目录下的条目名（不含完整路径）。目录不存在返回错误。
    async fn read_dir(&self, path: &str) -> std::io::Result<Vec<String>>;
    /// 读文件首行并 trim。文件不存在返回 None。
    async fn read_first_line(&self, path: &str) -> Option<String>;
    /// 读文件首个空白分隔 token 解析为 i64。不存在或非数字返回 None。
    async fn read_int(&self, path: &str) -> Option<i64>;
}

/// procfs 读取抽象：读 `/proc/loadavg`、`/proc/meminfo`、`/proc/stat`、`/proc/net/dev`、`/proc/mounts`、`/proc/uptime` 等。
/// 与 SysfsReader 分开：procfs 是多行键值/分段语义，sysfs 是目录+单值文件语义，合并会让 trait 过宽。
#[async_trait]
pub trait ProcReader: Send + Sync {
    /// 读整个文件内容为字符串。文件不存在返回 None。
    async fn read(&self, path: &str) -> Option<String>;
}

/// Horizon `hrut_*` 工具网关：执行 `hrut_bpuinfo`/`hrut_sensors`/`hrut_thermal` 等，返回 stdout。
/// 真实实现见 infra::RealHrutGateway（Command::new）；测试用 FakeHrutGateway（HashMap）。
#[async_trait]
pub trait HrutGateway: Send + Sync {
    /// 执行指定 hrut 工具，返回其 stdout。工具不存在或执行失败返回 None。
    async fn run(&self, tool: &str) -> Option<String>;
}

/// shell 命令执行结果：退出码 + 截断后的 stdout/stderr。
#[derive(Debug, Clone)]
pub struct ShellOutput {
    /// 进程退出码；被信号杀死时为 None。
    pub exit: Option<i32>,
    /// stdout（已按上限截断）。
    pub stdout: String,
    /// stderr（已按上限截断）。
    pub stderr: String,
}

/// shell 执行抽象：真实实现见 infra::RealShellRunner（tokio::process + 超时 + deny 由上层策略保证）。
/// 与 CommandPolicy 分离：本 trait 只负责"执行"，deny/timeout 值的判定是 domain 层纯策略。
#[async_trait]
pub trait ShellRunner: Send + Sync {
    /// 用 sh -c 执行 cmd，超时由 timeout 控制。超时返回 ShellError::Timeout。
    async fn run(&self, cmd: &str, timeout: Duration) -> Result<ShellOutput, super::ShellError>;
}

/// 已发现插件的公开元数据。仅包含可安全展示给 CLI/调用方的信息。
#[derive(Debug, Clone, serde::Serialize)]
pub struct PluginInfo {
    /// 插件唯一标识，同时也是 CLI 的一级子命令名。
    pub id: String,
    /// 插件的人类可读说明。
    pub description: String,
}

/// 一次插件调用的返回结果。
#[derive(Debug, Clone)]
pub struct PluginOutput {
    /// 插件进程退出码；被信号终止时为 None。
    pub exit: Option<i32>,
    /// 标准输出，已按服务端上限截断。
    pub stdout: String,
    /// 标准错误，已按服务端上限截断。
    pub stderr: String,
}

/// 动态控制插件端口。实现必须以精确 argv 启动入口，禁止经 shell 解释用户参数。
#[async_trait]
pub trait PluginRunner: Send + Sync {
    /// 列出当前目录中可用的插件。
    async fn list(&self) -> Result<Vec<PluginInfo>, super::PluginError>;
    /// 调用指定插件，args 不含插件名本身。
    async fn invoke(
        &self,
        plugin: &str,
        args: &[String],
    ) -> Result<PluginOutput, super::PluginError>;
}
