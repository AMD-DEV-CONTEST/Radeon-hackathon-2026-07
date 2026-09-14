//! 动态控制插件的真实执行器。
//!
//! 插件以 `<插件目录>/<id>/plugin.toml` 描述。执行器每次调用时重新扫描目录，
//! 因此安装或删除插件无需重启 probe-daemon。入口以 `Command::new` 接收精确 argv，
//! 用户参数绝不交给 shell 解释。

use std::path::{Path, PathBuf};
use std::process::Stdio;

use async_trait::async_trait;
use serde::Deserialize;
use shared::ports::{PluginError, PluginInfo, PluginOutput, PluginRunner};
use tokio::io::AsyncReadExt;
use tokio::process::Command;

/// 每个 stdout/stderr 流的最大回传字节数，避免插件撑爆 RPC 响应。
const MAX_OUTPUT_BYTES: usize = 256 * 1024;

/// 板端插件清单的磁盘格式。
#[derive(Debug, Deserialize)]
struct PluginManifest {
    /// 契约版本；当前仅接受 1。
    api_version: u32,
    /// 插件唯一名称。
    id: String,
    /// 展示在 `sophonctl plugins list` 中的说明。
    #[serde(default)]
    description: String,
    /// 可执行入口及其固定参数，第一个元素是程序路径。
    entrypoint: Vec<String>,
    /// 单次调用超时秒数；0 表示不设置服务端超时。
    #[serde(default)]
    timeout_secs: u64,
}

/// 真实插件执行器，负责发现 manifest 与启动受控子进程。
pub struct RealPluginRunner {
    plugin_dir: PathBuf,
}

impl RealPluginRunner {
    /// 使用给定根目录创建执行器。
    pub fn new(plugin_dir: impl Into<PathBuf>) -> Self {
        Self {
            plugin_dir: plugin_dir.into(),
        }
    }

    fn manifests(&self) -> Result<Vec<PluginManifest>, PluginError> {
        if !self.plugin_dir.exists() {
            return Ok(Vec::new());
        }
        let entries = std::fs::read_dir(&self.plugin_dir).map_err(|e| {
            PluginError::InvalidManifest(format!("无法读取 {}: {e}", self.plugin_dir.display()))
        })?;
        let mut manifests = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|e| PluginError::InvalidManifest(e.to_string()))?;
            let manifest_path = entry.path().join("plugin.toml");
            if !manifest_path.is_file() {
                continue;
            }
            manifests.push(Self::parse_manifest(&manifest_path)?);
        }
        manifests.sort_by(|left, right| left.id.cmp(&right.id));
        Ok(manifests)
    }

    fn parse_manifest(path: &Path) -> Result<PluginManifest, PluginError> {
        let content = std::fs::read_to_string(path).map_err(|e| {
            PluginError::InvalidManifest(format!("无法读取 {}: {e}", path.display()))
        })?;
        let manifest: PluginManifest = toml::from_str(&content)
            .map_err(|e| PluginError::InvalidManifest(format!("{}: {e}", path.display())))?;
        if manifest.api_version != 1 {
            return Err(PluginError::InvalidManifest(format!(
                "{}: api_version 必须为 1",
                path.display()
            )));
        }
        if !valid_plugin_id(&manifest.id) {
            return Err(PluginError::InvalidManifest(format!(
                "{}: id '{}' 非法",
                path.display(),
                manifest.id
            )));
        }
        if manifest.entrypoint.is_empty() || manifest.entrypoint[0].is_empty() {
            return Err(PluginError::InvalidManifest(format!(
                "{}: entrypoint 不能为空",
                path.display()
            )));
        }
        Ok(manifest)
    }
}

/// 关闭动态插件时使用的空实现，避免 shell 回退成为插件执行通道。
pub struct DisabledPluginRunner;

#[async_trait]
impl PluginRunner for DisabledPluginRunner {
    async fn list(&self) -> Result<Vec<PluginInfo>, PluginError> {
        Ok(Vec::new())
    }

    async fn invoke(&self, plugin: &str, _args: &[String]) -> Result<PluginOutput, PluginError> {
        Err(PluginError::NotFound(plugin.to_string()))
    }
}

#[async_trait]
impl PluginRunner for RealPluginRunner {
    async fn list(&self) -> Result<Vec<PluginInfo>, PluginError> {
        self.manifests().map(|manifests| {
            manifests
                .into_iter()
                .map(|manifest| PluginInfo {
                    id: manifest.id,
                    description: manifest.description,
                })
                .collect()
        })
    }

    async fn invoke(&self, plugin: &str, args: &[String]) -> Result<PluginOutput, PluginError> {
        let manifest = self
            .manifests()?
            .into_iter()
            .find(|manifest| manifest.id == plugin)
            .ok_or_else(|| PluginError::NotFound(plugin.to_string()))?;

        // 固定入口参数在前，用户参数只作为独立 argv 元素附加，杜绝注入。
        let mut command = Command::new(&manifest.entrypoint[0]);
        command
            .args(&manifest.entrypoint[1..])
            .args(args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command
            .spawn()
            .map_err(|e| PluginError::Spawn(e.to_string()))?;
        let mut stdout = child.stdout.take().expect("stdout 已设为 pipe");
        let mut stderr = child.stderr.take().expect("stderr 已设为 pipe");
        let mut out_buf = Vec::new();
        let mut err_buf = Vec::new();

        let wait = async {
            let (out_result, err_result, status_result) = tokio::join!(
                stdout.read_to_end(&mut out_buf),
                stderr.read_to_end(&mut err_buf),
                child.wait(),
            );
            let _ = (out_result, err_result);
            status_result.map_err(|e| PluginError::Wait(e.to_string()))
        };
        let status = if manifest.timeout_secs == 0 {
            wait.await?
        } else {
            tokio::time::timeout(std::time::Duration::from_secs(manifest.timeout_secs), wait)
                .await
                .map_err(|_| PluginError::Timeout {
                    secs: manifest.timeout_secs,
                })??
        };
        out_buf.truncate(MAX_OUTPUT_BYTES);
        err_buf.truncate(MAX_OUTPUT_BYTES);
        Ok(PluginOutput {
            exit: status.code(),
            stdout: String::from_utf8_lossy(&out_buf).to_string(),
            stderr: String::from_utf8_lossy(&err_buf).to_string(),
        })
    }
}

fn valid_plugin_id(id: &str) -> bool {
    let mut chars = id.chars();
    matches!(chars.next(), Some(first) if first.is_ascii_lowercase())
        && chars.all(|character| {
            character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
        })
}

#[cfg(test)]
mod tests {
    use super::valid_plugin_id;

    #[test]
    fn plugin_id_must_be_a_safe_cli_name() {
        assert!(valid_plugin_id("servo"));
        assert!(valid_plugin_id("robot-arm2"));
        assert!(!valid_plugin_id("2servo"));
        assert!(!valid_plugin_id("servo_ctrl"));
        assert!(!valid_plugin_id("../servo"));
    }
}
