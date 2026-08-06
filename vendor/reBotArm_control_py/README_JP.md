# reBot Arm B601-DM の Pinocchio と MeshCat 入門ガイド

<p align="center">
    <a href="./LICENSE">
        <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
    </a>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Ubuntu-orange.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Framework-Pinocchio-yellow.svg" alt="Pinocchio">
</p>

<p align="center">
  <strong>6 自由度ロボットアーム · 多モーター対応 · 運動学ソルバー · 軌道計画 · 完全オープンソース</strong>
</p>

<p align="center">
  <strong>
    <a href="./README_zh.md">简体中文</a> &nbsp;|&nbsp;
    <a href="./README.md">English</a> &nbsp;|&nbsp;
    <a href="./README_JP.md">日本語</a>&nbsp;|&nbsp;
    <a href="./README_Fr.md">français</a>&nbsp;|&nbsp;
    <a href="./README_es.md">Español</a>
  </strong>
</p>

---

## 📖 プロジェクト概要

**reBotArm Control** は、reBot Arm B601 ロボットアーム向けの Python 制御ライブラリで、低レベルのモーター制御から高レベルの運動学計算までの完全なソリューションを提供します。

### ✨ 主な機能

- 🦾 **双型号サポート** — B601-DM（達妙モーター）と B601-RS（霊足モーター）
- 🧮 **運動学ソルバー** — Pinocchio ベースの順/逆運動学計算
- 🛤️ **軌道計画** — SE(3) 測地線軌道 + CLIK 追従
- 🔧 **柔軟な設定** — YAML 設定ファイルでハードウェアの迅速な適応

---

## ⚙️ クイックスタート

### 動作環境

| 項目 | 要件 |
|------|------|
| **Python** | 3.10+ |
| **オペレーティングシステム** | Ubuntu 22.04+ |
| **通信インターフェース** | USB2CAN シリアルブリッジ または CAN インターフェース |

### インストール手順

#### ステップ 1. uv のインストール（未インストールの場合）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### ステップ 2. 環境の同期（すべての依存関係をインストール）

```bash
git clone https://github.com/vectorBH6/reBotArm_control_py.git
cd reBotArm_control_py
uv sync
```

:::tip
`uv sync` は、仮想環境を自動的に作成し（存在しない場合）、`pyproject.toml` と `uv.lock` に従ってすべての依存関係をインストールします。
:::

---

## 🔌 ハードウェア設定

### デフォルト：達妙 USB2CAN シリアルブリッジ

reBot Arm B601-DM はデフォルトで達妙 USB2CAN シリアルブリッジモジュールを使用します。

**ハードウェア接続**：
1. USB2CAN モジュールを USB ケーブルでコンピュータに接続
2. システムが自動的に `/dev/ttyACM0` デバイスとして認識します

**設定の確認**：
```bash
# デバイスの確認
ls /dev/ttyACM0

# モータースキャン
motorbridge-cli scan --vendor damiao --transport dm-serial \
    --serial-port /dev/ttyACM0 --serial-baud 921600
```

### オプション：標準 CAN インターフェース

他の USB-CAN アダプター（CANable、PCAN など）を使用する場合：

```bash
# CAN インターフェースの起動
sudo ip link set can0 up type can bitrate 500000

# インターフェースの確認
ip -details link show can0
```

### モーターブランドの設定

| モーターブランド | 伝送方式 | 設定パラメータ | ボーレート |
|-----------------|---------|---------------|-----------|
| **達妙 (Damiao)** | シリアルブリッジ | `dm-serial` | 921600 |
| **達妙 (Damiao)** | CAN インターフェース | `socketcan` | 500000 |
| **RobStride** | CAN インターフェース | `socketcan` | 500000 |

:::tip
- 達妙モーターでシリアルブリッジを使用する場合、`--transport dm-serial` の設定が必要です
- フィードバック ID ルール：`feedback_id = motor_id + 0x10`
:::

---

## 📁 プロジェクト構成

```
reBotArm_control_py/
├── config/                     # 設定ファイル
│   └── robot.yaml              # 関節パラメータ設定
├── example/                    # サンプルプログラム
│   ├── デバッグツール/
│   │   ├── 1_damiao_text.py        # 単一モーターコンソール
│   │   └── 2_zero_and_read.py      # ゼロキャリブレーション
│   ├── 運動学テスト/
│   │   ├── 5_fk_test.py            # 順運動学
│   │   └── 6_ik_test.py            # 逆運動学
│   ├── 実機制御/
│   │   ├── 7_arm_ik_control.py     # IK リアルタイム制御
│   │   ├── 8_arm_traj_control.py   # 軌道計画
│   │   └── 9_gravity_compensation.py  # 重力補償
│   └── sim/                    # シミュレーションツール
├── reBotArm_control_py/        # コアライブラリ
│   ├── actuator/               # アクチュエータモジュール
│   ├── kinematics/             # 運動学モジュール
│   ├── controllers/            # コントローラモジュール
│   └── trajectory/             # 軌道計画モジュール
├── urdf/                       # URDF モデル
└── README.md
```

