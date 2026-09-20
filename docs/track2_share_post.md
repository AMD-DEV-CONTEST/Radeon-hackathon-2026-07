# 【Track 2 参赛作品分享】AMD ROCm Local Quantitative Investment Assistant

一个完全本地部署的量化投资 Agent：自然语言 → 策略 DSL → 确定性验证 → 回测 → 独立风险 Agent 否决，全链路跑在 AMD Radeon GPU（ROCm 7.2.1）上，不依赖任何云端模型。

🧠 Qwen2.5-7B + LoRA 微调，vLLM 本地推理（32K 上下文）
✅ 285 项测试通过、24/24 国内市场评测、token 准确率 98.1%
🔒 数据/推理不出本地；风险 Agent 有独立否决权
🎮 三条验证路径：①在线 Open WebUI 注册即聊 ②一条命令本地复现（python demos/run_track2_demo.py，无需 GPU）③4分23秒实机演示视频

📎 仓库：github.com/gxinxing/Radeon-hackathon-2026-07
📎 PR：github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/68
📎 在线演示：https://autoquant-landing.vercel.app（展示页）
📎 Open WebUI：https://bones-fans-imposed-rio.trycloudflare.com（注册即用）
📎 模型权重（魔搭社区）：https://modelscope.cn/models/gxinxing/qwen-trader-cn-merged
