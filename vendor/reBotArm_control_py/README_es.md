# Guía de Inicio de Pinocchio y MeshCat para reBot Arm B601-DM

<p align="center">
    <a href="./LICENSE">
        <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="Licencia: MIT">
    </a>
    <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Versión Python">
    <img src="https://img.shields.io/badge/Plataforma-Linux%20%7C%20Ubuntu-orange.svg" alt="Plataforma">
    <img src="https://img.shields.io/badge/Framework-Pinocchio-yellow.svg" alt="Pinocchio">
</p>

<p align="center">
  <strong>Brazo Robótico de 6-DOF · Soporte Multi-Motores · Solucionador Cinemático · Planificación de Trayectoria · Totalmente Open Source</strong>
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

## 📖 Introducción

**reBotArm Control** es una biblioteca de control Python para el brazo robótico reBot Arm B601, que proporciona una solución completa desde el control de motores de bajo nivel hasta el cálculo cinemático de alto nivel.

### ✨ Características Principales

- 🦾 **Doble Modelo** — B601-DM (motores Damiao) y B601-RS (motores RobStride)
- 🧮 **Solucionador Cinemático** — Cinemática directa/inversa basada en Pinocchio
- 🛤️ **Planificación de Trayectoria** — Trayectoria geodésica SE(3) + seguimiento CLIK
- 🔧 **Configuración Flexible** — Archivo de configuración YAML para adaptación rápida del hardware

---

## ⚙️ Inicio Rápido

### Requisitos del Sistema

| Elemento | Requisito |
|---------|-----------|
| **Python** | 3.10+ |
| **Sistema Operativo** | Ubuntu 22.04+ |
| **Interfaz de Comunicación** | Puente Serie USB2CAN o Interfaz CAN |

### Pasos de Instalación

#### Paso 1. Instalar uv (si no está instalado)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Paso 2. Sincronizar Entorno (Instalar Todas las Dependencias)

```bash
git clone https://github.com/vectorBH6/reBotArm_control_py.git
cd reBotArm_control_py
uv sync
```

:::tip
`uv sync` creará automáticamente un entorno virtual (si no existe) e instalará todas las dependencias según `pyproject.toml` y `uv.lock`.
:::

---

## 🔌 Configuración de Hardware

### Predeterminado: Puente Serie Damiao USB2CAN

El reBot Arm B601-DM utiliza por defecto el módulo de puente serie Damiao USB2CAN.

**Conexión de Hardware**:
1. Conecte el módulo USB2CAN a su computadora mediante cable USB
2. El sistema lo reconocerá automáticamente como dispositivo `/dev/ttyACM0`

**Verificación de Configuración**:
```bash
# Verificar dispositivo
ls /dev/ttyACM0

# Escanear motores
motorbridge-cli scan --vendor damiao --transport dm-serial \
    --serial-port /dev/ttyACM0 --serial-baud 921600
```

### Opcional: Interfaz CAN Estándar

Uso de otros adaptadores USB-CAN (CANable, PCAN, etc.):

```bash
# Iniciar interfaz CAN
sudo ip link set can0 up type can bitrate 500000

# Verificar interfaz
ip -details link show can0
```

### Configuración de Marcas de Motores

| Marca de Motor | Transmisión | Configuración | Baud Rate |
|---------------|-------------|---------------|-----------|
| **Damiao** | Puente Serie | `dm-serial` | 921600 |
| **Damiao** | Interfaz CAN | `socketcan` | 500000 |
| **RobStride** | Interfaz CAN | `socketcan` | 500000 |

:::tip
- Para motores Damiao usando puente serie, debe establecer `--transport dm-serial`
- Regla de ID de feedback: `feedback_id = motor_id + 0x10`
:::

---

## 📁 Estructura del Proyecto

```
reBotArm_control_py/
├── config/                     # Archivos de configuración
│   └── robot.yaml              # Configuración de parámetros de articulaciones
├── example/                    # Programas de ejemplo
│   ├── Herramientas de Depuración/
│   │   ├── 1_damiao_text.py        # Consola mono-motor
│   │   └── 2_zero_and_read.py      # Calibración cero
│   ├── Pruebas Cinemáticas/
│   │   ├── 5_fk_test.py            # Cinemática directa
│   │   └── 6_ik_test.py            # Cinemática inversa
│   ├── Control Real/
│   │   ├── 7_arm_ik_control.py     # Control IK tiempo real
│   │   ├── 8_arm_traj_control.py   # Planificación de trayectoria
│   │   └── 9_gravity_compensation.py  # Compensación de gravedad
│   └── sim/                    # Herramientas de simulación
├── reBotArm_control_py/        # Biblioteca principal
│   ├── actuator/               # Módulo de actuador
│   ├── kinematics/             # Módulo de cinemática
│   ├── controllers/            # Módulo de controlador
│   └── trajectory/             # Módulo de planificación de trayectoria
├── urdf/                       # Modelo URDF
└── README.md
```

---

## 🎮 Programas de Ejemplo

### Herramientas de Depuración

