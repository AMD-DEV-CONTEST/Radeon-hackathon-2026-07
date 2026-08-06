# UAS Canvas — 明线前端原生客户端

## 定位
Windows 原生指挥舱，egui/eframe 实现。第一屏同时展示：
- Agent 实时列表（从 Orchestrator REST 拉取）
- 任务流（从 Orchestrator REST 拉取）
- 会议室 + 推理摘要
- 模型驾驶舱

## 网络
- ✅ 只读连接 Orchestrator REST API，启动后立即拉取一次，之后 5s 轮询
- ✅ 默认地址：`http://111.228.42.18:8000`
- ✅ 可用环境变量覆盖：`UAS_ORCHESTRATOR_URL`
- ❌ 不连接 Gateway WebSocket
- ❌ 不处理 token / API key / auth header
- ❌ 不展示原始 chain-of-thought

## 技术栈
- Rust 1.96.0 stable-x86_64-pc-windows-msvc
- egui 0.31 / eframe 0.31
- reqwest 0.12（blocking + 8s timeout）
- serde / serde_json

## 构建
```powershell
$env:RUSTUP_HOME = "D:\Rust\rustup"
$env:CARGO_HOME = "D:\Rust\cargo"
$env:Path = "D:\Rust\cargo\bin;$env:Path"
cd canvas-native
cargo build --release
```

可选自定义 Orchestrator：

```powershell
$env:UAS_ORCHESTRATOR_URL = "http://111.228.42.18:8000"
cargo run --release
```

## 版本
- v0.5.2: Orchestrator URL 环境变量 + 首次立即拉取 + package version 对齐
- v0.5.1: 裸数组反序列化修复 + 8s timeout + 折叠按钮修复
- v0.5.0: 实时数据驱动（reqwest）
- v0.4.0: Segoe UI 字体 + 卡片阴影
- v0.3.0: iOS 主题 + 折叠面板
