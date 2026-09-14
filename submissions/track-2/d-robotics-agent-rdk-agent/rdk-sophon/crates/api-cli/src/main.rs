//! sophonctl：本地 CLI 或远程客户端。本地走 Unix socket，远程走 TCP（--host 或别名）。
//! 复用 client::Client（与 HTTP 网关、WS 出站同源），与 daemon 走同一套 NDJSON 协议。
//!
//! 连接目标优先级（高到低）：
//!   --host <ip:port>   >  --board <别名>  >  PROBE_HOST 环境变量  >  配置 [default]  >  本地 unix socket
//!
//! 配置文件 ~/.rdk-sophon/config.toml 管理板子别名表（见 mod config）。

mod config;

use anyhow::{anyhow, Result};
use clap::{Parser, Subcommand};
use client::{Client, ClientBuilder};
use shared::protocol::Params;
use std::ffi::OsString;
use std::io::Write;
use std::time::Duration;

use config::SophonConfig;

#[derive(Debug, Parser)]
#[command(name = "sophonctl", about = "操作 rdk-sophon 探针守护进程")]
struct Cli {
    /// 远程板子地址（ip:port）。最高优先级，覆盖 --board/env/配置。
    #[arg(long, env = "PROBE_HOST")]
    host: Option<String>,
    /// 板子别名（来自 ~/.rdk-sophon/config.toml 的 [boards.<别名>]）。
    /// 次于 --host，高于 env/配置默认。
    #[arg(long)]
    board: Option<String>,
    /// 本地 daemon 的 Unix socket 路径（仅无远程地址时用）。
    #[arg(
        short,
        long,
        default_value = "/run/probe-daemon/probe.sock",
        env = "PROBE_SOCK",
        global = true
    )]
    socket: String,
    /// 响应超时（秒）。--board 配置里若有 timeout 会覆盖此默认。
    #[arg(long, default_value = "30", global = true)]
    timeout: u64,
    /// 以紧凑 JSON 输出（适合脚本解析）。
    #[arg(long, global = true)]
    raw: bool,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Debug, Subcommand)]
enum Cmd {
    Ping,
    State,
    Thermal,
    Cpu,
    Memory,
    Disk,
    Net,
    Bpu,
    Refresh,
    Exec {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true, num_args = 1..)]
        cmd: Vec<String>,
    },
    Raw {
        method: String,
        params: Option<String>,
    },
    /// 管理板子别名（~/.rdk-sophon/config.toml）。
    #[command(subcommand)]
    Config(ConfigCmd),
    /// 管理并列出板端动态控制插件。
    #[command(subcommand)]
    Plugins(PluginsCmd),
    /// 未被内置命令占用的一级子命令按动态插件转发给板端。
    #[command(external_subcommand)]
    Plugin(Vec<OsString>),
}

#[derive(Debug, Subcommand)]
enum ConfigCmd {
    /// 列出所有别名与默认。
    List,
    /// 添加/更新一个别名。
    Add {
        /// 别名。
        name: String,
        /// 远程地址 ip:port。
        host: String,
        /// 超时秒（可选）。
        #[arg(long)]
        timeout: Option<u64>,
        /// 设为默认（不带 --board 时用）。
        #[arg(long)]
        default: bool,
    },
    /// 删除一个别名。
    Rm {
        /// 别名。
        name: String,
    },
    /// 显示配置文件路径。
    Path,
}

/// 动态插件管理子命令。
#[derive(Debug, Subcommand)]
enum PluginsCmd {
    /// 列出板端已安装、可调用的插件。
    List,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // config 子命令不连 daemon，直接操作配置文件后退出。
    if let Cmd::Config(sub) = &cli.cmd {
        return run_config(sub);
    }

    // 解析连接目标（host + timeout）。
    let (host, timeout_secs) = resolve_target(&cli)?;
    let timeout = Duration::from_secs(timeout_secs);
    let client = if let Some(h) = host {
        ClientBuilder::new().timeout(timeout).tcp(&h).await?
    } else {
        ClientBuilder::new()
            .timeout(timeout)
            .unix(&cli.socket)
            .await?
    };

