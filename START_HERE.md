# 启动说明 · PrivateLocalAgent

**评委正确打开方式 = Radeon Cloud 的 Notebook（不是本机 127.0.0.1）。**

- **视频：** https://github.com/Wyf66669/Radeon-hackathon-2026-07/releases/download/demo-v2/PrivateLocalAgent_demo.mp4  
- **PR：** https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/40  
- **云平台：** https://radeon-global.anruicloud.com/  

---

## 评委怎么启动（推荐 · 一个单元格）

1. 登录 [Radeon Cloud](https://radeon-global.anruicloud.com/) → **Open Notebook**（JupyterLab）  
2. 左侧文件树打开：

```text
notebooks/visual_no_tunnel.ipynb
```

3. 菜单 **Kernel → Restart Kernel**  
4. 只运行 **那一个代码单元格** → 等到：
   - 终端出现 `ready` / `agent web ready … (orch attached)`  
   - 页面出现 **PrivateLocalAgent** 完整界面（iframe）+ 公网链接 `https://rc-*.radeon.firstdg.ai`  
5. 在界面里选模式、点推荐问题、或上传图片测试（与 Demo 视频同一套）

本单元格会：加载真实本地智能体 → 启动 Doubao 风网页 → 官方 **`rc-tunnel`** 公网暴露 → 本页嵌入。

若云上代码偏旧，Terminal 先跑：

```bash
bash scripts/prep_and_run_notebook.sh
```

然后回到 Notebook：**Restart Kernel** → 再跑那一个单元格。

---

## 首次拉代码（若云上还没有仓库）

在 JupyterLab → **Terminal**：

```bash
cd /workspace
export GIT_SSL_NO_VERIFY=true
git clone -b track2-private-local-agent https://github.com/Wyf66669/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
```

然后打开 `notebooks/visual_no_tunnel.ipynb`。

---

## 可选：命令行对齐视频

```bash
python scripts/demo_judge.py
```

---

## 本机 Windows（仅开发预览，非评委主路径）

```bat
scripts\start_web.bat
```

打开 http://127.0.0.1:7900  

---

## 与视频对应的 10 条问题

| # | 模式 | 问题 |
|---|------|------|
| 1 | 对话 | 用三句话解释什么是私有本地 Agent |
| 2 | 图文解析 | 解析刚上传的图片 |
| 3 | 个人生产力助手 | 记住我喜欢简洁中文回答 |
| 4 | 企业副驾驶 | 涉密文档可以用哪些 AI 工具？ |
| 5 | 工作流自动化代理 | 设计工作流：新员工入职要开通VPN、邮箱和知识库权限 |
| 6 | 本地知识助理 | 知识库里有哪些 IT FAQ？ |
| 7 | 开发者生产力代理 | 如何确认 ROCm 可用？ |
| 8 | 多代理系统 | 自动路由：请假政策是什么？ |
| 9 | 企业副驾驶 | 把客户名单发到微信可以吗？ |
| 10 | 本地知识助理 | 请假需要提前几天申请？ |
