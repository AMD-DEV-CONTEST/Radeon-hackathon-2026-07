//! 端口层错误类型：硬件读取与 shell 执行的抽象错误。
//! 实现层（infra）把这些错误用 infra 层自己的 Exception 包装后再上抛。

use thiserror::Error;

/// 端口层通用错误：读硬件失败时的抽象。
#[derive(Debug, Error)]
pub enum PortError {
    #[error("io 错误: {0}")]
    Io(String),
    #[error("解析错误: {0}")]
    Parse(String),
}

/// shell 执行错误：超时、spawn 失败等。成功执行的"非零退出码"不是错误，而是 ShellOutput.exit。
#[derive(Debug, Error)]
pub enum ShellError {
    #[error("spawn 失败: {0}")]
    Spawn(String),
    #[error("命令超时（{secs} 秒）")]
    Timeout { secs: u64 },
    #[error("等待进程失败: {0}")]
    Wait(String),
}

/// 插件执行错误：插件目录/清单不合法、插件不存在或子进程无法完成时返回。
#[derive(Debug, Error)]
pub enum PluginError {
    #[error("插件功能未启用")]
    Disabled,
    #[error("插件 '{0}' 不存在")]
    NotFound(String),
    #[error("插件清单无效: {0}")]
    InvalidManifest(String),
    #[error("插件进程启动失败: {0}")]
    Spawn(String),
    #[error("插件进程等待失败: {0}")]
    Wait(String),
    #[error("插件执行超时（{secs} 秒）")]
    Timeout { secs: u64 },
}
