<div align="center">
  <h1 align="center">Go2 RL GYM</h1>
  <p align="center">
    <a href="README.md">🌎 English</a> | <span>🇨🇳 中文</span> | <a href="https://arxiv.org/abs/2602.00678">📄 Paper [RSS 2026]</a>
  </p>
</div>

<p align="center">
  <strong>本仓库基于<a href="https://github.com/unitreerobotics/unitree_rl_gym">unitree_rl_gym</a>，使用强化学习训练Go2机器狗。</br>基于IsaacLab开发的版本请见<a href="https://github.com/wertyuilife2/go2_rl_robotlab">go2_rl_robotlab</a>。</strong> 
</p>

<div align="center">

| <div align="center"> Isaac Gym </div> | <div align="center">  Mujoco </div> |  <div align="center"> Physical </div> |
|--- | --- | --- |
| ![isaacgym eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/isaacgym_eval.gif)  | ![mujoco eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval.gif) | ![real eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/real_eval.gif) |

</div>

## 📦 安装配置

安装和配置步骤请参考 [setup.md](/doc/setup_zh.md)

## 🛠️ 使用指南

### 1. 训练

运行以下命令进行训练：

```bash
python legged_gym/scripts/train.py --task=xxx --headless
```

#### ⚙️  参数说明
- `--task`: 必选参数，值可选(go2, go2_cts, go2_moe_cts, go2_moe_ng_cts, go2_mcp_cts, go2_ac_moe_cts, go2_dual_moe_cts)，go2_moe_cts为论文最终版本
- `--headless`: 默认启动图形界面，设为 true 时不渲染图形界面（效率更高）
- `--resume`: 从日志中选择 checkpoint 继续训练
- `--experiment_name`: 运行/加载的 experiment 名称
- `--run_name`: 运行/加载的 run 名称
- `--load_run`: 加载运行的名称，默认加载最后一次运行
- `--checkpoint`: checkpoint 编号，默认加载最新一次文件
- `--num_envs`: 并行训练的环境个数
- `--seed`: 随机种子
- `--max_iterations`: 训练的最大迭代次数
- `--sim_device`: 仿真计算设备，指定 CPU 为 `--sim_device=cpu`
- `--rl_device`: 强化学习计算设备，指定 CPU 为 `--rl_device=cpu`
- `--robogauge`: 是否启用 RoboGauge 评估工具，默认关闭，评估结果会以 `results_{it}.yaml` 保存在 `logs/{exp_name}/{date}/robogauge_results` 下，并记录在 TensorBoard 中
- `--robogauge_port`: RoboGauge 服务端端口，默认 9973