    let exit = match &cli.cmd {
        Cmd::Ping => print(&client, "ping", None, cli.raw).await?,
        Cmd::State => print(&client, "get_state", None, cli.raw).await?,
        Cmd::Thermal => print(&client, "get_thermal", None, cli.raw).await?,
        Cmd::Cpu => print(&client, "get_cpu", None, cli.raw).await?,
        Cmd::Memory => print(&client, "get_memory", None, cli.raw).await?,
        Cmd::Disk => print(&client, "get_disk", None, cli.raw).await?,
        Cmd::Net => print(&client, "get_net", None, cli.raw).await?,
        Cmd::Bpu => print(&client, "get_bpu", None, cli.raw).await?,
        Cmd::Refresh => print(&client, "refresh_state", None, cli.raw).await?,
        Cmd::Exec { cmd } => {
            let joined = cmd.join(" ");
            let mut map = serde_json::Map::new();
            map.insert("cmd".into(), serde_json::Value::String(joined));
            print(&client, "exec_shell", Some(Params::Named(map)), cli.raw).await?
        }
        Cmd::Raw { method, params } => {
            let p = match params {
                Some(s) => {
                    let v: serde_json::Value = serde_json::from_str(s)?;
                    Some(Params::Named(
                        v.as_object()
                            .cloned()
                            .ok_or_else(|| anyhow!("params 必须是 JSON 对象"))?,
                    ))
                }
                None => None,
            };
            print(&client, method, p, cli.raw).await?
        }
        Cmd::Plugins(PluginsCmd::List) => print(&client, "plugin.list", None, cli.raw).await?,
        Cmd::Plugin(parts) => {
            let (plugin, args) = plugin_parts(parts)?;
            let mut map = serde_json::Map::new();
            map.insert("plugin".into(), serde_json::Value::String(plugin));
            map.insert(
                "args".into(),
                serde_json::Value::Array(args.into_iter().map(serde_json::Value::String).collect()),
            );
            print(&client, "plugin.invoke", Some(Params::Named(map)), cli.raw).await?
        }
        Cmd::Config(_) => unreachable!("config 子命令已在上方处理"),
    };

    // exec 与插件调用返回的退出码应成为 sophonctl 自身的退出码，方便脚本判断结果。
    if let Some(code) = exit.filter(|code| *code != 0) {
        std::process::exit(code);
    }
    Ok(())
}

