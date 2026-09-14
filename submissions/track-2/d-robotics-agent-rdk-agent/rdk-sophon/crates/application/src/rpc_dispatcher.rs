//! RpcDispatcher：JSON-RPC 消息分发。把 method 路由到对应用例，
//! domain 返回领域类型后用 serde_json::to_value 转 Value 包进 Response。
//! 从原 executor::dispatch + methods::State::call 移入。

use std::sync::Arc;
use std::time::Duration;

use shared::protocol::{Error, ErrorCode, JsonRpcMessage, Params};

use crate::audit::AuditLog;
use crate::collection_orchestrator::CollectionOrchestrator;
use domain::{CommandPolicy, StateService};
use shared::ports::{PluginError, PluginRunner, ShellRunner};

/// 分发结果：Response 要回发；NoReply 表示是 notification 或别人的响应，不回。
pub enum DispatchOutcome {
    Response(JsonRpcMessage),
    NoReply,
}

pub struct RpcDispatcher {
    pub orchestrator: Arc<CollectionOrchestrator>,
    pub state: Arc<StateService>,
    pub command_policy: CommandPolicy,
    pub shell_runner: Arc<dyn ShellRunner>,
    /// 动态控制插件执行端口，由 daemon 注入真实目录扫描器或禁用实现。
    pub plugin_runner: Arc<dyn PluginRunner>,
}

impl RpcDispatcher {
    pub fn new(
        orchestrator: Arc<CollectionOrchestrator>,
        state: Arc<StateService>,
        command_policy: CommandPolicy,
        shell_runner: Arc<dyn ShellRunner>,
        plugin_runner: Arc<dyn PluginRunner>,
    ) -> Self {
        Self {
            orchestrator,
            state,
            command_policy,
            shell_runner,
            plugin_runner,
        }
    }

    /// 分发一条消息。
    pub async fn dispatch(
        &self,
        msg: JsonRpcMessage,
        source: &str,
        audit: &AuditLog,
    ) -> DispatchOutcome {
        match msg {
            JsonRpcMessage::Request(req) => {
                let id = req.id.clone();
                let result = self.call(&req.method, req.params, source, audit).await;
                let resp = match result {
                    Ok(v) => JsonRpcMessage::new_response(id, v),
                    Err(e) => JsonRpcMessage::new_error(id, e),
                };
                DispatchOutcome::Response(resp)
            }
            JsonRpcMessage::Notification(_) | JsonRpcMessage::Response(_) => {
                DispatchOutcome::NoReply
            }
        }
    }

