//! 假 infra 实现：用 HashMap 预设数据，实现 ports trait，供测试注入。

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

use async_trait::async_trait;
use shared::ports::{Collector, HrutGateway, ProcReader, ShellError, ShellOutput, ShellRunner, SysfsReader};
use shared::protocol::StateSnapshotFragment;

/// 假 sysfs：files 存单值文件内容，dirs 存目录条目列表。
#[derive(Default, Clone)]
pub struct FakeSysfsReader {
    pub files: HashMap<String, String>,
    pub dirs: HashMap<String, Vec<String>>,
}

#[async_trait]
impl SysfsReader for FakeSysfsReader {
    async fn read_dir(&self, path: &str) -> std::io::Result<Vec<String>> {
        self.dirs
            .get(path)
            .cloned()
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, format!("dir {path} not found")))
    }
    async fn read_first_line(&self, path: &str) -> Option<String> {
        self.files.get(path).map(|s| s.lines().next().unwrap_or("").trim().to_string())
    }
    async fn read_int(&self, path: &str) -> Option<i64> {
        self.read_first_line(path).await?.parse().ok()
    }
}

/// 假 procfs：files 存整个文件内容。
#[derive(Default, Clone)]
pub struct FakeProcReader {
    pub files: HashMap<String, String>,
}

#[async_trait]
impl ProcReader for FakeProcReader {
    async fn read(&self, path: &str) -> Option<String> {
        self.files.get(path).cloned()
    }
}

/// 假 hrut 网关：tools 存每个工具的预设 stdout。
#[derive(Default, Clone)]
pub struct FakeHrutGateway {
    pub tools: HashMap<String, String>,
}

#[async_trait]
impl HrutGateway for FakeHrutGateway {
    async fn run(&self, tool: &str) -> Option<String> {
        self.tools.get(tool).cloned()
    }
}

/// 假 shell 执行器：预设每条命令的输出。匹配不到时返回 None（视为 spawn 失败）。
pub struct FakeShellRunner {
    pub outputs: Mutex<HashMap<String, ShellOutput>>,
    /// 是否在匹配不到时返回超时错误（用于测超时路径）。
    pub timeout_on_unknown: bool,
}

#[async_trait]
impl ShellRunner for FakeShellRunner {
    async fn run(&self, cmd: &str, _timeout: Duration) -> Result<ShellOutput, ShellError> {
        let outputs = self.outputs.lock().unwrap();
        if let Some(out) = outputs.get(cmd) {
            return Ok(out.clone());
        }
        if self.timeout_on_unknown {
            return Err(ShellError::Timeout { secs: _timeout.as_secs() });
        }
        // 匹配不到：返回空成功输出（便于简单用例）。
        Ok(ShellOutput { exit: Some(0), stdout: String::new(), stderr: String::new() })
    }
}

impl FakeShellRunner {
    pub fn new() -> Self {
        Self { outputs: Mutex::new(HashMap::new()), timeout_on_unknown: false }
    }
    pub fn with(self, cmd: &str, out: ShellOutput) -> Self {
        self.outputs.lock().unwrap().insert(cmd.to_string(), out);
        self
    }
}

impl Default for FakeShellRunner {
    fn default() -> Self {
        Self::new()
    }
}

/// 假采集器：返回预设片段（或 None）。
pub struct FakeCollector {
    pub name: &'static str,
    pub frag: Option<StateSnapshotFragment>,
}

#[async_trait]
impl Collector for FakeCollector {
    fn name(&self) -> &'static str {
        self.name
    }
    async fn collect(&self) -> Option<StateSnapshotFragment> {
        self.frag.clone()
    }
}
