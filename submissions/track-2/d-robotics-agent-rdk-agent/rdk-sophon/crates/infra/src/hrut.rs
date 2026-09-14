//! RealHrutGateway：调 Horizon `hrut_*` 工具的 HrutGateway 实现。
//! 从原 collectors/bpu.rs 的 run() 提取。工具不存在返回 None，daemon 在非 RDK 板上自动省略 bpu 字段。

use async_trait::async_trait;
use shared::ports::HrutGateway;
use std::process::Command;

pub struct RealHrutGateway;

impl RealHrutGateway {
    pub fn new() -> Self {
        Self
    }
}

impl Default for RealHrutGateway {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl HrutGateway for RealHrutGateway {
    /// 执行指定 hrut 工具，返回 stdout。失败返回 None。
    async fn run(&self, tool: &str) -> Option<String> {
        // 先试 --help 确认工具存在；成功后再跑无参版本拿真实输出。
        // 若 --help 失败（某些 hrut 工具无 --help），回退到无参执行。
        let help_ok = Command::new(tool).arg("--help").output().ok().map(|o| o.status.success()).unwrap_or(false);
        let output = if help_ok {
            Command::new(tool).output().ok()
        } else {
            // 直接无参跑，捕获 stdout（即使退出码非零也可能有有用输出）
            Command::new(tool).output().ok()
        };
        output.map(|o| String::from_utf8_lossy(&o.stdout).to_string())
    }
}
