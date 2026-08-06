# 技术报告：基于 SmolVLA + Qwen3-VL 的 YCB 物体颜色分类抓取放置系统

**（Radeon Hackathon 2026-07 Track 3 · Physical AI Challenge · AMD ROCm）**

## 1. 系统架构

本系统实现了一个**双视觉语言模型（VLM）驱动的全链路闭环**：Qwen3-VL-8B 负责上层感知与任务规划（颜色识别、目标选择），SmolVLA-450M 负责低层闭环运动控制（30Hz 实时策略），在 Genesis 物理引擎中完成 YCB 物体的颜色分类抓取放置。

```
┌────────────────────────────────────────────────────────────────┐
│                       全链路闭环架构                            │
│                                                                │
│  [世界相机]──RGB图像──►[Qwen3-VL-8B 感知与规划 (Stage C1)]     │
│    │                             │                            │
│    │                             ▼                            │
│    │                    {pick_object, place_color}            │
│    │                             │                            │
│    │                             ▼                            │
│  [世界/腕部相机]──观察──►[SmolVLA-450M 策略 (Stage B)]         │
│    │                             │                            │
│    │                             ▼                            │
│    │                    {arm_action, finger_action}           │
│    │                             │                            │
│    └──────────物理执行 ◄─────────┘                            │
│              (Genesis 刚体物理)                                │
│                    │                                          │
│                    ▼                                          │
│             [check_success 判定]                              │
└────────────────────────────────────────────────────────────────┘
```

### 模块组成
| 模块 | 文件 | 功能 |
|------|------|------|
| 场景构建 | `build_scene.py` | Genesis 场景：Franka 机器人 + YCB 物体 + 5-box 凹槽容器 |
| 配置 | `scene_config.py` | YCB 物体布局、颜色映射、容器配置、几何物体定义 |
| 专家演示 | `sk_grasp_demo.py` | 脚本化抓取放置（录制训练数据） |
| 数据集录制 | `record_dataset_parallel.py` | 多环境并行录制 + 批级 NaN 恢复 |
| 策略训练 | `train_policy.py` | SmolVLA 微调（LeRobot） |
| 闭环评估 | `eval_policy.py` | SmolVLA 闭环推理 + Qwen3-VL 规划/验证 |
| 视觉感知 | `qwen_planner.py` | Qwen3-VL 颜色识别与任务规划（Stage C1） |
| 视觉验证 | `qwen_verifier.py` | Qwen3-VL 放置结果验证（Stage C2） |

## 2. AMD ROCm 计算资源使用

### 训练配置与耗时
| 项目 | 值 |
|------|-----|
| 训练框架 | LeRobot 0.6.0 + SmolVLA-450M |
| 训练步数 | 10,000 步 |
| Batch size | 64 |
| 数据规模 | 227 episodes（162,722 帧） |
| 训练耗时 | **3 小时 23 分**（12:43 → 16:06） |
| 单步耗时 | ~1.2 秒/步 |

### GPU 资源利用率（rocm-smi 实时采样，1055 采样点）
| 指标 | 平均 | 峰值 |
|------|------|------|
| **GPU 利用率** | **99.7%** | 100% |
| **显存占用** | ~16.7 GB | 16.7 GB |
| **总显存** | 51.5 GB | - |
| **功耗** | 228 W | 307 W |

**关键结论**：
- GPU 利用率接近饱和（99.7%），说明**计算是主要瓶颈**，而非数据加载或 I/O
- 显存占用仅 16.7/51.5 GB（32%），显存充裕
- 功耗峰值 307W，AMD GPU 满负荷运行

### 加速调优实证
| 配置 | 单步耗时 | 结论 |
|------|---------|------|
| batch=64, fp32 | 1.28 s/step | 基线 |
| batch=64, bf16 | 1.28 s/step | **无加速**（ROCm bf16 路径与 fp32 相当） |
| batch=128, bf16 | 2.66 s/step | **更慢**（每步梯度计算翻倍） |

**结论**：SmolVLA 训练瓶颈是模型推理+梯度计算，加大 batch 或 bf16 均无法提速。batch=64+fp32 为最优配置。

## 3. 创新点

1. **双 VLM 分层闭环架构**：Qwen3-VL-8B（大模型）负责上层的视觉感知与任务规划，SmolVLA-450M（轻量策略）负责低层 30Hz 实时控制。将昂贵的视觉推理从实时控制环中解耦，兼顾精度与实时性。

2. **几何物体可靠性工程**：通过实测 Franka 夹爪最大张开（7.62cm）与 YCB 物体尺寸，确立"物体短轴 ≤6cm"的可靠抓取边界。将不可靠的圆滑物体（apple/orange/strawberry）替换为红色几何立方体，实现专家演示 100% 可靠抓取。

3. **批级 NaN 恢复机制**：针对 Genesis 高负载并行模拟的偶发解算器发散（NaN），实现批级自动恢复——捕获异常后跳过该 batch 继续，已保存数据不丢失，避免从头重跑。

4. **符号化动作编码**：将夹爪动作编码为 -0.04（闭合力控）/ +0.04（张开位置控）双语义，保证训练/评估动作空间一致，解决策略预测模糊问题。

5. **5-box 凹槽容器 + 双层成功判定**：容器底部下沉判定（物体底部低于容器边缘）更符合物理实际，接受长条物体部分沉入。

## 4. 评估结果

### 最终版本（banana/plum/red_cube）
| 物体 | 成功率 |
|------|--------|
| 011_banana（黄） | **100%** |
| 018_plum（紫） | 57% |
| red_cube（红） | 25% |
| **总体** | **70%** |

### 迭代演进
| 版本 | 训练物体 | 成功率 | 失败根因 |
|------|---------|--------|---------|
| v6（几何基元） | cube/cylinder | 50% | 圆柱抓取困难 |
| YCB v1 | apple/banana/plum | 35% | apple 超夹爪 |
| YCB v2 | banana/plum/orange | 70% | orange 超夹爪 |
| YCB v3 | banana/plum/strawberry | 65% | strawberry 不对称 |
| **YCB v4** | **banana/plum/red_cube** | **70%** | - |

### 闭环集成验证（Qwen3-VL 规划 + SmolVLA 执行）
| 测试 | 成功率 |
|------|--------|
| Qwen3-VL 场景规划闭环（3 episodes） | **100%**（3/3） |

## 5. 复现说明

详见 `README.md`。核心命令：
```bash
# 1. 录制数据集（n_envs=32，批级 NaN 恢复）
python record_dataset_parallel.py --episodes 220 --n-envs 32 --repo-id color_sort/train_ycb4

# 2. 训练 SmolVLA（batch=64, fp32）
python train_policy.py smolvla --repo-id color_sort/train_ycb4 --steps 10000 --batch-size 64

# 3. 闭环评估 + Qwen3-VL 规划
python eval_policy.py --policy-path ... --qwen-plan --episodes 20
```

## 6. 环境
- **GPU**: AMD Radeon（ROCm 7.2, 51.5GB VRAM）
- **物理引擎**: Genesis 1.2.3（GPU 并行）
- **框架**: LeRobot 0.6.0, PyTorch 2.11 (ROCm), transformers ≥4.57
- **模型**: Qwen3-VL-8B（ModelScope 本地）, SmolVLA-450M
