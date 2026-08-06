# Guide de Démarrage Pinocchio & MeshCat pour reBot Arm B601-DM

<p align="center">
    <a href="./LICENSE">
        <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
    </a>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Version Python">
    <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Ubuntu-orange.svg" alt="Plateforme">
    <img src="https://img.shields.io/badge/Framework-Pinocchio-yellow.svg" alt="Pinocchio">
</p>

<p align="center">
  <strong>Bras Robotique 6-DOF · Support Multi-Moteurs · Solveur Cinématique · Planification de Trajectoire · Entièrement Open Source</strong>
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

## 📖 Introduction

**reBotArm Control** est une bibliothèque de contrôle Python pour le bras robotique reBot Arm B601, fournissant une solution complète du contrôle des moteurs de bas niveau au calcul cinématique de haut niveau.

### ✨ Fonctionnalités Principales

- 🦾 **Double Modèle** — B601-DM (moteurs Damiao) et B601-RS (moteurs RobStride)
- 🧮 **Solveur Cinématique** — Cinématique directe/inverse basée sur Pinocchio
- 🛤️ **Planification de Trajectoire** — Trajectoire géodésique SE(3) + suivi CLIK
- 🔧 **Configuration Flexible** — Fichier de configuration YAML pour une adaptation rapide du matériel

---

## ⚙️ Démarrage Rapide

### Configuration Requise

| Élément | Configuration Requise |
|---------|----------------------|
| **Python** | 3.10+ |
| **Système d'Exploitation** | Ubuntu 22.04+ |
| **Interface de Communication** | Pont série USB2CAN ou Interface CAN |

### Étapes d'Installation

#### Étape 1. Installer uv (si non installé)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Étape 2. Synchroniser l'Environnement (Installer Toutes les Dépendances)

```bash
git clone https://github.com/vectorBH6/reBotArm_control_py.git
cd reBotArm_control_py
uv sync
```

:::tip
`uv sync` créera automatiquement un environnement virtuel (s'il n'existe pas) et installera toutes les dépendances selon `pyproject.toml` et `uv.lock`.
:::

---

## 🔌 Configuration Matérielle

### Par Défaut : Pont Série Damiao USB2CAN

Le reBot Arm B601-DM utilise par défaut le module de pont série Damiao USB2CAN.

**Connexion Matérielle** :
1. Connectez le module USB2CAN à votre ordinateur via un câble USB
2. Le système le reconnaîtra automatiquement comme périphérique `/dev/ttyACM0`

**Vérification de la Configuration** :
```bash
# Vérifier le périphérique
ls /dev/ttyACM0

# Scanner les moteurs
motorbridge-cli scan --vendor damiao --transport dm-serial \
    --serial-port /dev/ttyACM0 --serial-baud 921600
```

### Optionnel : Interface CAN Standard

Utilisation d'autres adaptateurs USB-CAN (CANable, PCAN, etc.) :

```bash
# Démarrer l'interface CAN
sudo ip link set can0 up type can bitrate 500000

# Vérifier l'interface
ip -details link show can0
```

### Configuration des Marques de Moteurs

| Marque de Moteur | Transmission | Configuration | Baud Rate |
|-----------------|--------------|---------------|-----------|
| **Damiao** | Pont Série | `dm-serial` | 921600 |
| **Damiao** | Interface CAN | `socketcan` | 500000 |
| **RobStride** | Interface CAN | `socketcan` | 500000 |

:::tip
- Pour les moteurs Damiao utilisant le pont série, devez définir `--transport dm-serial`
- Règle d'ID de feedback : `feedback_id = motor_id + 0x10`
:::

---

## 📁 Structure du Projet

```
reBotArm_control_py/
├── config/                     # Fichiers de configuration
│   └── robot.yaml              # Configuration des paramètres des articulations
├── example/                    # Programmes d'exemple
│   ├── Outils de Débogage/
│   │   ├── 1_damiao_text.py        # Console mono-moteur
│   │   └── 2_zero_and_read.py      # Calibration zéro
│   ├── Tests Cinématiques/
│   │   ├── 5_fk_test.py            # Cinématique directe
│   │   └── 6_ik_test.py            # Cinématique inverse
│   ├── Contrôle Réel/
│   │   ├── 7_arm_ik_control.py     # Contrôle IK temps réel
│   │   ├── 8_arm_traj_control.py   # Planification de trajectoire
│   │   └── 9_gravity_compensation.py  # Compensation de gravité
│   └── sim/                    # Outils de simulation
├── reBotArm_control_py/        # Bibliothèque principale
│   ├── actuator/               # Module d'actionneur
│   ├── kinematics/             # Module de cinématique
│   ├── controllers/            # Module de contrôleur
│   └── trajectory/             # Module de planification de trajectoire
├── urdf/                       # Modèle URDF
└── README.md
```

---

## 🎮 Programmes d'Exemple

### Outils de Débogage

#### 1️⃣ Console Mono-Moteur (`1_damiao_text.py`)

Test direct d'un seul moteur avec le SDK motorbridge, supporte trois modes de contrôle.

