<div align="center">
	<h1 align="center">Go2 RL GYM</h1>
	<p align="center">
		<span>🌎 English</span> | <a href="README_zh.md">🇨🇳 中文</a> | <a href="https://arxiv.org/abs/2602.00678">📄 Paper [RSS 2026]</a>
	</p>
</div>

<p align="center">
	<strong>This repository builds on <a href="https://github.com/unitreerobotics/unitree_rl_gym">unitree_rl_gym</a> to train the Unitree Go2 quadruped with reinforcement learning.</br>For the IsaacLab-based version, see <a href="https://github.com/wertyuilife2/go2_rl_robotlab">go2_rl_robotlab</a>.</strong>
</p>

<div align="center">

| <div align="center"> Isaac Gym </div> | <div align="center"> Mujoco </div> |  <div align="center"> Physical </div> |
|--- | --- | --- |
| ![isaacgym eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/isaacgym_eval.gif)  | ![mujoco eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval.gif) | ![real eval](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/real_eval.gif) |

</div>

## 📦 Installation

Follow the step-by-step setup guide in [setup.md](doc/setup_en.md).

## 🛠️ Usage Guide

### 1. Train

Run the following command to launch training:

```bash
python legged_gym/scripts/train.py --task=xxx --headless
```

#### ⚙️  Arguments
- `--task`: Required. Options include `go2`, `go2_cts`, `go2_moe_cts`, `go2_moe_ng_cts`, `go2_mcp_cts`, `go2_ac_moe_cts`, `go2_dual_moe_cts`; `go2_moe_cts` is the paper's final version.
- `--headless`: Render viewer by default; set to `true` to disable rendering for higher throughput.
- `--resume`: Resume training from a chosen checkpoint in the logs.
- `--experiment_name`: Experiment folder to save/load from.
- `--run_name`: Run subfolder name to save/load from.
- `--load_run`: Name of the run to load (defaults to the most recent run).
- `--checkpoint`: Checkpoint index to load (defaults to the latest file).
- `--num_envs`: Number of parallel simulated environments.
- `--seed`: Random seed.
- `--max_iterations`: Maximum training iterations.
- `--sim_device`: Physics simulation device. Use `--sim_device=cpu` to force CPU.
- `--rl_device`: RL computation device. Use `--rl_device=cpu` to force CPU.
- `--robogauge`: Enable RoboGauge evaluation tool; disabled by default. Evaluation results are saved as `results_{it}.yaml` in `logs/{exp_name}/{date}/robogauge_results` and logged to TensorBoard.
- `--robogauge_port`: RoboGauge server port; default is 9973.

