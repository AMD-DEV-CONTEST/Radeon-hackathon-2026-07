# 🚀 AMD Radeon Cloud（官方免费 GPU）申请与使用指引

> **为什么用**：本机是 NVIDIA 卡，赛道 2 的 40 分（AMD 平台优化）必须在 AMD GPU 上出真数据。
> RC 是 AMD 官方云平台，**比赛期间不消耗积分**（群里官方确认），注册送 10~100 小时免费算力。
> 平台无需翻墙（中文站本地化）。

---

## 🟢 快路径：实例已就绪（8/6 状态）

**你的 Radeon Cloud 实例已经在运行了**（`u-7102-1179e4d5`，Qwen3.6-35B-A3B + llama.cpp/Vulkan）。

1. 浏览器打开：**https://developer.amd.com.cn/radeon/instances/u-7102-1179e4d5/lab**
   （若提示登录，用微信/手机号登录后自动进入）
2. 在文件列表里会看到官方 workshop 笔记本 `hermes-agent-vllm-local-serving-radeon-workshop.ipynb`
   → 打开 → **Run All** → 启动模型推理服务
3. 再打开我上传的 **`private-rag-agent-benchmark.ipynb`** → **Run All**
   → 自动输出 `rocminfo` / `rocm-smi` / tokens/s 基准
4. 把每格输出截图存到本机 `benchmarks/`，填进 README 性能表即可

> 若 workshop 服务没启动成功，再走下面的完整流程用 Terminal 跑 `deploy_rc.sh`。

---

## ⏱️ 你需要操作的部分（约 10 分钟）

### 第 1 步：登录 AMD AI 开发者计划
打开 **https://developer.amd.com.cn/login?source=91kadjjnI**

登录方式三选一（**微信登录最方便**，一键直达；也可手机号/邮箱/魔搭）：
- 微信扫码 → 首次会跳转注册表单，填姓名 + 邮箱/手机号 + 验证码
- 登录后进"会员中心"补全：**个人基础信息 → 项目环境与偏好 → 学术身份**
- 提交后获得 **100 积分**（1 积分 = 1 小时 GPU）

> 💡 如果你之前报名比赛时已经注册过，直接登录即可，积分可能已到账。

### 第 2 步：进入 Radeon Cloud 云算力
在开发者中心首页点进 **AMD 开发者云**（或直接访问 **https://developer.amd.com.cn/radeon/**）

### 第 3 步：创建实例
1. 页面选模板（推荐 **ROCm + PyTorch**，或 **vLLM** 示例、**AgenticAI** 示例）
2. 点 **Launch / 启动**，等 3~5 分钟直到进度 100%
3. 出现 **"打开笔记本 / Open Notebook"** 按钮，点进去
4. 进入的是 **Jupyter 环境**（浏览器里操作，预装 ROCm + PyTorch，有 AMD GPU）

> 群聊里有人 ssh 连不上，是因为 **RC 实例没装 sshd**——不需要 ssh，直接用浏览器里的 Notebook/Terminal 即可。

### 第 4 步：打开 Terminal 跑部署脚本
在 Jupyter 里点 **New → Terminal**，然后：

```bash
# 先把自己项目的代码传上去（见下方"上传代码"），然后：
bash deploy_rc.sh
```

---

## 📤 上传代码到 RC（二选一）

**方式 A：直接从 GitHub 拉**（推荐，最快）
```bash
git clone <你的仓库地址>
cd private-rag-agent
```
（前提：先把本项目推到 GitHub，见文末"提交作品"）

**方式 B：Jupyter 上传**
- 在 Jupyter 文件列表页点 **Upload**，把整个项目文件夹压缩成 zip 上传
- 上传后解压：`unzip private-rag-agent.zip`

---

## ✅ 部署后能做什么

`bash deploy_rc.sh` 会依次：
1. 检测 AMD GPU（amd-smi / rocmsmi）
2. 确认/安装 **vLLM (ROCm)**
3. 安装本项目依赖
4. **vLLM 启动 Qwen3-8B 推理服务**（后台，端口 8000）
5. 把 config.yaml 切换到 vLLM 后端
6. 跑通一次真实 AMD GPU 推理，打印结果

然后在工作区：
```bash
python main.py ingest data/docs/     # 导入文档
python main.py ask '我的项目用了什么技术栈？'  # RAG 问答（真实 AMD GPU 推理）
python benchmarks/bench_amd.py       # 跑 AMD GPU 性能基准 → 拿 40 分数据
```

---

## 📊 拿满 40 分要提交的证据（在 RC 上生成）

| 证据 | 命令 | 用途 |
|---|---|---|
| GPU 型号截图 | `amd-smi` / `rocm-smi` | 证明跑在 AMD GPU 上 |
| 推理速度 | `python benchmarks/bench_amd.py` | tokens/s 对比 |
| 量化对比 | vLLM 用 AWQ 量化模型 | 显存/速度优化 |
| ROCm 日志 | `rocminfo` 输出 | ROCm 适配证明 |
| 更大模型 | 把 deploy_rc.sh 里 `VLLM_MODEL` 改成 `Qwen/Qwen3-14B-AWQ` | 展示 AMD 能跑大模型 |

---

## ⚠️ 常见问题

| 问题 | 解决 |
|---|---|
| ssh 连不上 | 不需要 ssh，用浏览器里的 Jupyter Terminal |
| 实例 launch 报错 | 删掉 template 重建（群里官方这么建议） |
| vLLM 显存不够 | `--gpu-memory-utilization 0.85` 已设置；换小模型或 AWQ 量化 |
| 上传慢 | 用 GitHub clone，别传大 zip |
| 积分不够 | 活动期注册送 100 小时；魔搭社区有任务可拿更多（最高 1000+ 小时） |

---

## 📁 本目录已准备好的文件

| 文件 | 作用 |
|---|---|
| `deploy_rc.sh` | RC 一键部署（vLLM + 项目） |
| `docker-compose.yml` | 一键容器化部署（离线部署能力证据） |
| `Dockerfile.app` | compose 用的轻量应用镜像 |
| `Dockerfile` | ROCm 容器（备用） |
| `agent/llm.py` | 已支持 vLLM 后端 |
| `benchmarks/bench_amd.py` | AMD 基准测试 |
| `README.md` | 项目说明（提交用） |