**Utilisation** :
```bash
uv run python example/1_damiao_text.py
```

**Commandes Interactives** :
| Commande | Description |
|---------|-------------|
| `mit <pos_deg> [vel kp kd tau]` | Mode MIT |
| `posvel <pos_deg> [vlim]` | Mode POS_VEL |
| `vel <vel_rad_s>` | Mode Vitesse |
| `enable` / `disable` | Activer/Désactiver |
| `set_zero` | Définir la position zéro |
| `state` | Voir l'état |

---

#### 2️⃣ Calibration Zéro et Surveillance d'Angle (`2_zero_and_read.py`)

Définit automatiquement les zéros de toutes les articulations et affiche les angles en temps réel.

**Utilisation** :
```bash
uv run python example/2_zero_and_read.py
```

---

### Tests Cinématiques

#### 5️⃣ Test de Cinématique Directe (`5_fk_test.py`)

Calcule la pose de l'effecteur terminal à partir des angles des articulations.

**Entrée** : 6 angles d'articulation (degrés)

**Sortie** :
- Position de l'effecteur (X, Y, Z) — Unité : mètres
- Matrice de rotation (3×3)
- Angles d'Euler (Roulis/Tangage/Lacet) — Unité : degrés

**Exemple** :
```bash
uv run python example/5_fk_test.py
> 0 0 0 0 0 0
> 45 -30 15 -60 90 180
```

---

#### 6️⃣ Test de Cinématique Inverse (`6_ik_test.py`)

Résout les angles des articulations à partir de la pose désirée de l'effecteur.

**Format d'Entrée** :
- Position uniquement : `<x> <y> <z>` (mètres)
- Position + Orientation : `<x> <y> <z> <roll> <pitch> <yaw>` (degrés)

**Exemple** :
```bash
uv run python example/6_ik_test.py
> 0.25 0.0 0.15              # Position uniquement
> 0.25 0.0 0.15 0 0 0        # Position + Orientation
```

---

### Contrôle Réel

:::tip Configuration des Permissions
Avant d'exécuter les exemples de contrôle réel, vous devez configurer les permissions du périphérique :

```bash
# Définir la permission du périphérique série (Damiao USB2CAN)
sudo chmod 666 /dev/ttyACM0

# Ou pour l'interface CAN (par exemple can0)
sudo chmod 666 /dev/can0
```
:::

#### 7️⃣ Contrôle IK en Temps Réel (`7_arm_ik_control.py`)

Contrôle en temps réel de l'effecteur basé sur le solveur IK.

**Commandes Interactives** :
| Commande | Description |
|---------|-------------|
| `x y z [roll pitch yaw]` | Pose cible de l'effecteur |
| `state` | Voir l'état actuel/cible |
| `pos` | Position actuelle de l'effecteur |
| `q/quit/exit` | Quitter |

**Utilisation** :
```bash
uv run python example/7_arm_ik_control.py
> 0.3 0.0 0.2
> 0.3 0.1 0.25 0 0.5 0
```

---

#### 8️⃣ Contrôle de Planification de Trajectoire (`8_arm_traj_control.py`)

Planification de trajectoire géodésique SE(3) + suivi CLIK.

**Format d'Entrée** :
```
x y z [roll pitch yaw] [duration]
```

**Paramètres** :
- `x, y, z`: Position cible (mètres)
- `roll, pitch, yaw`: Orientation cible (radians)
- `duration`: Durée du mouvement (secondes), défaut 2.0s

**Utilisation** :
```bash
uv run python example/8_arm_traj_control.py
> 0.3 0.0 0.3 0 0.4 0 2.0
```

---

#### 9️⃣ Contrôle de Compensation de Gravité (`9_gravity_compensation.py`)

Compense la gravité des articulations en utilisant le modèle dynamique Pinocchio.

**Loi de Contrôle** :
```
tau = g(q)          — Compensation de gravité
pos = position actuelle du moteur  — La position suit la position actuelle
kp = 2,  kd = 1     — Rigidité/amortissement unifiés pour tous les moteurs
```

**Comportement Attendu** :
- Le bras robotique peut « flotter » dans n'importe quelle posture
- Ne tombe pas sous son propre poids lorsqu'il est relâché
- Peut être déplacé manuellement vers n'importe quelle position

**Utilisation** :
```bash
uv run python example/9_gravity_compensation.py
```

**Sortie** :
- Affichage en temps réel du couple attendu pour chaque articulation (N·m)
- Appuyez sur `Ctrl+C` pour arrêter et déconnecter

---

## 📄 Licence

Ce projet est open source sous la **Licence MIT**.

---

## ☎ Nous Contacter

- **Support Technique** : [Soumettre un Issue](https://github.com/vectorBH6/reBotArm_control_py/issues)
- **Dépôt** : [GitHub](https://github.com/vectorBH6/reBotArm_control_py)

---

<p align="center">
  <strong>🌟 Si ce projet vous est utile, veuillez nous donner une Star !</strong>
</p>
