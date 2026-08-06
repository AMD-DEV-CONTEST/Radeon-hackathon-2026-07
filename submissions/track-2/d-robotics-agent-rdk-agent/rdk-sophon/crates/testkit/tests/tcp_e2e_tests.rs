//! E2E 测试：真实 TCP transport 全链路。
//! 起 TcpListener(127.0.0.1:0) + daemon::build_test_app + 真实 TCP client，
//! 验证 ping/get_state/exec_shell 在真实网络栈上的端到端行为。

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use daemon::accept_tcp_loop;
use shared::ports::ShellRunner;
use infra::Transport;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs, FakeShellRunner};

async fn spawn_test_daemon() -> (Arc<daemon::App>, std::net::SocketAddr, tokio::task::JoinHandle<()>) {
    let cfg = Config::default();
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;
    // 初始采集。
    app.orchestrator.collect_once().await;

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app_clone = Arc::clone(&app);
    let handle = tokio::spawn(async move {
        let _ = accept_tcp_loop(listener, app_clone).await;
    });
    (app, addr, handle)
}

#[tokio::test]
async fn e2e_tcp_ping() -> Result<()> {
    let (app, addr, _h) = spawn_test_daemon().await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(3))
        .tcp(&addr.to_string())
        .await?;
    let v = client.call("ping", None).await?;
    assert_eq!(v["pong"], serde_json::json!(true));
    app.cancel.cancel();
    Ok(())
}

#[tokio::test]
async fn e2e_tcp_get_state() -> Result<()> {
    let (app, addr, _h) = spawn_test_daemon().await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(3))
        .tcp(&addr.to_string())
        .await?;
    let v = client.call("get_state", None).await?;
    // FakeReader 注入 52°C。
    assert_eq!(v["thermal"]["zones"][0]["tempC"], serde_json::json!(52.0));
    app.cancel.cancel();
    Ok(())
}

#[tokio::test]
async fn e2e_tcp_exec_shell_denied() -> Result<()> {
    // 默认 shell disabled，exec_shell 应拒。
    let (app, addr, _h) = spawn_test_daemon().await;
    let client = client::ClientBuilder::new()
        .timeout(Duration::from_secs(3))
        .tcp(&addr.to_string())
        .await?;
    let mut map = serde_json::Map::new();
    map.insert("cmd".into(), serde_json::Value::String("echo hi".into()));
    let err = client
        .call("exec_shell", Some(shared::protocol::Params::Named(map)))
        .await
        .unwrap_err();
    assert!(matches!(err, client::ClientError::Server { .. }));
    app.cancel.cancel();
    Ok(())
}

#[tokio::test]
async fn e2e_tcp_telemetry_push() -> Result<()> {
    // interval=1s，连上后应收到 telemetry notification。
    let mut cfg = Config::default();
    cfg.telemetry.interval_secs = 1;
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app_clone = Arc::clone(&app);
    tokio::spawn(async move { let _ = accept_tcp_loop(listener, app_clone).await; });

    // 用底层 transport 连，收第一条 notification（telemetry）。
    let stream = tokio::net::TcpStream::connect(addr).await?;
    let peer = stream.peer_addr()?;
    let mut t = infra::TcpTransport::new(stream, peer);
    // 先发个 ping 让 session 建立订阅。
    let req = shared::protocol::JsonRpcMessage::new_request(shared::protocol::Id::Num(1), "ping", None);
    t.send(&req).await?;
    // 在 2.5s 内应收到 telemetry notification（无 id）。
    let got = tokio::time::timeout(Duration::from_millis(2500), async {
        loop {
            match t.recv().await? {
                Some(shared::protocol::JsonRpcMessage::Notification(n)) if n.method == "telemetry" => return Ok::<_, anyhow::Error>(n),
                _ => continue,
            }
        }
    })
    .await;
    assert!(got.is_ok(), "应在 2.5s 内收到 telemetry");
    app.cancel.cancel();
    Ok(())
}
