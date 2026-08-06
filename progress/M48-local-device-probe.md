# M48 · 本机计算设备探测（ROCm/CUDA 面补齐）

- **日期**：2026-08-06
- **背景**：用户指令「ROCm CUDA 注入之类的也都看看」。核查发现 ROCm/CUDA 的**选择**已做好（训练页 accelerator 选择 + 算力节点管理 + 推理页设备徽章），但缺「选节点时看不到本机到底有没有可用 GPU」——选了 ROCm 实际是 CPU 就白选。
- **完成了什么**：
  - 后端：`apps/realtime/api/remote_compute.py` 新增 `GET /api/remote_compute/device`——本机计算设备探测。**安全关键**：gfx1151 栈上 in-process 触碰 torch.cuda 可硬崩解释器（SIGSEGV，M10 教训），探测在隔离子进程跑，崩了只死子进程（复用 setup.py `_probe_rocm` 的模式）。返回 `{ok, accelerator: rocm|cuda|cpu, device_name, message}`，按设备名粗判 AMD（ROCm）vs NVIDIA（CUDA）。
  - 前端：`LocalTrainingOptions` 节点列表下方加「探测本机 GPU」按钮 + 结果行（`本机 AMD · ROCm ✓ Radeon 8060S` 或 `本机无可用 GPU（CPU only）`），点按才探测（torch import 慢，不挂页面加载）。
- **解决了什么**：用户选算力节点前能看到本机真实计算能力，ROCm/CUDA 选择不再凭猜。诚实边界：探测的是 realtime 所在机器，远端节点（GB10/云 GPU）无法探测（代码注释写明）。
- **关键命令**：`py_compile` ✓；端点功能测试（真实 venv python 跑子进程探测）→ 返回干净 JSON（本机未 source rocm_env 时如实报 CPU）✓；前端 tsc 干净（仅 1 个历史遗留 FormField 错误，行号 157→200，非本轮引入）。
- **最终结果**：已提交。部署时随 realtime 容器一起上线（realtime 重建已含此端点）。
- **下一步**：v2 主线继续（runtime 内容丰富或功能改进）；部署重建仍等用户确认。
