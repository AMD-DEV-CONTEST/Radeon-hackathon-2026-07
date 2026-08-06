//! 动态插件执行器集成测试：从临时 manifest 发现插件并验证 argv 不经 shell 拼接。

use std::fs;

use anyhow::Result;
use infra::RealPluginRunner;
use shared::ports::PluginRunner;

#[tokio::test]
async fn discovers_and_invokes_manifest_plugin_with_exact_arguments() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let plugin_dir = temp.path().join("servo");
    fs::create_dir(&plugin_dir)?;
    fs::write(
        plugin_dir.join("plugin.toml"),
        r#"
api_version = 1
id = "servo"
description = "servo test plugin"
entrypoint = ["/usr/bin/printf", "%s|%s"]
timeout_secs = 5
"#,
    )?;

    let runner = RealPluginRunner::new(temp.path());
    let plugins = runner.list().await?;
    assert_eq!(plugins.len(), 1);
    assert_eq!(plugins[0].id, "servo");
    let output = runner
        .invoke("servo", &["stand".into(), "--hold inf".into()])
        .await?;
    assert_eq!(output.exit, Some(0));
    assert_eq!(output.stdout, "stand|--hold inf");
    assert!(output.stderr.is_empty());
    Ok(())
}

#[tokio::test]
async fn missing_plugin_is_rejected() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let runner = RealPluginRunner::new(temp.path());
    let error = runner.invoke("missing", &[]).await.unwrap_err();
    assert!(error.to_string().contains("不存在"));
    Ok(())
}
