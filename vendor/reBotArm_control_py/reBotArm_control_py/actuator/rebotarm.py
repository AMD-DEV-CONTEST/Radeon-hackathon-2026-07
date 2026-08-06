"""reBotArm 分组控制系统 — JointGroup 架构。

配置驱动的硬件抽象层：
  - 所有参数均在 config/rebotarm.yaml 中定义（hardware_yaml 指定硬件配置文件）
  - 关节按 groups 分组，每组独立控制模式
  - 统一 loop 中按组顺序同步发送，防止总线争用

使用示例::

    # arm 组 POS_VEL，gripper 组 MIT（解耦混合控制）
    arm = RebotArm()
    arm.connect()
    arm.arm.enable()
    arm.gripper.enable()
    arm.arm.mode_pos_vel()
    arm.gripper.mode_mit()

    def loop(ref, dt):
        ref.arm.send_pos_vel(joint_pos)
        ref.gripper.send_mit(gripper_pos)

    arm.start_control_loop(loop)

    # 全部组 MIT（纯测试）
    arm.arm.mode_mit()
    arm.gripper.mode_mit()

    arm.disconnect()
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import yaml

from motorbridge import Controller, Mode, CallError

_CFG_DIR = Path(__file__).parent.parent.parent / "config"
_GLOBAL_CFG = _CFG_DIR / "rebotarm.yaml"


def _resolve_hw_cfg_path(hw_yaml: str | None = None) -> Path:
    if hw_yaml is None:
        if not _GLOBAL_CFG.exists():
            raise FileNotFoundError(f"{_GLOBAL_CFG} not found")
        data = yaml.safe_load(_GLOBAL_CFG.read_text())
        hw_yaml = data.get("hardware_yaml") if data else None
        if not hw_yaml:
            raise ValueError("hardware_yaml not set in rebotarm.yaml")

    p = Path(hw_yaml)
    if p.is_absolute():
        return p
    path = _CFG_DIR / hw_yaml
    if path.exists():
        return path
    raise FileNotFoundError(f"hardware config not found: {path}")


# --------------------------------------------------------------------------
# 配置加载
# --------------------------------------------------------------------------

@dataclass
class JointCfg:
    name: str
    motor_id: int
    feedback_id: int
    model: str
    vendor: str = "damiao"
    kp: float = 0.0
    kd: float = 0.0
    vel_kp: float = 0.0
    vel_ki: float = 0.0
    pos_kp: float = 0.0
    pos_ki: float = 0.0
    vlim: float = 0.0


def load_cfg(hw_yaml: str | None = None) -> dict:
    hw_path = _resolve_hw_cfg_path(hw_yaml)

    with open(hw_path, "r") as f:
        data = yaml.safe_load(f)

    joints = []
    for j in data.get("joints", []):
        mc = j.get("MIT", {})
        pc = j.get("POS_VEL", {})
        joints.append(JointCfg(
            name=j["name"],
            motor_id=int(j["motor_id"]),
            feedback_id=int(j["feedback_id"]),
            model=str(j.get("model", "4340P")),
            vendor=str(j.get("vendor", "damiao")).lower(),
            kp=float(mc.get("kp", 0.0)),
            kd=float(mc.get("kd", 0.0)),
            vel_kp=float(pc.get("vel_kp", 0.0)),
            vel_ki=float(pc.get("vel_ki", 0.0)),
            pos_kp=float(pc.get("pos_kp", 0.0)),
            pos_ki=float(pc.get("pos_ki", 0.0)),
            vlim=float(pc.get("vlim", 2.0)),
        ))

    return {
        "name": data.get("name", "reBotArm"),
        "channel": data.get("channel", "/dev/ttyACM0"),
        "rate": float(data.get("rate", 500.0)),
        "groups": data.get("groups", {}),
        "joints": joints,
    }


# --------------------------------------------------------------------------
# NoOpGroup — 无执行器时的空操作桩
# --------------------------------------------------------------------------

class NoOpGroup:
    """当配置中不存在 gripper 组时的空实现。

    所有属性和方法与 JointGroup 接口兼容，但不对电机发送任何指令，
    方便用户代码在有/无夹爪时共用同一套逻辑，无需条件判断。
    """

    name: str = "gripper"
    _mode: str = "mit"

    @property
    def num_joints(self) -> int:
        return 0

    @property
    def joint_names(self) -> List[str]:
        return []

    @property
    def mode(self) -> str:
        return "mit"

    def enable(self) -> None:
        pass

    def disable(self) -> None:
        pass

    def mode_mit(self, kp=None, kd=None) -> bool:
        self._mode = "mit"
        return True

    def mode_pos_vel(self, vlim=None) -> bool:
        self._mode = "pos_vel"
        return True

    def mode_vel(self) -> bool:
        self._mode = "vel"
        return True

    def send_mit(self, pos, vel=None, kp=None, kd=None, tau=None) -> None:
        pass

    def send_pos_vel(self, pos, vlim=None) -> None:
        pass

    def send_vel(self, vel) -> None:
        pass

    def get_positions(self) -> np.ndarray:
        return np.array([], dtype=np.float64)

    def get_velocities(self) -> np.ndarray:
        return np.array([], dtype=np.float64)

    def __repr__(self) -> str:
        return "NoOpGroup(gripper, no actuator)"


# --------------------------------------------------------------------------
# JointGroup — 单组关节控制
# --------------------------------------------------------------------------

class JointGroup:
    """一组关节的独立控制器。

    每组拥有独立的控制模式（MIT / POS_VEL）、PID 参数和电机列表，
    可单独使能、切换模式、发送命令。

    由 RebotArm 通过 __getattr__ 代理访问，例如 arm.arm / arm.gripper。
    组内关节数量、顺序由配置决定。
    """

    def __init__(
        self,
        name: str,
        joint_names: List[str],
        all_joints: List[JointCfg],
        motor_map: Dict[str, any],
        ctrl_map: Dict[str, Controller],
    ) -> None:
        self.name = name
        self._jn: List[str] = joint_names
        self._jcfgs: List[JointCfg] = [
            next(j for j in all_joints if j.name == n) for n in joint_names
        ]
        self._mm: Dict[str, any] = motor_map
        self._cm: Dict[str, Controller] = ctrl_map
        self._mode: str = "mit"
        self._mit_kp: np.ndarray = np.array([j.kp for j in self._jcfgs], dtype=np.float64)
        self._mit_kd: np.ndarray = np.array([j.kd for j in self._jcfgs], dtype=np.float64)
        self._pv_vlim: np.ndarray = np.array([j.vlim for j in self._jcfgs], dtype=np.float64)

    # ── 属性 ────────────────────────────────────────────────────────────

    @property
    def num_joints(self) -> int:
        return len(self._jn)

    @property
    def joint_names(self) -> List[str]:
        return list(self._jn)

    @property
    def mode(self) -> str:
        return self._mode

    # ── 使能 / 失能 ────────────────────────────────────────────────────

    def enable(self) -> None:
        by_vendor: Dict[str, List[str]] = {}
        for jc in self._jcfgs:
            by_vendor.setdefault(jc.vendor, []).append(jc.name)
        for vendor in by_vendor:
            try:
                self._cm[vendor].enable_all()
            except CallError as e:
                print(f"[{self.name}/enable] {e}")
            time.sleep(0.05)

    def disable(self) -> None:
        by_vendor: Dict[str, List[str]] = {}
        for jc in self._jcfgs:
            by_vendor.setdefault(jc.vendor, []).append(jc.name)
        for vendor in by_vendor:
            try:
                self._cm[vendor].disable_all()
            except CallError as e:
                print(f"[{self.name}/disable] {e}")
            time.sleep(0.05)

    # ── 模式切换 ────────────────────────────────────────────────────────

    def _write_pv_params(self, jc: JointCfg) -> None:
        m = self._mm[jc.name]
        try:
            if jc.vendor == "robstride":
                m.robstride_write_param_f32(0x7017, jc.vlim)
                time.sleep(0.01)
                m.robstride_write_param_f32(0x701F, jc.vel_kp)
                time.sleep(0.01)
                m.robstride_write_param_f32(0x7020, jc.vel_ki)
                time.sleep(0.01)
                m.robstride_write_param_f32(0x701E, jc.pos_kp)
            elif jc.vendor == "damiao":
                m.write_register_f32(25, jc.vel_kp)
                m.write_register_f32(26, jc.vel_ki)
                m.write_register_f32(27, jc.pos_kp)
                m.write_register_f32(28, jc.pos_ki)
            time.sleep(0.02)
        except Exception as e:
            print(f"[{self.name}/pv_params/{jc.name}] {e}")

    def mode_mit(
        self,
        kp: Optional[np.ndarray] = None,
        kd: Optional[np.ndarray] = None,
    ) -> bool:
        self._mode = "mit"
        if kp is not None:
            self._mit_kp = np.asarray(kp, dtype=np.float64).reshape(-1)
        if kd is not None:
            self._mit_kd = np.asarray(kd, dtype=np.float64).reshape(-1)
        ok = True
        for jc in self._jcfgs:
            try:
                self._mm[jc.name].ensure_mode(Mode.MIT, 1000)
            except CallError as e:
                print(f"[{self.name}/mode_mit/{jc.name}] {e}")
                ok = False
            time.sleep(0.05)
        time.sleep(0.2)
        return ok

    def mode_pos_vel(
        self,
        vlim: Optional[np.ndarray] = None,
    ) -> bool:
        self._mode = "pos_vel"
        if vlim is not None:
            self._pv_vlim = np.asarray(vlim, dtype=np.float64).reshape(-1)
        ok = True
        for jc in self._jcfgs:
            self._write_pv_params(jc)
            try:
                self._mm[jc.name].ensure_mode(Mode.POS_VEL, 1000)
            except CallError as e:
                print(f"[{self.name}/mode_pos_vel/{jc.name}] {e}")
                ok = False
            time.sleep(0.05)
        time.sleep(0.2)
        return ok

    def mode_vel(self) -> bool:
        self._mode = "vel"
        ok = True
        for jc in self._jcfgs:
            try:
                self._mm[jc.name].ensure_mode(Mode.VEL, 1000)
            except CallError as e:
                print(f"[{self.name}/mode_vel/{jc.name}] {e}")
                ok = False
            time.sleep(0.05)
        time.sleep(0.2)
        return ok

    # ── MIT 发送 ────────────────────────────────────────────────────────

    def send_mit(
        self,
        pos: np.ndarray,
        vel: Optional[np.ndarray] = None,
        kp: Optional[np.ndarray] = None,
        kd: Optional[np.ndarray] = None,
        tau: Optional[np.ndarray] = None,
    ) -> None:
        n = self.num_joints
        pos = np.asarray(pos, dtype=np.float64).reshape(-1)
        if vel is None:
            vel = np.zeros(n)
        if tau is None:
            tau = np.zeros(n)
        if kp is None:
            kp = self._mit_kp
        if kd is None:
            kd = self._mit_kd

        for i, jc in enumerate(self._jcfgs):
            try:
                self._mm[jc.name].send_mit(
                    float(pos[i]),
                    float(vel[i]),
                    float(kp[i]),
                    float(kd[i]),
                    float(tau[i]),
                )
            except CallError:
                pass

    # ── POS_VEL 发送 ───────────────────────────────────────────────────

    def send_pos_vel(
        self,
        pos: np.ndarray,
        vlim: Optional[np.ndarray] = None,
    ) -> None:
        pos = np.asarray(pos, dtype=np.float64).reshape(-1)
        if vlim is None:
            vlim = self._pv_vlim
        vlim = np.asarray(vlim, dtype=np.float64).reshape(-1)
        for i in range(min(len(pos), len(vlim))):
            try:
                self._mm[self._jcfgs[i].name].send_pos_vel(
                    float(pos[i]),
                    float(vlim[i]),
                )
            except CallError:
                pass

    # ── VEL 发送 ───────────────────────────────────────────────────────

    def send_vel(self, vel: np.ndarray) -> None:
        vel = np.asarray(vel, dtype=np.float64).reshape(-1)
        for i in range(min(len(vel), self.num_joints)):
            try:
                self._mm[self._jcfgs[i].name].send_vel(float(vel[i]))
            except CallError:
                pass

    # ── 状态读取 ───────────────────────────────────────────────────────

    def _request_feedback(self) -> None:
        seen: set[str] = set()
        for jc in self._jcfgs:
            try:
                self._mm[jc.name].request_feedback()
            except Exception:
                pass
            if jc.vendor not in seen:
                seen.add(jc.vendor)
                try:
                    self._cm[jc.vendor].poll_feedback_once()
                except Exception:
                    pass

    def get_positions(self, request_feedback: bool = True) -> np.ndarray:
        if request_feedback:
            self._request_feedback()
        return np.array([
            self._mm[jc.name].get_state().pos
            if self._mm[jc.name].get_state() is not None else 0.0
            for jc in self._jcfgs
        ], dtype=np.float64)

    def get_velocities(self, request_feedback: bool = True) -> np.ndarray:
        if request_feedback:
            self._request_feedback()
        return np.array([
            self._mm[jc.name].get_state().vel
            if self._mm[jc.name].get_state() is not None else 0.0
            for jc in self._jcfgs
        ], dtype=np.float64)

    def __repr__(self) -> str:
        return f"JointGroup({self.name!r}, joints={self.num_joints}, mode={self._mode})"


# --------------------------------------------------------------------------
# RebotArm — 分组控制器容器
# --------------------------------------------------------------------------

class RebotArm:
    """reBotArm 分组控制系统。

    持有多个 JointGroup，每组独立控制模式，独立发送命令，
    在同一个控制循环中按组顺序同步发送，防止总线争用。

    按组访问（通过 __getattr__）::

        arm.arm       # 机械臂关节组
        arm.gripper   # 夹爪关节组（如果有）

    也可以通过 groups 字典::

        arm.groups["arm"]
        arm.groups["gripper"]

    手动添加组::

        arm.add_group("custom", ["joint1", "joint2"])
    """

    def __init__(self, hw_yaml: str | None = None) -> None:
        self._hw_yaml = _resolve_hw_cfg_path(hw_yaml).name
        cfg = load_cfg(hw_yaml)

        self._name: str = cfg["name"]
        self._channel: str = cfg["channel"]
        self._rate: float = cfg["rate"]
        self._all_joints: List[JointCfg] = cfg["joints"]
        self._groups_def: dict = cfg["groups"]

        self._ctrl_map: Dict[str, Controller] = {}
        self._motor_map: Dict[str, any] = {}
        self._groups: Dict[str, JointGroup] = {}

        self._running = False
        self._ctrl_thread: Optional[threading.Thread] = None
        self._ctrl_fn: Optional[Callable] = None
        self._ctrl_rate: float = self._rate
        self._connected: bool = False

        self._build_groups()

    def connect(self) -> None:
        """连接总线、注册电机。模式切换需在 connect 后调用。"""
        if self._connected:
            return
        self._setup_motors()
        self._connected = True

    def _make_controller(self, vendor: str) -> Controller:
        if self._channel.startswith("/dev/tty"):
            return Controller.from_dm_serial(self._channel, 921600)
        return Controller(self._channel)

    def _setup_motors(self) -> None:
        for jc in self._all_joints:
            vendor = jc.vendor
            if vendor not in self._ctrl_map:
                self._ctrl_map[vendor] = self._make_controller(vendor)
            ctrl = self._ctrl_map[vendor]

            if vendor == "damiao":
                mot = ctrl.add_damiao_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif vendor == "robstride":
                mot = ctrl.add_robstride_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif vendor == "myactuator":
                mot = ctrl.add_myactuator_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif vendor == "hightorque":
                mot = ctrl.add_hightorque_motor(jc.motor_id, jc.feedback_id, jc.model)
            else:
                raise ValueError(f"Unsupported vendor: {vendor}")

            self._motor_map[jc.name] = mot

    def _build_groups(self) -> None:
        for gname, gdef in self._groups_def.items():
            joints_def = gdef.get("joints", [])
            g = JointGroup(
                name=gname,
                joint_names=joints_def,
                all_joints=self._all_joints,
                motor_map=self._motor_map,
                ctrl_map=self._ctrl_map,
            )
            self._groups[gname] = g
        if "gripper" not in self._groups:
            self._groups["gripper"] = NoOpGroup()

    # ── 属性 ────────────────────────────────────────────────────────────

    @property
    def num_joints(self) -> int:
        return len(self._all_joints)

    @property
    def joint_names(self) -> List[str]:
        return [j.name for j in self._all_joints]

    @property
    def groups(self) -> Dict[str, JointGroup]:
        return self._groups

    @property
    def control_loop_active(self) -> bool:
        t = getattr(self, "_ctrl_thread", None)
        return t is not None and t.is_alive()

    @property
    def rate(self) -> float:
        return self._ctrl_rate

    @property
    def has_gripper(self) -> bool:
        return not isinstance(self._groups.get("gripper", None), NoOpGroup)

    @property
    def hardware_yaml(self) -> str:
        return self._hw_yaml

    def __getattr__(self, name: str) -> any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._groups:
            return self._groups[name]
        raise AttributeError(name)

    # ── 手动添加组 ────────────────────────────────────────────────────

    def add_group(self, name: str, joint_names: List[str]) -> JointGroup:
        if name in self._groups:
            raise ValueError(f"组 {name!r} 已存在")
        g = JointGroup(
            name=name,
            joint_names=joint_names,
            all_joints=self._all_joints,
            motor_map=self._motor_map,
            ctrl_map=self._ctrl_map,
        )
        self._groups[name] = g
        return g

    # ── 全局使能 / 失能 ────────────────────────────────────────────────

    def enable_all(self) -> None:
        for g in self._groups.values():
            g.enable()

    def disable_all(self) -> None:
        for g in self._groups.values():
            g.disable()

    # ── 零点 ────────────────────────────────────────────────────────────

    def set_zero(self, poll_max: int = 200, poll_interval: float = 0.05) -> None:
        self.disable_all()
        time.sleep(0.3)
        for jc in self._all_joints:
            for _ in range(poll_max):
                for m in self._motor_map.values():
                    try:
                        m.request_feedback()
                    except Exception:
                        pass
                for ctrl in self._ctrl_map.values():
                    try:
                        ctrl.poll_feedback_once()
                    except Exception:
                        pass
                st = self._motor_map[jc.name].get_state()
                if st is not None and st.status_code == 0:
                    break
                time.sleep(poll_interval)
            try:
                self._motor_map[jc.name].set_zero_position()
            except CallError as e:
                print(f"[set_zero] {jc.name}: {e}")
            time.sleep(0.1)

    # ── 全局状态读取 ───────────────────────────────────────────────────

    def get_state(
        self,
        request_feedback: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if request_feedback:
            for m in self._motor_map.values():
                try:
                    m.request_feedback()
                except Exception:
                    pass
        for ctrl in self._ctrl_map.values():
            try:
                ctrl.poll_feedback_once()
            except Exception:
                pass
        pos, vel, torq = [], [], []
        for jc in self._all_joints:
            st = self._motor_map[jc.name].get_state()
            if st is not None:
                pos.append(st.pos)
                vel.append(st.vel)
                torq.append(st.torq)
            else:
                pos.append(0.0)
                vel.append(0.0)
                torq.append(0.0)
        return (
            np.array(pos, dtype=np.float64),
            np.array(vel, dtype=np.float64),
            np.array(torq, dtype=np.float64),
        )

    def get_positions(self) -> np.ndarray:
        return self.get_state()[0]

    def get_velocities(self) -> np.ndarray:
        return self.get_state()[1]

    def get_torques(self) -> np.ndarray:
        return self.get_state()[2]

    # ── 生命周期 ────────────────────────────────────────────────────────

    def disconnect(self) -> None:
        if not self._connected:
            return
        self.stop_control_loop()
        self.disable_all()
        time.sleep(0.5)
        for ctrl in self._ctrl_map.values():
            ctrl.shutdown()
            time.sleep(0.1)
            ctrl.close()
        self._ctrl_map.clear()
        self._motor_map.clear()
        self._connected = False

    def estop(self) -> None:
        self.disable_all()

    def reconnect(
        self,
        init_delay: float = 1.0,
        post_setup_delay: float = 0.5,
    ) -> None:
        self.disconnect()
        time.sleep(init_delay)
        for vendor in set(j.vendor for j in self._all_joints):
            self._ctrl_map[vendor] = self._make_controller(vendor)
        self._motor_map.clear()
        for jc in self._all_joints:
            ctrl = self._ctrl_map[jc.vendor]
            if jc.vendor == "damiao":
                mot = ctrl.add_damiao_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif jc.vendor == "robstride":
                mot = ctrl.add_robstride_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif jc.vendor == "myactuator":
                mot = ctrl.add_myactuator_motor(jc.motor_id, jc.feedback_id, jc.model)
            elif jc.vendor == "hightorque":
                mot = ctrl.add_hightorque_motor(jc.motor_id, jc.feedback_id, jc.model)
            else:
                raise ValueError(f"Unsupported vendor: {jc.vendor}")
            self._motor_map[jc.name] = mot
            time.sleep(0.05)
        self._build_groups()
        time.sleep(post_setup_delay)
        print("[reconnect] 控制器和电机已重新初始化")

    # ── 控制循环 ────────────────────────────────────────────────────────

    def start_control_loop(
        self,
        control_fn: Callable[["RebotArm", float], None],
        rate: Optional[float] = None,
    ) -> None:
        if self.control_loop_active:
            raise RuntimeError("控制循环已在运行，请先调用 stop_control_loop()")
        self._running = True
        self._ctrl_rate = rate if rate is not None else self._rate
        self._ctrl_fn = control_fn
        self._ctrl_thread = threading.Thread(
            target=self._control_loop_impl,
            name="rebotarm-control-loop",
            daemon=True,
        )
        self._ctrl_thread.start()

    def _control_loop_impl(self) -> None:
        dt = 1.0 / self._ctrl_rate
        while self._running:
            t0 = time.perf_counter()
            try:
                self._ctrl_fn(self, dt)
            except Exception:
                if self._running:
                    raise
            elapsed = time.perf_counter() - t0
            sleep_time = dt - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop_control_loop(self) -> None:
        self._running = False
        t = getattr(self, "_ctrl_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout=5.0)

    # ── 上下文管理器 ───────────────────────────────────────────────────────

    def __enter__(self) -> "RebotArm":
        return self

    def __exit__(self, *args) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        gs = ", ".join(f"{k}({g.num_joints}j)" for k, g in self._groups.items())
        return f"RebotArm({self._name!r}, [{gs}], rate={self._ctrl_rate}Hz)"
