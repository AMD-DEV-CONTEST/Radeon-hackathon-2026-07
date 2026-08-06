# Case Log: 320 条模糊语义对抗门禁

## Goal

把三次真实用户失败从孤立回归扩展为可冻结、可复现、可在 Radeon Cloud 重跑的语义门禁，阻止“修一句、坏一句”。

## Dataset Contract

- 320 条合成查询，40 份合成混淆文档，10 个类别。
- 查询清单在修改核心检索前冻结，SHA-256 为 `ac65870e5ad9a59ea9ae0c743761d828adeaaa437e945b408a051337c5a0107f`。
- 覆盖单文件、清单、存在性、角色交集、否定、alternatives、错误年份/编号、笔记与澄清。
- 该集合是工程 holdout，不冒充 owner-approved blind gold；原有 60 条私有清单继续作为真实目录反向回归。

## Baseline

- 总通过率 42.8%，意图合同 54.4%。
- 单目标 Top-1 83.1%，多目标完整覆盖 0%。
- 拒答 87.5%，澄清 73.3%，错误自动选择 10 次。

## Root Causes

- 文件族规则把实验 1/2/3 当成版本副本合并。
- 清单与存在性只识别少量固定句式。
- 报告模板、指导书和完成版报告缺少角色层级。
- `Verilog/CPU/SQL` 等技术词被误当作课程身份证明。
- Linux 实验编号既可能充分定位，也可能仍需澄清，缺少条件化边界。

## Final Local Verification

- 320/320 合成 holdout 通过；所有核心指标 100%，错误自动选择 0。
- 77 项 Python 测试通过。
- 真实私有清单保持 37/37 单目标 Top-1、40/40 Recall@5、3/3 多目标完整覆盖、12/12 拒答、100% 澄清和自动选择精度。
- Championship check 通过。

## Radeon Status

旧 SSH 入口在 banner exchange 阶段超时，无法在本轮执行新的 GPU 调用。`scripts/run_radeon_holdout.sh` 已要求 LoRA、BGE 和 reranker 全部真实启用；任一组件回退都会失败。拿到新 SSH 地址后运行该脚本，再运行 Qwen3-14B 三角色法庭门禁。

## Residual Risk

- 合成矩阵由工程模板生成，不是独立人员提供的盲测。
- 私有标签仍需 owner 复核。
- 新 320 条清单尚未在当前 Radeon Cloud live stack 上完成复验。