> RoboGauge evaluation requires a separate server to be started. Refer to the [RoboGauge documentation](https://github.com/wty-yy/RoboGauge).

**Default checkpoint path**: `logs/<experiment_name>/<date_time>_<run_name>/model_<iteration>.pt`

---

#### Model Evaluation

The trained model above was evaluated using the [RoboGauge](https://github.com/wty-yy/RoboGauge) framework via Sim2Sim. The models in the table below are the best models after 150k training steps.
All released checkpoints are hosted on Hugging Face: [wty-yy/go2_rl_gym_data](https://huggingface.co/wty-yy/go2_rl_gym_data).

| Model | Score | Tracking  | Safety  | Quality  | Level | Download |
| --- | --- | --- | --- | --- | --- | --- |
| go2_moe_cts (Ours) | **0.6713** | **0.6669** | **0.7857** | **0.7392** | **7.85** | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_cts_137000_0.6713) |
| go2_ac_moe_cts | 0.6509 | 0.6442 | 0.7644 | 0.7149 | 7.52 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_ac_moe_cts_115k_0.6509.pt) |
| go2_mcp_cts | 0.6399 | 0.6355 | 0.7542 | 0.7058 | 7.41 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_mcp_cts_91k_0.6399) |
| go2_moe_ng_cts | 0.6519 | 0.6447 | 0.7639 | 0.7186 | 7.56 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_ng_cts_79k_0.6519) |
| [CTS](https://arxiv.org/pdf/2405.10830) vanilla | 0.5786 | 0.5755 | 0.7066 | 0.6624 | 6.83 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_cts_vanilla2_103.5k_0.5786) |
| [HIM](https://github.com/InternRobotics/HIMLoco) | 0.5379 | 0.5453 | 0.6476 | 0.6050 | 6.19 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_him_21k_0.5379.pt) |
| [DreamWaQ](https://arxiv.org/abs/2301.10602) | 0.5054 | 0.5105 | 0.6149 | 0.5730 | 5.74 | [ckpt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_dwaq_119.5k_0.5054.pt) |

> In the downloaded ckpt files, `*.pt` is used for [Python deployment](#41-python-deployment), and `*.onnx` is used for [C++ deployment](#42-c-deployment). The models above were all trained with self-collision disabled. In later tests, we found that enabling self-collision can also achieve strong results; see [go2_moe_cts_164k_0.6715 - exported](https://huggingface.co/wty-yy/go2_rl_gym_data/tree/main/go2_moe_cts_high_slope_thre_164k_0.6715_20260419) with [complete model weights - model_164000.pt](https://huggingface.co/wty-yy/go2_rl_gym_data/blob/main/go2_moe_cts_high_slope_thre_164k_0.6715_20260419/model_164000.pt).

### 2. Play

Visualize policies inside Gym with:

```bash
python legged_gym/scripts/play.py --task=xxx
```

**Notes**

- Play launches on randomized terrain with difficulty between 7 and 9.
- It automatically loads the latest checkpoint inside the experiment folder.
- You can specify another model via `experiment_name`, `load_run`, and `checkpoint`, for example:
	```bash
	python legged_gym/scripts/play.py --task=go2_moe_cts --num_envs 100 --experiment_name go2_cts_hard_terrain --load_run Mar21_22-54-5-46_ --checkpoint 100000
	```

#### 💾 Policy Export

Play exports the Actor network to `logs/{experiment_name}/exported/policies`:
- `policy.pt`: TorchScript model for Sim2Sim.
- `policy.onnx`: ONNX model for Sim2Real.
- `policy.pkl`: Raw weights.
  
#### Demonstration

![isaacgym play](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/isaacgym_play.gif)

---

### 3. Sim2Sim (Mujoco)

Run policies in the Mujoco simulator:

```bash
python deploy/deploy_mujoco/deploy_go2.py
```

Connect an Xbox-compatible gamepad to enable teleoperation; otherwise, the agent keeps a default forward command.

- **Swap the policy**: The default checkpoint is `deploy/pre_train/go2/go2_cts_150k.pt`. Replace `policy_path` in the YAML config with your own `logs/{experiment_name}/exported/policies/policy.pt`.
- **Swap terrains**: Default terrain is `resources/robots/go2/stairs.xml`. Alternatives include `flat.xml`, `race_track.xml`, `cross_stairs.xml`, and `cross_slope.xml`. Generate new terrains with [windigal - mujoco_terrains](https://github.com/windigal/mujoco_terrains)

#### Results

| Flat | Stairs | Race Track |
|--- | --- | --- |
| <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval_flat.gif" width="250"/> | <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval.gif" width="250"/> | <img src="https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/go2_rl_gym/mujoco_eval_track.gif" width="250"/> |

---

### 4. Sim2Real

#### 4.1 Python Deployment

```bash
# Onboard Jetson: pick Python by JetPack version
# JetPack 6: Python 3.10
# JetPack 5: Python 3.8
conda create -n deploy python=3.10
conda activate deploy
# Install the matching PyTorch wheel for your Jetson
# https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip3 install -e .
```

In the Unitree app, open Device → Service, disable `mcf/*`, and enable the `ota_box` service.

Assuming the interface to the low-level controller is `eth0`:

```bash
cd deploy/deploy_real
python deploy_real_go2.py eth0
```

Press `start` to stand and `A` to engage the controller.

#### 4.2 C++ Deployment

Follow the usage described in [unitree_cpp_deploy](https://github.com/wty-yy/unitree_cpp_deploy).

#### Demonstration

| Python Deploy | C++ Deploy |
| --- | --- |
| ![python deploy](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/deploy/py_deploy_with_commands.gif) | ![cpp deploy](https://raw.githubusercontent.com/robogauge/picture-bed/refs/heads/main/deploy/cpp_deploy_with_commands.gif) |

C++ Deployment: Policy 1/2/4 trained by go2_rl_gym, Policy 3 trained by [go2_rl_robotlab](https://github.com/wertyuilife2/go2_rl_robotlab).

https://github.com/user-attachments/assets/b72e10f2-ffdb-407d-bb1f-9d545e7f9f63

---

## 🎉  Acknowledgements

This repository would not exist without the following open-source projects:

- [unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym): Unitree's core RL training framework.
- [legged_gym](https://github.com/leggedrobotics/legged_gym): Base locomotion environment.
- [rsl_rl](https://github.com/leggedrobotics/rsl_rl.git): Reinforcement learning algorithms.
- [mujoco](https://github.com/google-deepmind/mujoco.git): High-performance CPU physics simulator.
- [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python.git): Python hardware interface for deployment.
- [unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2): C++ hardware interface for deployment.

Related publications implemented in this repo:
- [CTS: Concurrent Teacher-Student Reinforcement Learning for Legged Locomotion](https://arxiv.org/pdf/2405.10830)

Contributors:
- [@windigal](https://github.com/windigal): CTS algorithm reproduction, terrain generation, video editing
- [@wertyuilife2](https://github.com/wertyuilife2): CTS algorithm reproduction

---

## 📄  Citation
If you find our work helpful, please cite:
```bibtex
@inproceedings{wu2026robogauge,
    title={Toward Reliable Sim-to-Real Predictability for MoE-based Robust Quadrupedal Locomotion},
    author={Tianyang Wu and Hanwei Guo and Yuhang Wang and Junshu Yang and Xinyang Sui and Jiayi Xie and Xingyu Chen and Zeyang Liu and Xuguang Lan},
    booktitle={Proceedings of Robotics: Science and Systems},
    year={2026}
}
```

## 🔖  License

New contributions follow the [MIT License](LICENSE); the original unitree_rl_gym remains under the [BSD 3-Clause License](LICENSE).

See the complete [LICENSE file](LICENSE) for details.
