//! E2E 测试：真实 Unix socket transport 全链路。
//! 用 tempfile 当 socket 路径，避免与系统 /run 冲突。

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use daemon::accept_unix_loop;
use shared::ports::ShellRunner;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs, FakeShellRunner};

#[tokio::test]
async fn e2e_unix_ping_and_state() -> Result<()> {
    let cfg = Config::default();
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;
    app.orchestrator.collect_once().await;

    // 用 tempfile 目录放 socket。
    let dir = tempfile::tempdir()?;
    let sock = dir.path().join("probe.sock");
    let sock_str = sock.to_string_lossy().to_string();
    let _ = std::fs::remove_file(&sock);
    let listener = tokio::net::UnixListener::bind(&sock)?;
    let app_clone = Arc::clone(&app);
    tokio::spawn(async move { let _ = accept_unix_loop(listener, app_clone).await; });

    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(3))
        .unix(&sock_str)
        .await?;
    let v = client.call("ping", None).await?;
    assert_eq!(v["pong"], serde_json::json!(true));

    let v = client.call("get_state", None).await?;
    assert_eq!(v["thermal"]["zones"][0]["tempC"], serde_json::json!(52.0));
    app.cancel.cancel();
    Ok(())
}
