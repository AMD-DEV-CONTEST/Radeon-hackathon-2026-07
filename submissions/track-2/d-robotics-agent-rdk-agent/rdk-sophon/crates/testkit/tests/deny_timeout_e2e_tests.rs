//! E2E 测试：shell 执行的 deny 与超时，用真实 RealShellRunner。
//! deny：mkfs 被内置列表拦。超时：sleep 10 + timeout=1s 被 kill。

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use daemon::accept_tcp_loop;
use infra::RealShellRunner;
use shared::ports::ShellRunner;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs};

async fn spawn_shell_enabled_daemon(timeout_secs: u64) -> (Arc<daemon::App>, std::net::SocketAddr) {
    let mut cfg = Config::default();
    cfg.shell.enabled = true;
    cfg.shell.timeout_secs = timeout_secs;
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn ShellRunner> = Arc::new(RealShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;
    app.orchestrator.collect_once().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app_clone = Arc::clone(&app);
    tokio::spawn(async move { let _ = accept_tcp_loop(listener, app_clone).await; });
    (app, addr)
}

#[tokio::test]
async fn e2e_deny_mkfs() -> Result<()> {
    let (app, addr) = spawn_shell_enabled_daemon(5).await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(5))
        .tcp(&addr.to_string())
        .await?;
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String("mkfs /dev/sda1".into()));
    let err = client
        .call("exec_shell", Some(shared::protocol::Params::Named(map)))
        .await
        .unwrap_err();
    match err {
        client::ClientError::Server { code, .. } => {
            assert_eq!(code, shared::protocol::ErrorCode::ShellDenied as i32);
        }
        _ => panic!("应为 ShellDenied"),
    }
    app.cancel.cancel();
    Ok(())
}

#[tokio::test]
async fn e2e_timeout_kills_long_command() -> Result<()> {
    // timeout=1s，sleep 10 应被杀，返回 Timeout 错误。
    let (app, addr) = spawn_shell_enabled_daemon(1).await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(5))
        .tcp(&addr.to_string())
        .await?;
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String("sleep 10".into()));
    let err = client
        .call("exec_shell", Some(shared::protocol::Params::Named(map)))
        .await
        .unwrap_err();
    match err {
        client::ClientError::Server { code, .. } => {
            assert_eq!(code, shared::protocol::ErrorCode::Timeout as i32);
        }
        _ => panic!("应为 Timeout"),
    }
    app.cancel.cancel();
    Ok(())
}

#[tokio::test]
async fn e2e_exec_runs_real_command() -> Result<()> {
    // 真实执行 echo，stdout 应含 "hello"。
    let (app, addr) = spawn_shell_enabled_daemon(5).await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(5))
        .tcp(&addr.to_string())
        .await?;
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String("echo hello".into()));
    let v = client
        .call("exec_shell", Some(shared::protocol::Params::Named(map)))
        .await?;
    assert_eq!(v["exit"], serde_json::json!(0));
    assert!(v["stdout"].as_str().unwrap().contains("hello"));
    app.cancel.cancel();
    Ok(())
}
