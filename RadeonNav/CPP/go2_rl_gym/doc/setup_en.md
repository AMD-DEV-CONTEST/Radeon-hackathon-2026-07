# Installation and Configuration Guide

## System Requirements

- **OS**: Ubuntu 18.04 or higher is recommended
- **GPU**: Nvidia GPU
- **Driver Version**: Version 525 or higher is recommended

---

## 1. Create Virtual Environment

It is recommended to run training or deployment programs within a virtual environment. Conda is recommended for creating and managing virtual environments. If Conda is already installed on your system, you can skip step 1.1.

### 1.1 Download and Install MiniConda

MiniConda is a lightweight distribution of Conda suitable for creating and managing virtual environments. Use the following commands to download and install:

```bash
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
```

After installation, initialize Conda:

```bash
~/miniconda3/bin/conda init --all
source ~/.bashrc
```

### 1.2 Create New Environment

Use the following command to create a virtual environment:

```bash
conda create -n unitree-rl python=3.8
```

### 1.3 Activate Virtual Environment

```bash
conda activate unitree-rl
```

---

## 2. Install Dependencies

### 2.1 Install PyTorch

PyTorch is a neural network computation framework used for model training and inference. Install it using the following command:

```bash
conda install pytorch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 pytorch-cuda=12.1 -c pytorch -c nvidia
```

### 2.2 Install Isaac Gym

Isaac Gym is Nvidia's rigid body simulation and training framework.

#### 2.2.1 Download

Download [Isaac Gym](https://developer.nvidia.com/isaac-gym) from the Nvidia official website.

#### 2.2.2 Install

Unzip the file, enter the `isaacgym/python` folder, and execute the following command to install:

```bash
cd isaacgym/python
pip install -e .
```

#### 2.2.3 Verify Installation

Run the following commands. If a window pops up showing 1080 balls falling, the installation is successful:

```bash
cd examples
python 1080_balls_of_solitude.py
```

If there are any issues, please refer to the official documentation in `isaacgym/docs/index.html`.

### 2.3 Install rsl_rl

`rsl_rl` is a reinforcement learning algorithm library.

Our repository includes `rsl_rl` with new algorithms. Clone the Git repository:

```bash
git clone https://github.com/wty-yy/go2_rl_gym.git
```

#### 2.3.1 Install

```bash
cd rsl_rl
pip install -e .
```

### 2.4 Install go2_rl_gym

Enter the directory and install:

```bash
cd go2_rl_gym
pip install -e .
```

### 2.5 Real Robot Deployment (Optional)

#### 2.5.1 unitree_sdk2

C++ SDK. For compilation, please refer to the [official tutorial](https://github.com/unitreerobotics/unitree_sdk2?tab=readme-ov-file#environment-setup).

#### 2.5.2 unitree_sdk2_python (Choose for Python Deployment)

```bash
conda create -n kaiwu python=3.8
conda activate kaiwu
pip3 install pytorch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 pytorch-cuda=12.1 -c pytorch -c nvidia

git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .
```

#### 2.5.3 Install unitree_cpp_deploy (Choose for C++ Deployment)

We use a modified C++ deployment repository based on `unitree_rl_lab`, specifically designed for deploying models trained in this repository. See [unitree_cpp_deploy](https://github.com/wty-yy/unitree_cpp_deploy).

### 2.6 RoboGauge Evaluation (Optional)

RoboGauge is a project for evaluating quadruped robot performance via Sim2Sim in Mujoco. It performs asynchronous evaluation on the CPU during training. For specific details, refer to the [README](https://github.com/wty-yy/RoboGauge).

```bash
git clone [https://github.com/wty-yy/RoboGauge.git](https://github.com/wty-yy/RoboGauge.git)
cd RoboGauge
pip install -e .
```