    /// 方法表：把 method 路由到用例。新增能力在此扩展 match。
    async fn call(
        &self,
        method: &str,
        params: Option<Params>,
        source: &str,
        audit: &AuditLog,
    ) -> Result<serde_json::Value, Error> {
        match method {
            // ---- 状态拉取：domain 返回领域类型 → serde 转 Value ----
            "get_state" => Ok(serde_json::to_value(&self.state.get_state().await)
                .unwrap_or(serde_json::json!({}))),
            "get_thermal" => Ok(serde_json::to_value(&self.state.get_thermal().await)
                .unwrap_or(serde_json::Value::Null)),
            "get_cpu" => Ok(serde_json::to_value(&self.state.get_cpu().await)
                .unwrap_or(serde_json::Value::Null)),
            "get_memory" => Ok(serde_json::to_value(&self.state.get_memory().await)
                .unwrap_or(serde_json::Value::Null)),
            "get_disk" => Ok(serde_json::to_value(&self.state.get_disk().await)
                .unwrap_or(serde_json::Value::Null)),
            "get_net" => Ok(serde_json::to_value(&self.state.get_net().await)
                .unwrap_or(serde_json::Value::Null)),
            "get_bpu" => Ok(serde_json::to_value(&self.state.get_bpu().await)
                .unwrap_or(serde_json::Value::Null)),

            // ---- 控制 ----
            "refresh_state" => {
                let ts = self.orchestrator.refresh(audit, source).await;
                Ok(serde_json::json!({"ok": true, "ts": ts}))
            }
            "ping" => Ok(
                serde_json::json!({"pong": true, "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)}),
            ),

            // ---- shell 执行（受 CommandPolicy 策略约束）----
            "exec_shell" => self.exec_shell(params, source, audit).await,
            "plugin.list" => self.list_plugins().await,
            "plugin.invoke" => self.invoke_plugin(params, source, audit).await,

            other => Err(Error::new(
                ErrorCode::MethodNotFound,
                format!("unknown method: {other}"),
            )),
        }
    }

    async fn exec_shell(
        &self,
        params: Option<Params>,
        source: &str,
        audit: &AuditLog,
    ) -> Result<serde_json::Value, Error> {
        // 取 cmd 参数（命名参数）。
        let cmdline = match params {
            Some(Params::Named(m)) => m
                .get("cmd")
                .and_then(|v| v.as_str())
                .ok_or_else(|| Error::new(ErrorCode::InvalidParams, "missing `cmd` string param"))?
                .to_string(),
            _ => {
                return Err(Error::new(
                    ErrorCode::InvalidParams,
                    "exec_shell expects named params with `cmd`",
                ))
            }
        };
        // 策略判定（纯逻辑，零 IO）。
        self.command_policy.check(&cmdline)?;
        // 真实执行（infra ShellRunner）。
        let started = std::time::Instant::now();
        let timeout = Duration::from_secs(self.command_policy.timeout_secs);
        let result = self.shell_runner.run(&cmdline, timeout).await;
        let outcome_label = match &result {
            Ok(out) => {
                format!(
                    "{} exit={}",
                    if out.exit == Some(0) { "ok" } else { "nonzero" },
                    out.exit.unwrap_or(-1)
                )
            }
            Err(e) => {
                format!("error: {e}")
            }
        };
        audit.record(crate::audit::AuditEntry {
            ts: AuditLog::now_ts(),
            source: source.to_string(),
            method: "exec_shell".into(),
            args: cmdline.chars().take(200).collect(),
            outcome: outcome_label,
            duration_ms: started.elapsed().as_millis() as u64,
        });
        match result {
            Ok(out) => Ok(serde_json::json!({
                "exit": out.exit,
                "stdout": out.stdout,
                "stderr": out.stderr,
            })),
            Err(shared::ports::ShellError::Timeout { secs }) => Err(Error::new(
                ErrorCode::Timeout,
                format!("command timed out ({secs}s)"),
            )),
            Err(e) => Err(Error::new(ErrorCode::ExecError, e.to_string())),
        }
    }

    /// 返回动态插件清单，供 CLI 补足 clap 无法静态生成的帮助信息。
    async fn list_plugins(&self) -> Result<serde_json::Value, Error> {
        let plugins = self.plugin_runner.list().await.map_err(plugin_error)?;
        Ok(serde_json::to_value(plugins).unwrap_or_else(|_| serde_json::json!([])))
    }

    /// 解析参数、调用插件端口并记录审计。用户参数始终保持数组形态，不拼接 shell 字符串。
    async fn invoke_plugin(
        &self,
        params: Option<Params>,
        source: &str,
        audit: &AuditLog,
    ) -> Result<serde_json::Value, Error> {
        let map = match params {
            Some(Params::Named(map)) => map,
            _ => {
                return Err(Error::new(
                    ErrorCode::InvalidParams,
                    "plugin.invoke expects named params",
                ))
            }
        };
        let plugin = map
            .get("plugin")
            .and_then(|value| value.as_str())
            .ok_or_else(|| Error::new(ErrorCode::InvalidParams, "missing `plugin` string param"))?;
        let args = map
            .get("args")
            .and_then(|value| value.as_array())
            .ok_or_else(|| {
                Error::new(
                    ErrorCode::InvalidParams,
                    "missing `args` string array param",
                )
            })?
            .iter()
            .map(|value| {
                value.as_str().map(str::to_string).ok_or_else(|| {
                    Error::new(ErrorCode::InvalidParams, "`args` must contain only strings")
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let started = std::time::Instant::now();
        let result = self.plugin_runner.invoke(plugin, &args).await;
        let outcome = match &result {
            Ok(output) if output.exit == Some(0) => "ok".to_string(),
            Ok(output) => format!("nonzero exit={}", output.exit.unwrap_or(-1)),
            Err(error) => format!("error: {error}"),
        };
        audit.record(crate::audit::AuditEntry {
            ts: AuditLog::now_ts(),
            source: source.to_string(),
            method: "plugin.invoke".into(),
            args: format!("{} {}", plugin, args.join(" "))
                .chars()
                .take(200)
                .collect(),
            outcome,
            duration_ms: started.elapsed().as_millis() as u64,
        });
        let output = result.map_err(plugin_error)?;
        Ok(serde_json::json!({
            "exit": output.exit,
            "stdout": output.stdout,
            "stderr": output.stderr,
        }))
    }
}

fn plugin_error(error: PluginError) -> Error {
    match error {
        PluginError::NotFound(name) => {
            Error::new(ErrorCode::InvalidParams, format!("插件 '{name}' 不存在"))
        }
        PluginError::Timeout { secs } => {
            Error::new(ErrorCode::Timeout, format!("插件执行超时（{secs} 秒）"))
        }
        PluginError::Disabled => Error::new(ErrorCode::InvalidParams, "插件功能未启用"),
        other => Error::new(ErrorCode::ExecError, other.to_string()),
    }
}
