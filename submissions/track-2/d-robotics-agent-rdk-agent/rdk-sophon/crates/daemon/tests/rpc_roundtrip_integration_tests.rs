//! 集成测试：RPC 全链路往返（in-memory transport，不起真实端口）。
//! 用 daemon::build_test_app + FakeReader 装配，StubTransport pair 驱动，
//! 验证 ping/get_state/exec_shell 从 client 到 dispatcher 到 domain 的完整路径。

use std::fs;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use infra::StubTransport;
use shared::protocol::Id;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs, FakeShellRunner};

/// 装配一个测试 App（假 infra）并返回 app。
fn build_test() -> Arc<daemon::App> {
    let cfg = Config::default();
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let shell_runner: Arc<dyn shared::ports::ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, shell_runner).unwrap();
    handles.app
}

#[tokio::test]
async fn ping_roundtrip() -> Result<()> {
    let app = build_test();
    // 等初始采集完成（写好 snapshot）。
    app.orchestrator.collect_once().await;

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

    // 客户端侧：发 ping，收响应。
    let client = client::Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));
    let v = client.call("ping", None).await?;
    assert_eq!(v["pong"], serde_json::json!(true));
    let _ = Id::Num(0);
    Ok(())
}

#[tokio::test]
async fn get_state_returns_fake_thermal() -> Result<()> {
    // FakeReader 注入 52°C/61°C，get_state 应含 thermal。
    let app = build_test();
    app.orchestrator.collect_once().await;

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

    let client = client::Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));
    let v = client.call("get_state", None).await?;
    let thermal = &v["thermal"];
    assert_eq!(thermal["zones"][0]["tempC"], serde_json::json!(52.0));
    Ok(())
}

#[tokio::test]
async fn exec_shell_denied_when_disabled() -> Result<()> {
    // 默认 shell.enabled=false，exec_shell 应返回 ShellDisabled 错误。
    let app = build_test();
    app.orchestrator.collect_once().await;

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

    let client = client::Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String("echo hi".into()));
    let err = client
        .call("exec_shell", Some(shared::protocol::Params::Named(map)))
        .await
        .unwrap_err();
    match err {
        client::ClientError::Server { code, .. } => {
            assert_eq!(code, shared::protocol::ErrorCode::ShellDisabled as i32);
        }
        _ => panic!("应为 ShellDisabled"),
    }
    Ok(())
}

#[tokio::test]
async fn plugin_rpc_discovers_and_invokes_a_manifest() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let servo_dir = temp.path().join("servo");
    fs::create_dir(&servo_dir)?;
    fs::write(
        servo_dir.join("plugin.toml"),
        r#"
api_version = 1
id = "servo"
description = "servo test plugin"
entrypoint = ["/usr/bin/printf", "%s"]
"#,
    )?;
    let mut cfg = Config::default();
    cfg.plugins.enabled = true;
    cfg.plugins.dir = temp.path().display().to_string();
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let shell_runner: Arc<dyn shared::ports::ShellRunner> = Arc::new(FakeShellRunner::new());
    let app = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, shell_runner)?.app;
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
    let client = client::Client::new(Box::new(client_side)).with_timeout(Duration::from_secs(2));
    let plugins = client.call("plugin.list", None).await?;
    assert_eq!(plugins[0]["id"], "servo");
    let mut params = serde_json::Map::new();
    params.insert("plugin".into(), serde_json::json!("servo"));
    params.insert("args".into(), serde_json::json!(["stand"]));
    let output = client
        .call(
            "plugin.invoke",
            Some(shared::protocol::Params::Named(params)),
        )
        .await?;
    assert_eq!(output["exit"], 0);
    assert_eq!(output["stdout"], "stand");
    Ok(())
}