> RoboGauge 评估还需单独启动服务端，使用方法参考 [RoboGauge 文档](https://github.com/wty-yy/RoboGauge)

**默认保存训练结果**：`logs/<experiment_name>/<date_time>_<run_name>/model_<iteration>.pt`

---

#### 模型评估

使用[RoboGauge](https://github.com/wty-yy/RoboGauge)框架通过Sim2Sim评估上述训练模型，下表中模型为150k训练步中的最优模型。
发布的权重统一保存在 Hugging Face: [wty-yy/go2_rl_gym_data](https://huggingface.co/wty-yy/go2_rl_gym_data)。

| Model | Score | Tracking | Safety | Quality | Level | Download |
| --- | --- | --- | --- | --- | --- | --- |
| go2_moe_cts (Ours) | **0.6713** | **0.6669** | **0.7857** | **0.7392** | **7.85** | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_cts_137000_0.6713) |
| go2_ac_moe_cts | 0.6509 | 0.6442 | 0.7644 | 0.7149 | 7.52 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_ac_moe_cts_115k_0.6509.pt) |
| go2_mcp_cts | 0.6399 | 0.6355 | 0.7542 | 0.7058 | 7.41 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_mcp_cts_91k_0.6399) |
| go2_moe_ng_cts | 0.6519 | 0.6447 | 0.7639 | 0.7186 | 7.56 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_ng_cts_79k_0.6519) |
| [CTS](https://arxiv.org/pdf/2405.10830) vanilla | 0.5786 | 0.5755 | 0.7066 | 0.6624 | 6.83 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_cts_vanilla2_103.5k_0.5786) |
| [HIM](https://github.com/InternRobotics/HIMLoco) | 0.5379 | 0.5453 | 0.6476 | 0.6050 | 6.19 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_him_21k_0.5379.pt) |
| [DreamWaQ](https://arxiv.org/abs/2301.10602) | 0.5054 | 0.5105 | 0.6149 | 0.5730 | 5.74 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_dwaq_119.5k_0.5054.pt) |

> 下载的 ckpt 中，`*.pt` 用于[Python 实物部署](#41-python实物部署)，`*.onnx` 用于[C++ 实物部署](#42-c实物部署)。上述模型均在关闭自碰撞的设置下训练；后续测试发现，开启自碰撞也能取得不错效果，参考 [go2_moe_cts_164k_0.6715 - exported](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_cts_high_slope_thre_164k_0.6715_20260419)以及其[完整模型权重 - model_164000.pt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_moe_cts_high_slope_thre_164k_0.6715_20260419/model_164000.pt)。

---

### 2. Play

如果想要在 Gym 中查看训练效果，可以运行以下命令：

```bash
python legged_gym/scripts/play.py --task=xxx
```

**说明**：

- Play 启动参数为随机地形，难度在7到9之间。
- 默认加载实验文件夹最新训练的一个模型。
- 可通过 `experiment_name`, `load_run` 和 `checkpoint` 指定其他模型，例如
    ```bash
    python legged_gym/scripts/play.py --task=go2_moe_cts --num_envs 100 --experiment_name go2_cts_hard_terrain --load_run Mar21_22-54-5-46_ --checkpoint 100000
    ```

#### 💾 导出网络

Play 会导出 Actor 网络，保存于 `logs/{experiment_name}/exported/policies` 中：
- `policy.pt`: torch script模型，用于Sim2Sim。
- `policy.onnx`: onnx模型，用于Sim2Real。
- `policy.pkl`: 模型权重。
  
#### Play 效果

![isaacgym play](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/isaacgym_play.gif)

---

### 3. Sim2Sim (Mujoco)

支持在 Mujoco 仿真器中运行 Sim2Sim：

```bash
python deploy/deploy_mujoco/deploy_go2.py
```

如果有xbox协议的手柄接入主机，自动切换为手柄控制，否则只会保持默认指令前进。

- 替换网络模型：默认模型位于 `deploy/pre_train/go2/go2_cts_150k.pt`；自己训练模型保存于`logs/{experiment_name}/exported/policies/policy.pt`，只需替换 yaml 配置文件中 `policy_path`。
- 替换环境地形：默认地形为 `resources/robots/go2/stairs.xml`，其他可选地形，平地 `flat.xml`，赛道 `race_track.xml`，交叉楼梯和斜坡`cross_stairs`/`cross_slope`，地形使用[windigal - mujoco_terrains](https://github.com/windigal/mujoco_terrains)生成

#### 运行效果

| 平地 | 台阶 | 赛道 |
|--- | --- | --- |
| <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval_flat.gif" width="250"/> | <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval.gif" width="250"/> | <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval_track.gif" width="250"/> |

---

### 4. Sim2Real

#### 4.1 Python实物部署

```bash
# 如果机载电脑部署，根据Jetson版本选择Python版本
# JetPack 6: Python 3.10
# JetPack 5: Python 3.8
conda create -n deploy python=3.10
conda activate deploy
# 下载并安装对应Jetson设备和Python的PyTorch whl包
# https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip3 install -e .
```

先用app进入设备→服务状态→点击运控服务，关闭`mcf/*`，打开`ota_box`服务。

假设和下位机连接的网卡名称为`eth0`，执行
```bash
cd deploy/deploy_real
python deploy_real_go2.py eth0
```
`start`站立，`A`启动控制

#### 4.2 C++实物部署

参考[unitree_cpp_deploy](https://github.com/wty-yy/unitree_cpp_deploy)使用说明。

#### 运行效果

| Python部署 | C++部署 |
| --- | --- |
| ![python deploy](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/deploy/py_deploy_with_commands.gif) | ![cpp deploy](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/deploy/cpp_deploy_with_commands.gif) |

C++ 部署效果：策略1/2/4由go2_rl_gym训练，策略3由[go2_rl_robotlab](https://github.com/wertyuilife2/go2_rl_robotlab)训练。

https://github.com/user-attachments/assets/b72e10f2-ffdb-407d-bb1f-9d545e7f9f63

---

## 🎉  致谢

本仓库开发离不开以下开源项目的支持与贡献，特此感谢：

- [unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym)：宇树机器人强化学习训练基础框架。
- [legged\_gym](https://github.com/leggedrobotics/legged_gym)：构建基础训练环境。
- [rsl\_rl](https://github.com/leggedrobotics/rsl_rl.git)：强化学习算法实现。
- [mujoco](https://github.com/google-deepmind/mujoco.git)：提供强大CPU仿真功能。
- [unitree\_sdk2\_python](https://github.com/unitreerobotics/unitree_sdk2_python.git)：实物部署硬件Python通信接口。
- [unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2)：实物部署硬件C++通信接口。

本仓库实现包含以下论文，特此感谢：
- [CTS: Concurrent Teacher-Student Reinforcement Learning for Legged Locomotion](https://arxiv.org/pdf/2405.10830)

贡献者：
- [@windigal](https://github.com/windigal)：复现CTS算法，生成地形，剪辑视频
- [@wertyuilife2](https://github.com/wertyuilife2)：复现CTS算法

---

## 📄  引用
如果觉得我们的工作有帮助，请引用：
```bibtex
@inproceedings{wu2026robogauge,
    title={Toward Reliable Sim-to-Real Predictability for MoE-based Robust Quadrupedal Locomotion},
    author={Tianyang Wu and Hanwei Guo and Yuhang Wang and Junshu Yang and Xinyang Sui and Jiayi Xie and Xingyu Chen and Zeyang Liu and Xuguang Lan},
    booktitle={Proceedings of Robotics: Science and Systems},
    year={2026}
}
```

## 🔖  许可证

新增内容根据 [MIT License](./LICENSE) 授权，原仓库unitree_rl_gym根据 [BSD 3-Clause License](./LICENSE) 授权。

详情请阅读完整 [LICENSE 文件](./LICENSE)。
