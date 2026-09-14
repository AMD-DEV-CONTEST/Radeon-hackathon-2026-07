//! sophonctl 客户端配置文件：板子别名表 + 默认连接。
//!
//! 配置文件位置：~/.rdk-sophon/config.toml（XDG 不适合，用项目自带目录惯例，
//! 像 ~/.ssh / ~/.kube / ~/.cargo 一样一个目录放多文件，未来可扩展凭证/缓存）。
//!
//! 文件格式：
//! ```toml
//! [default]
//! host = "192.168.128.10:17777"
//! timeout = 30
//!
//! [boards.x5]
//! host = "192.168.128.10:17777"
//! timeout = 30
//!
//! [boards.lab-1]
//! host = "192.168.1.50:17777"
//! timeout = 10
//! ```
//!
//! 加载顺序（调用方实现优先级）：--host > --board 别名 > PROBE_HOST env > [default] > 本地 unix socket。

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// 单个板子的连接配置（别名指向它）。
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BoardConfig {
    /// 远程地址 ip:port。
    pub host: String,
    /// 响应超时秒（可选，缺省用 CLI 全局默认）。
    #[serde(default)]
    pub timeout: Option<u64>,
}

/// 整个配置文件。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SophonConfig {
    /// 默认板子（不带 --board 且无 --host/PROBE_HOST 时用）。
    #[serde(default)]
    pub default: Option<BoardConfig>,
    /// 别名表。
    #[serde(default)]
    pub boards: std::collections::BTreeMap<String, BoardConfig>,
}

impl SophonConfig {
    /// 配置文件路径：~/.rdk-sophon/config.toml。
    /// 尊重 SOPHON_CONFIG 环境变量覆盖（测试/多环境用）。
    pub fn path() -> Result<PathBuf> {
        if let Ok(p) = std::env::var("SOPHON_CONFIG") {
            return Ok(PathBuf::from(p));
        }
        let home = std::env::var("HOME").context("HOME 环境变量未设")?;
        Ok(PathBuf::from(home).join(".rdk-sophon").join("config.toml"))
    }

    /// 加载配置文件。文件不存在视为空配置（不报错，首次用）。
    pub fn load() -> Result<Self> {
        let p = Self::path()?;
        if !p.exists() {
            return Ok(Self::default());
        }
        let s =
            std::fs::read_to_string(&p).with_context(|| format!("读配置失败: {}", p.display()))?;
        let cfg: SophonConfig =
            toml::from_str(&s).with_context(|| format!("解析配置失败: {}", p.display()))?;
        Ok(cfg)
    }

    /// 保存配置到文件（config add/rm 子命令用）。
    pub fn save(&self) -> Result<()> {
        let p = Self::path()?;
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("建目录失败: {}", parent.display()))?;
        }
        let s = toml::to_string_pretty(self).context("序列化配置失败")?;
        std::fs::write(&p, s).with_context(|| format!("写配置失败: {}", p.display()))?;
        Ok(())
    }

    /// 按别名取板子配置。无别名返回 None。
    pub fn board(&self, name: &str) -> Option<&BoardConfig> {
        self.boards.get(name)
    }
}

/// 把 ~ 路径展开成绝对路径（用于打印时显示友好）。
pub fn expand_home(p: &Path) -> String {
    if let Ok(home) = std::env::var("HOME") {
        if let Ok(rest) = p.strip_prefix(home.as_str()) {
            return format!("~/{}", rest.display());
        }
    }
    p.display().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_default_and_boards() {
        let s = r#"
[default]
host = "192.168.128.10:17777"
timeout = 30

[boards.x5]
host = "192.168.128.10:17777"

[boards.lab-1]
host = "192.168.1.50:17777"
timeout = 10
"#;
        let cfg: SophonConfig = toml::from_str(s).unwrap();
        assert_eq!(cfg.default.as_ref().unwrap().host, "192.168.128.10:17777");
        assert_eq!(cfg.board("x5").unwrap().host, "192.168.128.10:17777");
        assert_eq!(cfg.board("lab-1").unwrap().timeout, Some(10));
        assert!(cfg.board("nope").is_none());
    }

    #[test]
    fn empty_config_is_ok() {
        // 空文件应解析成默认（空配置），不报错。
        let cfg: SophonConfig = toml::from_str("").unwrap();
        assert!(cfg.default.is_none());
        assert!(cfg.boards.is_empty());
    }
}
