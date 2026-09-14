//! 集成测试：exec_shell 全链路。用 FakeShellRunner 测 deny/disabled/正常路径。
//! shell.enabled=true 的配置 + 假 runner，验证策略判定与执行结果回传。

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use shared::ports::ShellRunner;
use infra::StubTransport;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs, FakeShellRunner};

/// 装配一个 shell 开启的测试 App。
fn build_shell_enabled_app(runner: Arc<dyn ShellRunner>) -> Arc<daemon::App> {
    let mut cfg = Config::default();
    cfg.shell.enabled = true;
    cfg.shell.timeout_secs = 2;
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    handles.app
}

async fn call_exec(app: &Arc<daemon::App>, cmd: &str) -> Result<serde_json::Value, client::ClientError> {
    let (server_side, client_side) = StubTransport::pair();
    let dispatcher = Arc::clone(&app.dispatcher);
    let audit = app.audit.clone();
    let rx = app.broadcaster.subscribe();
    tokio::spawn(application::run_session(
        "stub".into(),
        Box::new(server_side),
        dispatcher,
        audit,
        rx,
    ));
    let client = client::Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(3));
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String(cmd.into()));
    client.call("exec_shell", Some(shared::protocol::Params::Named(map))).await
}

#[tokio::test]
async fn exec_returns_runner_output() -> Result<()> {
    // 假 runner 对 "echo hi" 返回 stdout "hi"。
    let runner = Arc::new(
        FakeShellRunner::new().with(
            "echo hi",
            shared::ports::ShellOutput { exit: Some(0), stdout: "hi\n".into(), stderr: String::new() },
        ),
    );
    let app = build_shell_enabled_app(runner);
    app.orchestrator.collect_once().await;
    let v = call_exec(&app, "echo hi").await?;
    assert_eq!(v["exit"], serde_json::json!(0));
    assert_eq!(v["stdout"], serde_json::json!("hi\n"));
    Ok(())
}

#[tokio::test]
async fn exec_denies_mkfs() -> Result<()> {
    // mkfs 在内置 deny 列表，即使 shell enabled 也拒。
    let app = build_shell_enabled_app(Arc::new(FakeShellRunner::new()));
    app.orchestrator.collect_once().await;
    let err = call_exec(&app, "mkfs /dev/sda1").await.unwrap_err();
    match err {
        client::ClientError::Server { code, .. } => {
            assert_eq!(code, shared::protocol::ErrorCode::ShellDenied as i32);
        }
        _ => panic!("应为 ShellDenied"),
    }
    Ok(())
}

#[tokio::test]
async fn exec_denies_rm_rf_root() -> Result<()> {
    let app = build_shell_enabled_app(Arc::new(FakeShellRunner::new()));
    app.orchestrator.collect_once().await;
    let err = call_exec(&app, "sudo rm -rf /").await.unwrap_err();
    match err {
        client::ClientError::Server { code, .. } => {
            assert_eq!(code, shared::protocol::ErrorCode::ShellDenied as i32);
        }
        _ => panic!("应为 ShellDenied"),
    }
    Ok(())
}