/// 将 clap 捕获的未知子命令转为 JSON 可表达的插件名与参数。
fn plugin_parts(parts: &[OsString]) -> Result<(String, Vec<String>)> {
    let (name, args) = parts
        .split_first()
        .ok_or_else(|| anyhow!("缺少插件名；用 sophonctl plugins list 查看可用插件"))?;
    let name = name
        .to_str()
        .ok_or_else(|| anyhow!("插件名必须是 UTF-8"))?
        .to_string();
    let args = args
        .iter()
        .map(|arg| {
            arg.to_str()
                .map(str::to_string)
                .ok_or_else(|| anyhow!("插件参数必须是 UTF-8"))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok((name, args))
}

/// 解析连接目标。返回 (Option<host>, timeout_secs)。
/// 优先级：--host > --board 别名 > 配置 [default] > None（走本地 unix）。
/// env PROBE_HOST 已被 clap 注入到 cli.host，故 --host 与 env 同级。
fn resolve_target(cli: &Cli) -> Result<(Option<String>, u64)> {
    // 1) --host / PROBE_HOST（最高）
    if let Some(h) = &cli.host {
        return Ok((Some(h.clone()), cli.timeout));
    }
    let cfg = SophonConfig::load()?;
    // 2) --board 别名
    if let Some(name) = &cli.board {
        let b = cfg
            .board(name)
            .ok_or_else(|| anyhow!("别名 '{}' 在 {} 未找到", name, display_path()))?;
        let t = b.timeout.unwrap_or(cli.timeout);
        return Ok((Some(b.host.clone()), t));
    }
    // 3) 配置 [default]
    if let Some(d) = &cfg.default {
        let t = d.timeout.unwrap_or(cli.timeout);
        return Ok((Some(d.host.clone()), t));
    }
    // 4) 无远程地址，走本地 unix socket
    Ok((None, cli.timeout))
}

/// config 子命令：直接操作配置文件。
fn run_config(sub: &ConfigCmd) -> Result<()> {
    let path = SophonConfig::path()?;
    match sub {
        ConfigCmd::Path => {
            println!("{}", config::expand_home(&path));
            Ok(())
        }
        ConfigCmd::List => {
            let cfg = SophonConfig::load()?;
            println!("配置文件: {}", config::expand_home(&path));
            if let Some(d) = &cfg.default {
                println!(
                    "[default]  host={}  timeout={}",
                    d.host,
                    d.timeout.unwrap_or(30)
                );
            } else {
                println!("[default]  （未设）");
            }
            if cfg.boards.is_empty() {
                println!("（无别名，用 sophonctl config add <name> <host> 添加）");
            } else {
                println!("别名:");
                for (name, b) in &cfg.boards {
                    let default_tag = cfg
                        .default
                        .as_ref()
                        .map(|d| d.host == b.host && d.timeout == b.timeout)
                        .unwrap_or(false);
                    println!(
                        "  {}{}  host={}  timeout={}",
                        name,
                        if default_tag { " (==default)" } else { "" },
                        b.host,
                        b.timeout.unwrap_or(30)
                    );
                }
            }
            Ok(())
        }
        ConfigCmd::Add {
            name,
            host,
            timeout,
            default,
        } => {
            let mut cfg = SophonConfig::load()?;
            let board = config::BoardConfig {
                host: host.clone(),
                timeout: *timeout,
            };
            cfg.boards.insert(name.clone(), board);
            if *default {
                cfg.default = Some(config::BoardConfig {
                    host: host.clone(),
                    timeout: *timeout,
                });
            }
            cfg.save()?;
            println!("已保存别名 '{}' → {}", name, host);
            Ok(())
        }
        ConfigCmd::Rm { name } => {
            let mut cfg = SophonConfig::load()?;
            if cfg.boards.remove(name).is_some() {
                cfg.save()?;
                println!("已删除别名 '{}'", name);
                Ok(())
            } else {
                Err(anyhow!("别名 '{}' 不存在", name))
            }
        }
    }
}

fn display_path() -> String {
    config::expand_home(&SophonConfig::path().unwrap_or_default())
}

async fn print(
    client: &Client,
    method: &str,
    params: Option<Params>,
    raw: bool,
) -> Result<Option<i32>> {
    let v = client.call(method, params).await?;
    let stdout = std::io::stdout();
    let stderr = std::io::stderr();
    write_response(&v, raw, &mut stdout.lock(), &mut stderr.lock())
}

/// 输出 RPC 响应。
///
/// 命令和插件执行结果统一是 `{exit, stdout, stderr}`。默认把它们还原为普通
/// 命令行输出；其余 RPC 响应仍使用易读的 JSON。`--raw` 始终保留紧凑 JSON，
/// 以便脚本按原协议消费。
fn write_response(
    value: &serde_json::Value,
    raw: bool,
    stdout: &mut impl Write,
    stderr: &mut impl Write,
) -> Result<Option<i32>> {
    if raw {
        writeln!(stdout, "{value}")?;
        return Ok(command_result(value).and_then(|(exit, _, _)| exit));
    }

    if let Some((exit, command_stdout, command_stderr)) = command_result(value) {
        stdout.write_all(command_stdout.as_bytes())?;
        stderr.write_all(command_stderr.as_bytes())?;
        return Ok(exit);
    }

    writeln!(stdout, "{}", serde_json::to_string_pretty(value)?)?;
    Ok(None)
}

/// 仅识别执行器约定的完整结果对象，避免把恰好带有同名字段的普通查询误当成命令输出。
fn command_result(value: &serde_json::Value) -> Option<(Option<i32>, &str, &str)> {
    let object = value.as_object()?;
    let exit = object
        .get("exit")?
        .as_i64()
        .and_then(|code| i32::try_from(code).ok());
    let stdout = object.get("stdout")?.as_str()?;
    let stderr = object.get("stderr")?.as_str()?;
    Some((exit, stdout, stderr))
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use serde_json::json;

    use super::{plugin_parts, write_response};

    #[test]
    fn dynamic_plugin_parts_keep_each_argument_separate() {
        let parts = vec![
            OsString::from("servo"),
            OsString::from("servo"),
            OsString::from("0"),
            OsString::from("-2.0"),
        ];
        let (plugin, args) = plugin_parts(&parts).unwrap();
        assert_eq!(plugin, "servo");
        assert_eq!(args, vec!["servo", "0", "-2.0"]);
    }

    #[test]
    fn command_result_is_rendered_like_a_normal_command() {
        let response = json!({
            "exit": 0,
            "stdout": "usage: servo_ctrl.py [-h]\n\noptions:\n  -h, --help\n",
            "stderr": "",
        });
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();

        let exit = write_response(&response, false, &mut stdout, &mut stderr).unwrap();

        assert_eq!(exit, Some(0));
        assert_eq!(
            String::from_utf8(stdout).unwrap(),
            "usage: servo_ctrl.py [-h]\n\noptions:\n  -h, --help\n"
        );
        assert!(stderr.is_empty());
    }

    #[test]
    fn command_stderr_and_exit_code_are_preserved() {
        let response = json!({"exit": 3, "stdout": "", "stderr": "invalid action\n"});
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();

        let exit = write_response(&response, false, &mut stdout, &mut stderr).unwrap();

        assert_eq!(exit, Some(3));
        assert!(stdout.is_empty());
        assert_eq!(String::from_utf8(stderr).unwrap(), "invalid action\n");
    }

    #[test]
    fn raw_mode_keeps_compact_json() {
        let response = json!({"exit": 0, "stdout": "ok\n", "stderr": ""});
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();

        let exit = write_response(&response, true, &mut stdout, &mut stderr).unwrap();

        assert_eq!(exit, Some(0));
        assert_eq!(
            String::from_utf8(stdout).unwrap(),
            "{\"exit\":0,\"stderr\":\"\",\"stdout\":\"ok\\n\"}\n"
        );
        assert!(stderr.is_empty());
    }
}
