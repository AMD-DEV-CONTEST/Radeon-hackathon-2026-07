# Color Sorting Design Spec

> AMD Hackathon Track 3 — Genesis + IL/RL/VLA 桌面颜色分拣
> Status: DRAFT · 2026-07-28

## 1. 选题与目标

**任务**:Franka Panda 机械臂在 Genesis 仿真桌面上,将多种颜色的几何混合物体(Box / Cylinder / Sphere)分拣到与物体颜色对应的容器中。

**示例指令**:"pick the red cube into the red bin" → 机械臂抓红色方块放进红色碗。

**技术路线**:Hybrid
- Phase A — ACT(imitation learning)跑通闭环
- Phase B — SmolVLA 微调(加语言分拣 + 类别泛化)
- Phase C — Qwen3-VL 分级架构(评估 + 失败重规划,创新加分点)

**不走的路线**:纯 RL 从零训练(PPO/SAC 在赛题时间窗内风险过高,不作为主路径)。

---

## 2. 现状基线

### 2.1 当前 repo(RoboPilot)已删除部分
已删除(与新主路线无关):
- `src/envs/{grasp_env,residual_env}.py`(suction 焊接约束 + 6D delta-EE,被 demo 夹爪+9D 取代)
- `src/{grasp_bc,train_grasp,residual_train,search_offset}.py`(自写 BC + rsl_rl PPO 脚手架,被 lerobot-train 取代)
- `src/control/primitives.py`(OMPL+焊接控制原语)
- `src/sim/scene_manager.py`(ground-plane 无桌台范式,与 demo 桌台+D435i 冲突)
- `src/system/__init__.py`(空)

### 2.2 当前 repo 保留部分
- `src/vision/{qwen3vl,camera,verifier,scene_memory}.py` — Qwen3-VL 分级架构上层(Stage C 用)
- `src/planner/{task_planner,recovery,action_scheduler}.py` — task_planner 接 Qwen 出 JSON、recovery 9 模式分类失败类型
- `demo/` `examples/` `benchmark/` — RoboPilot 现有 baseline,作异范式参考(不入主对比表)
- `docs/AMD_Hackathon_Workshop_Guide.md` `docs/Genesis_World_完整教程.md` — 赛题 + 教程资料
- `franka_fruit_pick_demo-main_extracted/` `genesis-world-main_extracted/` — 只读参考,不修改

### 2.3 参考 demo(franka_fruit_pick_demo)
M1-M5 高质量 pipeline 已跑通,作为代码基底:
- `SceneBundle`:Franka + Table + YCB + 世界相机 + 腕相机(D435i 1280x720)
- 几何自适应抓取(`_grasp_hand_z` 用 AABB 算 fingertip_z)
- 速度限制防弹射(`_goto_interp` MOVE_MAX_DQ=0.006 rad/step)
- 双层域随机化(Layer-A build-time 外观 / Layer-B runtime 物理)
- `EpisodeRecorder`:30fps decimated from 100Hz,9D 关节 + world/wrist RGB + task 文本
- `LeRobotDataset.create`/`finalize`(lerobot 0.6.x API)
- 策略无关 eval(`make_policy` + `predict_action`,ACT/SmolVLA 通用)

---

## 3. 技术选型依据

### 3.1 为什么 Hybrid(ACT → SmolVLA)
研究 agent 综述结论(详见 `MEMORY.md` "Discovered durable knowledge"):

| 维度 | ACT(IL) | SmolVLA(VLA) | RL(HIL-SERL) |
|---|---|---|---|
| 数据需求 | 几十-百 episode 起步 | 50-200 episodes 微调见效 | 大量在线 rollout |
| 训练成本 | 单 GPU 十几分钟-小时 | 单 GPU ~1 天 | 上百 GPU 小时,调参敏感 |
| 闭环率 | 桌面 pick-place 强 | SO100 ~78%(社区预训练后) | 看 reward shaping |
| 泛化 | IN 分布鲁内强,OOD 差 | 强(VLM prior,语言驱动) | 任务边界内强,迁移弱 |
| sim-to-real | 视觉 gap 中等 | 需消除视觉 gap | RL sim-native |
| 契合赛题 | ⭐⭐⭐⭐ 快速跑通首选 | ⭐⭐⭐ 数据少 + 语言分拣 | ⭐⭐ 时间窗风险高 |

**顺序**:ACT 先跑通(迭代快、不依赖 reward shaping)→ SmolVLA 微调(加语言/类别泛化)→ 可选 HIL-SERL 残差纠正(不从零训 PPO)。

