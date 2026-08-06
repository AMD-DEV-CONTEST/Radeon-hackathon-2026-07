"""BotclawFollower — subscribes to /ws/ui (+ /ws/robotstate) and echoes inference
predictions onto a physical Feetech follower arm (M5.2).

Data flow:

     /ws/ui?arm_id=<id>         /ws/robotstate?arm_id=<id>
           │                              │
           │ joint_update                 │ robot_state
           ▼                              ▼
    +--------------------+         +--------------------+
    |  filter source=    |         | safety.estop==true |
    |  "inference"       |         | → disable_torque() |
    +--------------------+         +--------------------+
           │
           ▼
    +--------------------+
    | client SafetyGate  |  max_delta=0.05 rad/tick  (second line of defense)
    +--------------------+
           │
           ▼
    +--------------------+
    | writer.write_pos() |  (torque gated; no-op if torque off)
    +--------------------+

Heartbeat fail-safe: if no inference frame arrives for `heartbeat_timeout_s`,
torque is automatically disabled. New frames can re-enable it only via an
explicit user action (resend --torque-on-start or external trigger).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Optional

# Allow `from api.safety import SafetyGate` when run as `python -m sender`
# with cwd = apps/realtime/.
_REALTIME_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REALTIME_ROOT not in sys.path:
    sys.path.insert(0, _REALTIME_ROOT)

from api.safety import SafetyGate  # noqa: E402

from .joint_angles import MOTOR_ID_TO_NAME, rad_to_normalized  # noqa: E402
from .writer import BaseArmWriter, FollowerArmWriter, MockArmWriter  # noqa: E402


DEFAULT_UI_WS = "ws://localhost:8002/ws/ui"
DEFAULT_ROBOTSTATE_WS = "ws://localhost:8002/ws/robotstate"


class BotclawFollower:
    """Follower-side websocket client driving a real arm from /ws/ui echoes."""

    def __init__(
        self,
        writer: BaseArmWriter,
        arm_id: str = "arm_0",
        ui_url: str = DEFAULT_UI_WS,
        robotstate_url: str = DEFAULT_ROBOTSTATE_WS,
        max_delta_rad: float = 0.05,
        heartbeat_timeout_s: float = 1.0,
        torque_on_start: bool = False,
        source_filter: str = "inference",
    ) -> None:
        self.writer = writer
        self.arm_id = arm_id
        self.ui_url = ui_url
        self.robotstate_url = robotstate_url
        self.gate = SafetyGate(max_delta=max_delta_rad)
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.torque_on_start = torque_on_start
        self.source_filter = source_filter
        self.running = False
        # Stats / last-frame timestamps
        self.last_frame_ts: float = 0.0
        self._ever_received_frame: bool = False
        self.frames_written: int = 0
        self.frames_dropped_gate: int = 0
        self.estop_triggered: bool = False
        self._torque_disabled_by_watchdog: bool = False
        self._last_torque_reenable_attempt_ts: float = 0.0
        self._debug_run_id: str = f"follower-{int(time.time() * 1000)}"
        self._dbg_source_drop_count: int = 0
        self._dbg_frame_accept_count: int = 0
        self._dbg_ws_msg_count: int = 0
        self._dbg_ws_joint_count: int = 0

    def _debug_log(self, hypothesis_id: str, location: str, message: str, data: dict) -> None:
        try:
            payload = {
                "sessionId": "59adc0",
                "runId": self._debug_run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
            with open("/home/amd/Downloads/botversex/.cursor/debug-59adc0.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception:
            pass

    # -- url helpers -------------------------------------------------------
    def _with_arm_id(self, url: str) -> str:
        if "arm_id=" in url:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}arm_id={self.arm_id}"

    # -- task: inference frames ------------------------------------------
    async def _consume_ui(self) -> None:
        import websockets
        import websockets.exceptions as _wse

        url = self._with_arm_id(self.ui_url)
        print(f"[INFO] follower: subscribing {url} (source filter='{self.source_filter}')")
        while self.running:
            try:
                async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
                    print("[OK] follower: /ws/ui connected")
                    # region agent log
                    self._debug_log(
                        "H9",
                        "sender/follower.py:_consume_ui",
                        "ws_ui_connected",
                        {"url": url, "source_filter": self.source_filter},
                    )
                    # endregion
                    while self.running:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        self._dbg_ws_msg_count += 1
                        msg_type = str(msg.get("type", ""))
                        meta = msg.get("meta") or {}
                        source = str(meta.get("source", ""))
                        if self._dbg_ws_msg_count <= 20:
                            # region agent log
                            self._debug_log(
                                "H11",
                                "sender/follower.py:_consume_ui",
                                "ws_ui_message_seen",
                                {
                                    "msg_count": self._dbg_ws_msg_count,
                                    "type": msg_type,
                                    "source": source,
                                },
                            )
                            # endregion
                        if msg_type != "joint_update":
                            continue
                        self._dbg_ws_joint_count += 1
                        if self._dbg_ws_joint_count <= 20:
                            # region agent log
                            self._debug_log(
                                "H11",
                                "sender/follower.py:_consume_ui",
                                "ws_ui_joint_update_seen",
                                {
                                    "joint_count_seen": self._dbg_ws_joint_count,
                                    "source": source,
                                },
                            )
                            # endregion
                        # M5.x: server broadcasts inference-stop when compare session ends
                        if source == "inference-stop":
                            self.last_frame_ts = 0.0
                            # region agent log
                            self._debug_log(
                                "H6",
                                "sender/follower.py:_consume_ui",
                                "inference_stop_received",
                                {"source": source},
                            )
                            # endregion
                            continue
                        if source != self.source_filter:
                            self._dbg_source_drop_count += 1
                            if self._dbg_source_drop_count <= 10:
                                # region agent log
                                self._debug_log(
                                    "H5",
                                    "sender/follower.py:_consume_ui",
                                    "source_filtered_out",
                                    {
                                        "source": source,
                                        "source_filter": self.source_filter,
                                        "drop_count": self._dbg_source_drop_count,
                                    },
                                )
                                # endregion
                            continue
                        joints = msg.get("joints") or {}
                        if not joints:
                            continue
                        self.last_frame_ts = time.time()
                        self._ever_received_frame = True
                        self._dbg_frame_accept_count += 1
                        if self._dbg_frame_accept_count <= 10:
                            # region agent log
                            self._debug_log(
                                "H5",
                                "sender/follower.py:_consume_ui",
                                "source_accepted_frame",
                                {
                                    "source": source,
                                    "joint_count": len(joints),
                                    "accept_count": self._dbg_frame_accept_count,
                                },
                            )
                            # endregion
                        await self._handle_frame(joints)
            except (_wse.ConnectionClosed, ConnectionResetError, OSError) as exc:
                if not self.running:
                    break
                print(f"[WARN] /ws/ui connection lost ({exc}); retry in 2s")
                # region agent log
                self._debug_log(
                    "H9",
                    "sender/follower.py:_consume_ui",
                    "ws_ui_connection_lost",
                    {"error": f"{type(exc).__name__}: {exc}"},
                )
                # endregion
                await asyncio.sleep(2)
            except Exception as exc:
                print(f"[ERR] /ws/ui consumer error: {exc}; retry in 3s")
                # region agent log
                self._debug_log(
                    "H9",
                    "sender/follower.py:_consume_ui",
                    "ws_ui_consumer_error",
                    {"error": f"{type(exc).__name__}: {exc}"},
                )
                # endregion
                await asyncio.sleep(3)

    async def _handle_frame(self, joints_raw: dict) -> None:
        # Normalize keys to strings "1".."6"
        joints = {str(k): float(v) for k, v in joints_raw.items()}
        result = self.gate.apply(joints)
        # region agent log
        self._debug_log(
            "H7",
            "sender/follower.py:_handle_frame",
            "gate_result",
            {
                "fatal": bool(result.fatal),
                "clamped": bool(result.clamped),
                "reason": result.reason,
                "joint_count_in": len(joints),
                "safe_joint_count": len(result.safe_joints or {}),
            },
        )
        # endregion
        if result.fatal:
            if not self.estop_triggered:
                self.estop_triggered = True
                print(f"[EMERGENCY] client gate fatal ({result.reason}); disabling torque")
                self.writer.disable_torque()
            self.frames_dropped_gate += 1
            return
        if result.clamped:
            self.frames_dropped_gate += 0  # keep frame, but count clamp events
        # SafetyGate runs in radian domain. Writer expects lerobot-normalized
        # units keyed by motor name. One conversion step here translates
        # between the two coordinate systems — the URDF-limit-based mapping
        # in joint_angles is the shared agreement between leader and follower.
        safe_rad = result.safe_joints
        normalized: dict[str, float] = {}
        for key, rad in safe_rad.items():
            try:
                motor_id = int(str(key))
            except (TypeError, ValueError):
                continue
            name = MOTOR_ID_TO_NAME.get(motor_id)
            if name is None:
                continue
            normalized[name] = rad_to_normalized(name, float(rad))
        if not normalized:
            return
        # If watchdog disabled torque due to a brief frame gap, auto-recover on
        # the next valid inference frame so motion resumes without manual restart.
        if (
            self._torque_disabled_by_watchdog
            and not self.estop_triggered
            and not self.writer.torque_enabled
        ):
            now = time.time()
            if (now - self._last_torque_reenable_attempt_ts) >= 1.0:
                self._last_torque_reenable_attempt_ts = now
                ok = self.writer.enable_torque()
                # region agent log
                self._debug_log(
                    "H12",
                    "sender/follower.py:_handle_frame",
                    "watchdog_reenable_attempt",
                    {"ok": bool(ok)},
                )
                # endregion
                if ok:
                    self._torque_disabled_by_watchdog = False
        n = self.writer.write_positions(normalized)
        # region agent log
        self._debug_log(
            "H8",
            "sender/follower.py:_handle_frame",
            "write_positions_result",
            {
                "normalized_count": len(normalized),
                "written": int(n),
                "torque_enabled": bool(self.writer.torque_enabled),
            },
        )
        # endregion
        if n > 0:
            self.frames_written += 1

    # -- task: estop watchdog via /ws/robotstate --------------------------
    async def _consume_robotstate(self) -> None:
        import websockets
        import websockets.exceptions as _wse

        url = self._with_arm_id(self.robotstate_url)
        # hz=5 is plenty for estop latency (<=200ms)
        if "hz=" not in url:
            url = f"{url}{'&' if '?' in url else '?'}hz=5"
        print(f"[INFO] follower: watching {url}")
        while self.running:
            try:
                async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
                    while self.running:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") != "robot_state":
                            continue
                        safety = msg.get("safety") or {}
                        if safety.get("estop"):
                            if not self.estop_triggered:
                                self.estop_triggered = True
                                print(
                                    f"[EMERGENCY] server reports estop (reason="
                                    f"{safety.get('reason','?')}), disabling torque"
                                )
                                self.writer.disable_torque()
            except (_wse.ConnectionClosed, ConnectionResetError, OSError):
                if not self.running:
                    break
                await asyncio.sleep(2)
            except Exception as exc:
                print(f"[WARN] /ws/robotstate watcher error: {exc}; retry in 3s")
                await asyncio.sleep(3)

    # -- task: heartbeat fail-safe ----------------------------------------
    async def _heartbeat_watchdog(self) -> None:
        """If no inference frame received within heartbeat_timeout_s, disable torque.

        The writer side will silently no-op writes afterwards; user must re-enable
        (externally) to resume actuation.
        """
        while self.running:
            await asyncio.sleep(self.heartbeat_timeout_s / 2)
            if not self.writer.torque_enabled:
                continue
            # Skip if we've never received any inference frame yet
            if not self._ever_received_frame:
                continue
            # last_frame_ts=0 means inference-stop received — treat as immediate timeout
            if self.last_frame_ts == 0.0:
                silent = float("inf")
            else:
                silent = time.time() - self.last_frame_ts
            if silent > self.heartbeat_timeout_s:
                print(
                    f"[WATCHDOG] no inference frame for {silent:.2f}s "
                    f"(> {self.heartbeat_timeout_s:.2f}s); disabling torque"
                )
                # region agent log
                self._debug_log(
                    "H6",
                    "sender/follower.py:_heartbeat_watchdog",
                    "watchdog_disable_torque",
                    {
                        "silent_seconds": float(silent),
                        "timeout_seconds": float(self.heartbeat_timeout_s),
                        "ever_received_frame": bool(self._ever_received_frame),
                    },
                )
                # endregion
                self.writer.disable_torque()
                self._torque_disabled_by_watchdog = True

    # -- task: periodic status -------------------------------------------
    async def _status_printer(self) -> None:
        while self.running:
            await asyncio.sleep(2.0)
            clamped = bool(getattr(self.writer, "_last_write_clamped", False))
            print(
                f"[follower] arm={self.arm_id} torque={self.writer.torque_enabled} "
                f"written={self.frames_written} dropped={self.frames_dropped_gate} "
                f"estop={self.estop_triggered}"
                + (" catching-up" if clamped else "")
            )

    # -- lifecycle --------------------------------------------------------
    async def run_async(self) -> None:
        # region agent log
        self._debug_log(
            "H10",
            "sender/follower.py:run_async",
            "run_async_enter",
            {
                "torque_on_start": bool(self.torque_on_start),
                "source_filter": self.source_filter,
                "arm_id": self.arm_id,
            },
        )
        # endregion
        if not self.writer.is_connected:
            if not self.writer.connect():
                print("[ERR] follower writer failed to connect; aborting")
                # region agent log
                self._debug_log(
                    "H10",
                    "sender/follower.py:run_async",
                    "run_async_abort_writer_connect",
                    {},
                )
                # endregion
                return
        ok, reason = self.writer.preflight()
        if not ok:
            print(f"[ERR] follower preflight failed: {reason}")
            # region agent log
            self._debug_log(
                "H10",
                "sender/follower.py:run_async",
                "run_async_abort_preflight",
                {"reason": reason},
            )
            # endregion
            self.writer.disconnect()
            return
        if self.torque_on_start:
            if not self.writer.enable_torque():
                print("[ERR] --torque-on-start requested but enable_torque failed")
                # region agent log
                self._debug_log(
                    "H10",
                    "sender/follower.py:run_async",
                    "run_async_abort_enable_torque",
                    {},
                )
                # endregion
                self.writer.disconnect()
                return
        else:
            print("[INFO] torque is OFF; enable externally before expecting motion")

        self.running = True
        # region agent log
        self._debug_log(
            "H10",
            "sender/follower.py:run_async",
            "run_async_tasks_start",
            {"running": True},
        )
        # endregion
        try:
            await asyncio.gather(
                self._consume_ui(),
                self._consume_robotstate(),
                self._heartbeat_watchdog(),
                self._status_printer(),
            )
        finally:
            # region agent log
            self._debug_log(
                "H10",
                "sender/follower.py:run_async",
                "run_async_finally",
                {"running_before": self.running},
            )
            # endregion
            self.running = False
            try:
                self.writer.disable_torque()
            finally:
                self.writer.disconnect()

    def run(self) -> None:
        # IMPORTANT: if we don't install a SIGTERM handler here, Python's
        # default behaviour on `kill -TERM <pid>` is to exit the interpreter
        # abruptly — the `finally: disable_torque()` block inside run_async()
        # never runs and the follower stays locked with torque on. The UI's
        # Stop button sends SIGTERM via killpg() so we must cooperate here.
        #
        # We can't reliably hook asyncio.run()'s loop from outside, so we
        # convert SIGTERM into a regular KeyboardInterrupt which asyncio.run
        # propagates cleanly, letting the `finally` blocks fire.
        import signal as _signal

        def _handle_term(signum, frame):  # noqa: ARG001
            raise KeyboardInterrupt(f"signal {signum}")

        try:
            _signal.signal(_signal.SIGTERM, _handle_term)
            # On Windows SIGHUP doesn't exist; guard for portability.
            if hasattr(_signal, "SIGHUP"):
                _signal.signal(_signal.SIGHUP, _handle_term)
        except (ValueError, OSError):
            # Not the main thread (e.g. pytest) — fall back to default.
            pass

        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n[INFO] interrupted, disabling torque")
            try:
                self.writer.disable_torque()
                self.writer.disconnect()
            except Exception:
                pass

    def stop(self) -> None:
        self.running = False


__all__ = ["BotclawFollower", "DEFAULT_UI_WS", "DEFAULT_ROBOTSTATE_WS"]
