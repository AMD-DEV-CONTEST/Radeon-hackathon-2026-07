from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def value(mapping: dict[str, Any] | None, key: str, suffix: str = "") -> str:
    if mapping is None or key not in mapping:
        return "[待运行生成]"
    raw = mapping[key]
    if isinstance(raw, float):
        raw = f"{raw:.4f}"
    return f"{raw}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Chinese technical-report draft from run outputs")
    parser.add_argument("--input", default="outputs/radeon-run")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root = Path(args.input)
    expert = load_json(root / "expert" / "summary.json")
    robustness = load_json(root / "robustness" / "robustness.json")
    benchmark = load_json(root / "benchmarks" / "parallel.json")
    expert_summary = expert.get("summary") if expert else None
    runtime = expert.get("runtime") if expert else (benchmark.get("runtime") if benchmark else None)
    profiles = robustness.get("profiles", {}) if robustness else {}

    benchmark_rows = "| [待运行生成] | - | - |\n"
    if benchmark and benchmark.get("cases"):
        benchmark_rows = "".join(
            f"| {case['num_envs']} | {case['physics_steps_per_second']:.2f} | "
            f"{case['environment_steps_per_second']:.2f} |\n"
            for case in benchmark["cases"]
        )

    profile_rows = "".join(
        f"| {profile} | {value(profiles.get(profile), 'success_rate')} | "
        f"{value(profiles.get(profile), 'drop_rate')} | "
        f"{value(profiles.get(profile), 'recovery_success_rate')} |\n"
        for profile in ("nominal", "in_domain", "unseen")
    )
    report = f"""# 基于 AMD Radeon GPU 的鲁棒小快递抓取与分拣系统

## 1. 目标应用

本项目面向小型仓储和教学场景，在 Genesis 物理仿真中使用 Franka Panda 机械臂，将尺寸、质量、摩擦和初始位姿不同的小快递抓取并放入指定格口。系统强调可复现闭环、失败恢复和单张 Radeon GPU 上的仿真与策略执行。

## 2. 系统架构

系统由 Genesis 刚体仿真、RGB-D 与机器人状态观测、ACT/行为克隆策略接口、IK/PD 底层控制、安全状态机、专家数据采集和评估工具组成。当前结果中的确定性基线使用仿真真值专家；学习策略结果需在训练后补充。

## 3. 数据集

专家回合按照 LeRobotDataset 格式保存 RGB、Depth、非特权机器人状态、动作和任务文本。快递真值位姿单独保存为 `observation.privileged_state`，仅用于专家和评估，不输入最终视觉策略。

数据规模：[待采集后填写]\n
训练/验证/未见场景划分：[待训练后填写]

## 4. AMD Radeon GPU 与 ROCm

- GPU：{value(runtime, 'gpu_name')}
- 显存字节数：{value(runtime, 'gpu_total_memory_bytes')}
- ROCm：{value(runtime, 'rocm')}
- PyTorch：{value(runtime, 'torch')}
- Python：{value(runtime, 'python')}

项目在单张 GPU 上运行 Genesis 仿真、专家数据生成、后续策略训练/推理和并行吞吐测试。正式报告需补充 `rocprofv3` 或 PyTorch Profiler 结果，说明热点和具体优化前后差异。

## 5. 机器人能力结果

- 回合数：{value(expert_summary, 'episodes')}
- 成功率：{value(expert_summary, 'success_rate')}
- 首次成功率：{value(expert_summary, 'first_attempt_success_rate')}
- 恢复成功率：{value(expert_summary, 'recovery_success_rate')}
- 掉落率：{value(expert_summary, 'drop_rate')}
- P95 策略延迟：{value(expert_summary, 'p95_inference_latency_ms', ' ms')}
- 每小时成功快递数：{value(expert_summary, 'successful_parcels_per_hour')}

## 6. 鲁棒性

| 测试分布 | 成功率 | 掉落率 | 恢复成功率 |
| --- | ---: | ---: | ---: |
{profile_rows}
## 7. GPU 并行性能

| 并行环境数 | 物理步/秒 | 环境步/秒 |
| ---: | ---: | ---: |
{benchmark_rows}
## 8. 学习模型

[待填写：ACT、行为克隆或轻量 VLA 的开源来源、许可、输入输出、训练配置、检查点、训练曲线和推理结果。]

必须同时报告确定性专家与学习策略结果，避免将专家真值能力当作视觉模型能力。

## 9. 创新点与应用价值

- 将轻量学习策略与模型外部的 IK、PD、安全限制和失败恢复组合，降低策略失误的实际影响。
- 使用明确的未见尺寸、质量、摩擦和延迟条件评估，而不只展示单个成功视频。
- 同时交付审计轨迹、LeRobotDataset、随机种子、硬件信息和原始性能结果。

## 10. 上游贡献

[待填写：比赛期间向 Genesis、LeRobot 或 ROCm 相关项目提交的问题、修复、文档或 PR。]

## 11. 交付物

- 项目源代码与固定上游提交
- Radeon/ROCm Dockerfile
- 完整中文与英文 README
- 配置、随机种子、JSONL 轨迹和 LeRobotDataset
- 鲁棒性及 GPU 并行性能原始结果
- 3–5 分钟演示视频

## 12. 团队成员与贡献

[待填写团队成员法定姓名、角色和具体贡献。]
"""

    output = Path(args.output) if args.output else root / "technical_report_draft.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8", newline="\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
