# Cloudflare 内网穿透（豆包风格网页）

界面只保留整页工作台（侧栏 + 「有什么我能帮你的吗？」+ 输入框），不再使用 Jupyter 控件条。

## 一键启动（推荐）

```bash
cd /workspace/Radeon-hackathon-2026-07
git checkout -- notebooks/private_agent_demo.ipynb
git pull origin track2-private-local-agent
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
python scripts/migrate_to_persistence.py
python scripts/run_cloudflare_tunnel.py
```

脚本会：

1. 启动 `scripts/web_http_demo.py`（`http://127.0.0.1:7900`）
2. 自动下载/调用 `cloudflared`
3. 打印公网地址：`https://xxxx.trycloudflare.com`

用浏览器打开该链接即可（手机/评委电脑都能访问）。

## 仅本地

```bash
python scripts/web_http_demo.py
# http://127.0.0.1:7900
```

## 说明

- Quick Tunnel **无需登录** Cloudflare 账号
- 终端需保持运行；关掉则链接失效
- 首次仍要加载本地模型，等终端出现 `[boot] ready`
- 侧栏可切换六大应用模式
