//! CommandPolicy：shell 命令执行策略。纯逻辑，零 IO，零 async。
//! 从原 executor/shell.rs 的 ShellPolicy::check 拆出。
//! 策略判定（enabled? deny 匹配? timeout 值?）在此处单测，不依赖 tokio runtime。
//! 真实执行（spawn sh）在 infra::RealShellRunner。

use shared::protocol::{Error, ErrorCode};
use serde::{Deserialize, Serialize};

/// 内置 deny 列表：破坏性命令子串。生产配置无法削弱（只能追加）。
pub fn default_deny_patterns() -> Vec<String> {
    vec![
        "rm -rf /".into(),
        "mkfs".into(),
        "dd if=/dev/zero of=/dev/".into(),
        ":(){ :|:&".into(),
    ]
}

/// shell 策略。enabled=false 时任何 cmd 都被拒；enabled=true 时仍受 deny 列表约束。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandPolicy {
    pub enabled: bool,
    pub timeout_secs: u64,
    pub deny_patterns: Vec<String>,
}

impl Default for CommandPolicy {
    fn default() -> Self {
        Self {
            enabled: false,
            timeout_secs: 30,
            deny_patterns: default_deny_patterns(),
        }
    }
}

impl CommandPolicy {
    /// 用配置构造：内置 deny 列表始终生效，extra_deny 只能追加收紧，不能削弱。
    pub fn from_config(enabled: bool, timeout_secs: u64, extra_deny: &[String]) -> Self {
        let mut deny = default_deny_patterns();
        deny.extend(extra_deny.iter().cloned());
        Self {
            enabled,
            timeout_secs,
            deny_patterns: deny,
        }
    }

    /// 判定一条 cmdline 是否允许执行。不允许返回 JSON-RPC Error（ShellDisabled/ShellDenied）。
    pub fn check(&self, cmdline: &str) -> Result<(), Error> {
        if !self.enabled {
            return Err(Error::new(
                ErrorCode::ShellDisabled,
                "raw shell is disabled in the daemon config",
            ));
        }
        for pat in &self.deny_patterns {
            if cmdline.contains(pat.as_str()) {
                return Err(Error::new(
                    ErrorCode::ShellDenied,
                    format!("command matches deny pattern: {pat}"),
                ));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_rejects_everything() {
        // enabled=false 时，任何命令（哪怕无害）都被拒，错误码 ShellDisabled。
        let p = CommandPolicy::default(); // 默认 disabled
        let err = p.check("echo hi").unwrap_err();
        assert_eq!(err.code, ErrorCode::ShellDisabled as i32);
    }

    #[test]
    fn enabled_allows_safe_command() {
        // enabled=true 且不在 deny 列表，echo hi 允许。
        let p = CommandPolicy { enabled: true, timeout_secs: 5, deny_patterns: default_deny_patterns() };
        assert!(p.check("echo hi").is_ok());
    }

    #[test]
    fn enabled_denies_mkfs() {
        // mkfs 在内置 deny 列表，即使 enabled=true 也被拒，错误码 ShellDenied。
        let p = CommandPolicy { enabled: true, timeout_secs: 5, deny_patterns: default_deny_patterns() };
        let err = p.check("mkfs /dev/sda1").unwrap_err();
        assert_eq!(err.code, ErrorCode::ShellDenied as i32);
    }

    #[test]
    fn enabled_denies_rm_rf_root() {
        // rm -rf / 被拒。
        let p = CommandPolicy { enabled: true, timeout_secs: 5, deny_patterns: default_deny_patterns() };
        assert!(p.check("sudo rm -rf /").is_err());
    }

    #[test]
    fn from_config_cannot_weaken_defaults() {
        // from_config 即便传空 extra_deny，内置 deny 列表仍在。
        let p = CommandPolicy::from_config(true, 10, &[]);
        assert!(p.check("mkfs").is_err());
        assert!(p.check("rm -rf /").is_err());
    }

    #[test]
    fn from_config_extra_deny_adds_pattern() {
        // 额外 deny 模式被追加，能拦截新命令。
        let p = CommandPolicy::from_config(true, 10, &["shutdown".into()]);
        assert!(p.check("sudo shutdown now").is_err());
    }
}