### 3.2 为什么保留 Qwen3-VL
研究 agent 综述结论(详见 `MEMORY.md` "VLA + external-VLM layered architecture"):

- **Pigey / Physical Agency**(arXiv:2607.21725)是 1:1 学术先例:"frozen VLA + external orchestrator does verify+replan"。
- **Gemini Robotics** 双模型(ER+VLA)、**GR00T N1** 双系统(VLM+DiT)是工业平行路线。
- **SmolVLA 自身数据流水线**用了 Qwen2.5-VL-3B 做离线标注(HF blog /blog/smolvla),LeRobot 团队背书 Qwen-VL 系列在机器人数据管线的角色。

**定位**:Qwen3-VL 作 ACT/SmolVLA 策略**上层的评估 + 失败重规划**模块,不进 30Hz 控制循环(vLLM ~1.8s/帧会拖垮)。

**插入点**:
1. **episode 开始前**:自然语言 → Qwen3-VL 输出 `[(object, color, container)]` JSON → 喂 SmolVLA 语言 task / ACT task spec
2. **episode 结束 + dwell 后**:抓 world-cam 一帧 → Qwen3-VL 判 success/fail + failure_type → 失败触发 replan(对位 RoboPilot recovery.py 9 模式)
3. **可选离线**:录制数据集时用 Qwen3-VL 自动标 task 描述 + 颜色/位置(扩展 SmolVLA 自身做法)

### 3.3 为什么用 Box/Cylinder/Sphere 而非 YCB
- demo 的 YCB 物体抓取参数(GraspProfile)针对 banana/lemon/plum 调优,换成多色后要重调
- `gs.morphs.Box/Cylinder/Sphere` + `gs.surfaces.Plastic(color=...)` 是 RoboPilot `grasp_env.py` 已验证的彩色物体 API,几何抓取更稳定
- 语言分拣标签 = 颜色名,与 SmolVLA 已知 SO100 sorting dataset 对齐

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│ Stage C: Qwen3-VL 分级架构 (上层,非每帧)                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │ task_planner │───▶│  Qwen3-VL    │───▶│  verifier    │    │
│  │ 语言→JSON    │    │ (vLLM ~1.8s) │    │ success/fail │    │
│  └──────────────┘    └──────────────┘    └──────┬───────┘    │
│         │                                  failure_type      │
│         ▼                                       │            │
│  [(obj,color,container)] JSON                   ▼            │
│  = SmolVLA task 字段                    recovery.py          │
│                                       9 mode 重规划            │
└─────────────────────────────────────────────────────────────┘
        │                                       ▲
        ▼                                       │
┌─────────────────────────────────────────────────────────────┐
│ Stage A/B: 学习策略 (ACT / SmolVLA)                          │
│  observation: world_cam RGB + wrist_cam RGB + state[9] + task │
│       ↓                                                     │
│  ACT (Phase A) 或 SmolVLA (Phase B)                          │
│       ↓                                                     │
│  action: 9D joint targets (7 arm + 2 gripper)                │
└─────────────────────────────────────────────────────────────┘
        │                                       ▲
        ▼                                       │
┌─────────────────────────────────────────────────────────────┐
│ Genesis 仿真层 (底层)                                        │
│  build_scene → sk_grasp_demo → scene.step() → 读相机/状态      │
│  Franka + Table + 多色混合物体 + 多色容器                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 文件结构

```
/workspace/template-repos/template-107/repo/
  color_sort/                       (新主目录,搬 demo pipeline 骨架改编)
    paths.py                        ← 几乎直抄 demo
    scene_config.py                 ← 改:多色混合 (Box/Cylinder/Sphere)
                                     + 每色一个容器 (bowl 或 box)
                                     + 保留 demo 的 Franka/相机/D435i 配置
    build_scene.py                  ← 改色系 layout,其余保留
    sk_grasp_demo.py                ← 改 grasp_demo.py:
                                     TaskSpec pick_object 改为 (color, geometry)
                                     place_target = pick.color 对应容器
                                     GraspProfile 为 Box/Cylinder/Sphere 重调
    randomize.py                    ← 抄,RELIABLE_PICK_POOL 改为彩色物体列表
    record_dataset.py               ← 抄,task = "pick the <color> <geom> into the <color> bin"
                                     按 color 分 train/eval hold-out
    train_policy.py                 ← 直抄(策略无关,Phase A: --policy.type=act)
    eval_policy.py                  ← 直抄 + 顶层接 RoboPilot vision/verifier.py Qwen 分支

  src/vision/                       (保留,Stage C 接 Qwen3-VL)
  src/planner/                      (保留,recovery 9 类喂 Qwen 失败判定)

  docs/compose/specs/color_sorting_design.md  (本文件)
```