---

## 🎮 サンプルプログラム

### デバッグツール

#### 1️⃣ 単一モーターコンソール (`1_damiao_text.py`)

motorbridge SDK を直接使用した単一モーターテスト、3 つの制御モードをサポート。

**使用方法**：
```bash
uv run python example/1_damiao_text.py
```

**インタラクティブコマンド**：
| コマンド | 説明 |
|---------|------|
| `mit <pos_deg> [vel kp kd tau]` | MIT モード |
| `posvel <pos_deg> [vlim]` | POS_VEL モード |
| `vel <vel_rad_s>` | 速度モード |
| `enable` / `disable` | 有効/無効 |
| `set_zero` | ゼロ位置設定 |
| `state` | 状態表示 |

---

#### 2️⃣ ゼロキャリブレーションと角度監視 (`2_zero_and_read.py`)

全関節のゼロ位置を自動設定し、関節角度をリアルタイム表示。

**使用方法**：
```bash
uv run python example/2_zero_and_read.py
```

---

### 運動学テスト

#### 5️⃣ 順運動学テスト (`5_fk_test.py`)

関節角度からエンドエフェクタ姿勢を計算。

**入力**：6 関節角度（度）

**出力**：
- エンドエフェクタ位置 (X, Y, Z) — 単位：メートル
- 回転行列 (3×3)
- オイラー角 (ロール/ピッチ/ヨー) — 単位：度

**例**：
```bash
uv run python example/5_fk_test.py
> 0 0 0 0 0 0
> 45 -30 15 -60 90 180
```

---

#### 6️⃣ 逆運動学テスト (`6_ik_test.py`)

希望するエンドエフェクタ姿勢から関節角度を求解。

**入力形式**：
- 位置のみ：`<x> <y> <z>`（メートル）
- 位置 + 姿勢：`<x> <y> <z> <roll> <pitch> <yaw>`（度）

**例**：
```bash
uv run python example/6_ik_test.py
> 0.25 0.0 0.15              # 位置のみ
> 0.25 0.0 0.15 0 0 0        # 位置 + 姿勢
```

---

### 実機制御

:::tip 権限設定
実機制御サンプルを実行する前に、デバイスの権限を設定する必要があります：

```bash
# シリアルデバイスの権限を設定（達妙 USB2CAN）
sudo chmod 666 /dev/ttyACM0

# または CAN インターフェース（例：can0）
sudo chmod 666 /dev/can0
```
:::

#### 7️⃣ IK リアルタイム制御 (`7_arm_ik_control.py`)

IK ソルバーに基づくロボットアームリアルタイムエンドエフェクタ制御。

**インタラクティブコマンド**：
| コマンド | 説明 |
|---------|------|
| `x y z [roll pitch yaw]` | 目標エンドエフェクタ姿勢 |
| `state` | 現在の状態/目標状態 |
| `pos` | 現在のエンドエフェクタ位置 |
| `q/quit/exit` | 終了 |

**使用方法**：
```bash
uv run python example/7_arm_ik_control.py
> 0.3 0.0 0.2
> 0.3 0.1 0.25 0 0.5 0
```

---

#### 8️⃣ 軌道計画制御 (`8_arm_traj_control.py`)

SE(3) 測地線軌道計画 + CLIK 追従。

**入力形式**：
```
x y z [roll pitch yaw] [duration]
```

**パラメータ**：
- `x, y, z`: 目標位置（メートル）
- `roll, pitch, yaw`: 目標姿勢（ラジアン）
- `duration`: 移動時間（秒）、デフォルト 2.0 秒

**使用方法**：
```bash
uv run python example/8_arm_traj_control.py
> 0.3 0.0 0.3 0 0.4 0 2.0
```

---

#### 9️⃣ 重力補償制御 (`9_gravity_compensation.py`)

Pinocchio 动力学モデルを使用して関節の重力を補償します。

**制御則**：
```
tau = g(q)          — 重力フォワード
pos = 現在のモーター位置 — 関節位置は現在位置に従う
kp = 2,  kd = 1     — すべての関節で統一された剛性/ダンピング
```

**期待される動作**：
- ロボットアームは任意の姿勢で「浮遊」できます
- 離しても自重で落下しません
- 任意の位置に手で動かすことができます

**使用方法**：
```bash
uv run python example/9_gravity_compensation.py
```

**出力**：
- 各関節の期待トルクをリアルタイム表示（N·m）
- `Ctrl+C` で停止して接続を切断

---

## 📄 ライセンス

本プロジェクトは **MIT ライセンス** の下でオープンソースです。

---

## ☎ お問い合わせ

- **技術サポート**: [Issue を提出](https://github.com/vectorBH6/reBotArm_control_py/issues)
- **リポジトリ**: [GitHub](https://github.com/vectorBH6/reBotArm_control_py)

---

<p align="center">
  <strong>🌟 このプロジェクトが役に立った場合は、Star をつけてサポートしてください！</strong>
</p>