#### 1️⃣ Consola Mono-Motor (`1_damiao_text.py`)

Prueba directa de un solo motor con el SDK motorbridge, soporta tres modos de control.

**Uso**:
```bash
uv run python example/1_damiao_text.py
```

**Comandos Interactivos**:
| Comando | Descripción |
|---------|-------------|
| `mit <pos_deg> [vel kp kd tau]` | Modo MIT |
| `posvel <pos_deg> [vlim]` | Modo POS_VEL |
| `vel <vel_rad_s>` | Modo Velocidad |
| `enable` / `disable` | Habilitar/Deshabilitar |
| `set_zero` | Establecer posición cero |
| `state` | Ver estado |

---

#### 2️⃣ Calibración Cero y Monitoreo de Ángulo (`2_zero_and_read.py`)

Establece automáticamente los ceros de todas las articulaciones y muestra los ángulos en tiempo real.

**Uso**:
```bash
uv run python example/2_zero_and_read.py
```

---

### Pruebas Cinemáticas

#### 5️⃣ Prueba de Cinemática Directa (`5_fk_test.py`)

Calcula la pose del efector terminal desde los ángulos de las articulaciones.

**Entrada**: 6 ángulos de articulaciones (grados)

**Salida**:
- Posición del efector (X, Y, Z) — Unidad: metros
- Matriz de rotación (3×3)
- Ángulos de Euler (Roll/Pitch/Yaw) — Unidad: grados

**Ejemplo**:
```bash
uv run python example/5_fk_test.py
> 0 0 0 0 0 0
> 45 -30 15 -60 90 180
```

---

#### 6️⃣ Prueba de Cinemática Inversa (`6_ik_test.py`)

Resuelve los ángulos de las articulaciones desde la pose deseada del efector.

**Formato de Entrada**:
- Solo posición: `<x> <y> <z>` (metros)
- Posición + Orientación: `<x> <y> <z> <roll> <pitch> <yaw>` (grados)

**Ejemplo**:
```bash
uv run python example/6_ik_test.py
> 0.25 0.0 0.15              # Solo posición
> 0.25 0.0 0.15 0 0 0        # Posición + Orientación
```

---

### Control Real

:::tip Configuración de Permisos
Antes de ejecutar los ejemplos de control real, necesita configurar los permisos del dispositivo:

```bash
# Establecer permiso del dispositivo serie (Damiao USB2CAN)
sudo chmod 666 /dev/ttyACM0

# O para la interfaz CAN (por ejemplo can0)
sudo chmod 666 /dev/can0
```
:::

#### 7️⃣ Control IK en Tiempo Real (`7_arm_ik_control.py`)

Control en tiempo real del efector basado en el solucionador IK.

**Comandos Interactivos**:
| Comando | Descripción |
|---------|-------------|
| `x y z [roll pitch yaw]` | Pose objetivo del efector |
| `state` | Ver estado actual/objetivo |
| `pos` | Posición actual del efector |
| `q/quit/exit` | Salir |

**Uso**:
```bash
uv run python example/7_arm_ik_control.py
> 0.3 0.0 0.2
> 0.3 0.1 0.25 0 0.5 0
```

---

#### 8️⃣ Control de Planificación de Trayectoria (`8_arm_traj_control.py`)

Planificación de trayectoria geodésica SE(3) + seguimiento CLIK.

**Formato de Entrada**:
```
x y z [roll pitch yaw] [duration]
```

**Parámetros**:
- `x, y, z`: Posición objetivo (metros)
- `roll, pitch, yaw`: Orientación objetivo (radianes)
- `duration`: Duración del movimiento (segundos), predeterminado 2.0s

**Uso**:
```bash
uv run python example/8_arm_traj_control.py
> 0.3 0.0 0.3 0 0.4 0 2.0
```

---

#### 9️⃣ Control de Compensación de Gravedad (`9_gravity_compensation.py`)

Compensa la gravedad de las articulaciones usando el modelo dinámico Pinocchio.

**Ley de Control**:
```
tau = g(q)          — Compensación de gravedad
pos = posición actual del motor  — La posición sigue la posición actual
kp = 2,  kd = 1     — Rigidez/amortiguación unificadas para todos los motores
```

**Comportamiento Esperado**:
- El brazo robótico puede "flotar" en cualquier postura
- No se cae por su propio peso cuando se suelta
- Se puede mover manualmente a cualquier posición

**Uso**:
```bash
uv run python example/9_gravity_compensation.py
```

**Salida**:
- Visualización en tiempo real del par esperado para cada articulación (N·m)
- Presione `Ctrl+C` para detener y desconectar

---

## 📄 Licencia

Este proyecto es de código abierto bajo la **Licencia MIT**.

---

## ☎ Contáctenos

- **Soporte Técnico**: [Enviar Issue](https://github.com/vectorBH6/reBotArm_control_py/issues)
- **Repositorio**: [GitHub](https://github.com/vectorBH6/reBotArm_control_py)

---

<p align="center">
  <strong>🌟 ¡Si este proyecto le es útil, por favor denos una Star!</strong>
</p>