---

## 6. 数据集设计

### 6.1 LeRobot 字段(对齐 demo 0.6.x)
| 字段 | Shape | Dtype | 说明 |
|---|---|---|---|
| `observation.state` | [9] | float32 | Franka 9D 关节(7 arm + 2 gripper) |
| `action` | [9] | float32 | 专家目标关节 |
| `observation.images.world` | [360,640,3] | video | 顶视 RGB |
| `observation.images.wrist` | [360,640,3] | video | 腕视 RGB |
| `task` | — | str | "pick the red cube into the red bin" |

fps=30,decimated from 100Hz sim via fractional accumulator。只 flush 成功 episode(对齐 demo)。

### 6.2 颜色 hold-out 设计(为 B2 泛化对比铺路)
- **训练颜色**:red, blue, green(3 色)
- **评估 hold-out 颜色**:yellow, purple(2 色,训练时不见)
- **几何**:每色含 Box + Cylinder + Sphere 各 1 个(共 3 色 × 3 几何 = 9 物体 + 2 hold-out 色 × 3 几何 = 6 评估物体)
- **容器**:每色 1 个 bowl(共 5 色 = 5 bowl,含 hold-out 色)

### 6.3 数据量
- Phase A(ACT):50 episodes × ~135 frames ≈ 6750 frames
- Phase B(SmolVLA):100 episodes(对齐 AMD 指南 demo 规模)

---

## 7. 执行计划(三阶段 + 提交)

### Stage A — 跑通 ACT 闭环(T3,7 步)
| ID | 任务 | verify |
|---|---|---|
| T3.6 A6a | 云实例验证依赖(lerobot==0.6.0 + genesis + torchcodec/pyav + smolvla_base + Qwen3-VL-8B 可加载) | `python -c "import lerobot, genesis, torch; print(torch.cuda.is_available())"` 全通 |
| T3.7 A6b | 当前 repo 只写代码骨架,不装全栈依赖 | 代码可 import(不跑仿真),无 ModuleNotFoundError |
| T3.1 A1 | 抄 demo 骨架到 color_sort/(Box/Cylinder/Sphere + Plastic color,不走 YCB) | `python color_sort/build_scene.py --cpu --steps 50 --save-frames` 出 2 张图,≥3 彩色物体 + ≥3 容器 |
| T3.2 A2 | sk_grasp_demo color→container + 3 几何 GraspProfile 调参 | 3 种几何各跑 5 次 script grasp,成功 ≥4/5 |
| T3.3 A3 | record_dataset 录 50 episodes(按颜色分 train/eval hold-out) | LeRobotDataset 加载、帧数 ≈50×135、字段对齐、train/eval 颜色分离 |
| T3.4 A4 | `lerobot-train --policy.type=act --dataset.repo_id=color_sort/mixed --steps=20000` | loss 单调下降、final 模型存在 |
| T3.5 A5 | eval_policy 20 episodes 闭环 | 成功率 >30%,与随机基线有显著差异 |

### Stage B — SmolVLA 微调 + 泛化对比(T4,2 步)
| ID | 任务 | verify |
|---|---|---|
| T4.1 B1 | 切 `--policy.path=lerobot/smolvla_base --rename_map={world→camera1, wrist→camera2}` | loss 单调下降、final <0.1;峰值显存记录留作 ROCm 评分数据 |
| T4.2 B2 | ACT vs SmolVLA 同 seed hold-out 颜色泛化对比 | SmolVLA 在 yellow/purple(训练未见)上成功率 > ACT |

### Stage C — Qwen3-VL 分级架构(T5,3 步,可选 stretch)
| ID | 任务 | verify |
|---|---|---|
| T5.1 C1 | task_planner.py 加"语言→Qwen3-VL 出 [(obj,color,container)] JSON"接口 | 输入"把红的放红碗"自动出 JSON |
| T5.2 C2 | eval_policy.py episode 收尾接 vision/verifier.py Qwen 后端判 success/fail | 失败 episode 正确分类到 recovery.py 9 mode 之一 |
| T5.3 C3 | 4 方案对照(ACT / SmolVLA / ACT+Qwen / SmolVLA+Qwen 同场景;RoboPilot 异范式参考单独列) | 4 成功率对比 JSON/图,作赛题报告主表 |

