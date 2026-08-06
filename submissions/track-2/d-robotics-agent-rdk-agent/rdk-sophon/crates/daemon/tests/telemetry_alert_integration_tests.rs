//! 集成测试：telemetry 周期推送 + alert 阈值告警。
//! 用短 interval 配置，订阅 broadcaster，断言收到 telemetry/alert notification。

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use daemon::config::Config;
use shared::protocol::JsonRpcMessage;
use testkit::common::{make_fake_hrut, make_fake_proc, make_fake_sysfs, FakeShellRunner};

#[tokio::test]
async fn telemetry_pushed_on_interval() -> Result<()> {
    // interval=1s，连接后 1.5s 内应收到 telemetry notification。
    let mut cfg = Config::default();
    cfg.telemetry.interval_secs = 1;
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn shared::ports::ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;

    // 订阅广播。
    let mut rx = app.broadcaster.subscribe();
    // 等一个 telemetry tick（interval=1s，约 1-2s 内）。
    let got = tokio::time::timeout(Duration::from_millis(2500), async {
        loop {
            match rx.recv().await {
                Ok(JsonRpcMessage::Notification(n)) if n.method == "telemetry" => return n,
                _ => continue,
            }
        }
    })
    .await;
    assert!(got.is_ok(), "应在 2.5s 内收到 telemetry notification");
    Ok(())
}

#[tokio::test]
async fn alert_emitted_when_thermal_over_threshold() -> Result<()> {
    // 阈值设为 10°C（FakeReader 注入 52°C/61°C，必然超阈值），interval=1s。
    let mut cfg = Config::default();
    cfg.telemetry.interval_secs = 1;
    cfg.alerts.temp_c = 10.0;
    let sysfs = Arc::new(make_fake_sysfs());
    let proc_r = Arc::new(make_fake_proc());
    let hrut = Arc::new(make_fake_hrut());
    let runner: Arc<dyn shared::ports::ShellRunner> = Arc::new(FakeShellRunner::new());
    let handles = daemon::build_test_app(&cfg, sysfs, proc_r, hrut, runner).unwrap();
    let app = handles.app;

    let mut rx = app.broadcaster.subscribe();
    let got = tokio::time::timeout(Duration::from_millis(2500), async {
        loop {
            match rx.recv().await {
                Ok(JsonRpcMessage::Notification(n)) if n.method == "alert" => return n,
                _ => continue,
            }
        }
    })
    .await;
    assert!(got.is_ok(), "thermal 超 10°C 应产 alert notification");
    Ok(())
}
