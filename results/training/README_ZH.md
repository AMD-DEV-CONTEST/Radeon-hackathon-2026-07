# Historical training record

[English](README.md) | 中文

本记录来自原始本地checkpoint元数据与训练日志。大型checkpoint和600回合数据集作为外部制品管理，不在此重复存放。

## SmolVLA微调

| 字段 | 核验值 |
|---|---:|
| 数据集 | `demo/fruit_pick_dr_600ep`，600个成功episode |
| 最终step / batch size | 20,000 / 128 |
| Seed | 1000 |
| 保存间隔 | 2,000步 |
| 周期checkpoint | 10个（`002000`至`020000`） |
| Optimizer学习率 | 1e-4 |
| Scheduler warmup / decay | 1,000 / 30,000步 |
| 训练选择 | 冻结vision encoder；训练expert与state projection |
| 最终模型大小 | 906,712,520 bytes |
| 最终模型SHA256 | `a0e735af8bc127d103ba89b7c9a1fa1e94d025a4170403712cd6bf689038d99d` |

最终`training_step.json`记录`step=20000`、`num_processes=1`、`batch_size=128`。原始输出保留checkpoint状态，但没有逐步loss日志，因此本提交不虚构或反推loss曲线。

## Lift-only Residual SAC

| 字段 | 核验值 |
|---|---:|
| 最终step / warmup | 100,000 / 10,000 |
| Batch size / replay capacity | 256 / 500,000 |
| Seed采样范围 | 3000–4999 |
| 保存间隔 | 10,000步 |
| 周期checkpoint | 10个及`last.pt` |
| 状态 / 残差维度 | 62 / 9 |
| 训练日志完整episode | 361 |
| 训练期成功 | 169/361（46.8%） |
| 最后100个训练episode | 45/100 |
| 最终checkpoint大小 | 2,389,351 bytes |
| 最终checkpoint SHA256 | `f05fce079fbc5a057f90c5b97d06d7075a29f4252d05ff210425e4b2a00dce86` |

训练episode来自持续更新策略的在线SAC过程，不是held-out评估集。因此169/361和45/100仅是优化监控。正式结果仍是固定seeds 2000–2099上的配对评估：eager baseline 34/100，lift residual 43/100；该结果尚未独立seed验证。

## 迁移后脚本测试

两个训练入口均在AMD GPU上完成过一次临时1-step测试：SmolVLA完成数据/模型加载、forward、backward、optimizer update和checkpoint保存；Residual SAC完成Genesis场景构建、冻结策略加载、一次环境动作和checkpoint保存。临时产物已经删除，不计入正式训练结果。