### Stage D — 赛题提交(T7,4 步)
| ID | 任务 | verify |
|---|---|---|
| T7.1 D1 | 技术报告(架构 + AMD GPU 使用 + 创新点 + ROCm 训练耗时/显存/利用率) | 覆盖评分 5 维度 |
| T7.2 D2 | 可复现 README + Dockerfile | 第三方按 README 可跑通 |
| T7.3 D3 | 演示视频 3-5 min | AMD GPU 上完整工作流闭环 |
| T7.4 D4 | PPT / 海报 | 赛题规则要求 |

### 执行顺序
```
T6 (spec) → T3.6 A6a (云验证) ──┐
                                ├─→ T3.1 A1 → T3.2 A2 → T3.3 A3 → T3.4 A4 → T3.5 A5
T6 (spec) → T3.7 A6b (写代码) ──┘
                                                                ↓
                                          T4.1 B1 → T4.2 B2
                                                                ↓
                                          T5.1 C1 → T5.2 C2 → T5.3 C3
                                                                ↓
                                          T7.1 D1 → T7.2 D2 → T7.3 D3 → T7.4 D4
```

---

## 8. 已知风险

1. **LeRobot 版本**:demo 用 0.6.0,赛题指南说 0.4.4(数据集 API 不兼容)。A6a 必须先确认 0.6.0 在云实例可装可 import。
2. **SmolVLA 模型基座**:AMD 指南说 `/workspace/models/smolvla_base` + `SmolVLM2-500M-Video-Instruct`。当前开发 repo 无此路径,A6a 在云实例确认。
3. **多色场景对脚本抓取成功率**:demo 调优针对 3 个 YCB + 单 bowl;多色混合 + 多容器后抓取时序可能撞邻物体。A2 需为 3 种几何重调 GraspProfile,验证各 5 次成功 ≥4。
4. **7-DOF 映射**:SmolVLA 模型卡评论提到 7-DOF→6-DOF 映射需谨慎。Franka 是 7-DOF arm + 2-DOF gripper = 9D,demo 已用 9D,保持 9D 即可。
5. **ROCm video backend**:torchcodec 需系统 FFmpeg 共享库且 ABI 绑 torch 构建,在 ROCm 上不可靠。demo 默认 pyav,A6a 确认。

---

## 9. 评分维度覆盖

| 评分维度 | 分值 | 覆盖点 |
|---|---|---|
| 能力表现 | 30 | A5/B2/C3 成功率数据 |
| AMD Radeon 和 ROCm | 20 | A6a 记录训练耗时/峰值显存/利用率;D1 报告 |
| 创新和原创性 | 20 | Qwen3-VL 分级架构(Stage C)+ 颜色 hold-out 泛化消融(B2)+ 多几何混合场景 |
| 真实应用价值 | 20 | 分拣任务的工业语义 + sim-to-real 讨论(D1) |
| 上游开源贡献 | 10 | 可复现 README + Dockerfile(D2)+ 对 demo 的改造回馈 |

---

## 10. 参考链接

### 论文(全部 arxiv ID 已验证)
- SmolVLA — arXiv:2506.01844
- Pigey / Physical Agency(分级架构主引用)— arXiv:2607.21725
- GR00T N1 — arXiv:2503.14734
- Inner Monologue — arXiv:2207.05608
- ECoT — arXiv:2407.08693
- PhysReflect-VLA — arXiv:2606.27146
- SayCan — arXiv:2204.01691
- OpenVLA — arXiv:2406.09246
- Qwen3 技术报告 — arXiv:2505.09388

### 模型卡 / blog
- `lerobot/smolvla_base` — https://huggingface.co/lerobot/smolvla_base
- SmolVLA blog(含 Qwen2.5-VL-3B 离线标注段)— https://huggingface.co/blog/smolvla
- `Qwen/Qwen3-VL-8B-Instruct` — https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
- LeRobot README — https://raw.githubusercontent.com/huggingface/lerobot/main/README.md
- Gemini Robotics — https://deepmind.google/models/gemini-robotics/

### 本项目内资料
- `docs/AMD_Hackathon_Workshop_Guide.md` — 赛题官方拆解
- `docs/Genesis_World_完整教程.md` — Genesis API 全解
- `franka_fruit_pick_demo-main_extracted/franka_fruit_pick_demo-main/` — 参考 demo(只读)
- `genesis-world-main_extracted/genesis-world-main/` — Genesis 官方仓库(只读)