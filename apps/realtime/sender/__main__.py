"""CLI entry for `python -m sender`.

Leader mode:   read Feetech + broadcast to /ws/teleop
Follower mode: subscribe /ws/ui + drive Feetech Goal_Position

Calibration: device_id points into lerobot's standard cache
    ~/.cache/huggingface/lerobot/calibration/{robots|teleoperators}/so101_{...}/{device_id}.json
If --device-id is omitted we auto-discover when exactly one file exists,
otherwise bail with a clear message telling the user to calibrate first.

Examples:
    python -m sender --mode leader   --com_port /dev/ttyACM1 --device-id ethan_leader
    python -m sender --mode follower --com_port /dev/ttyACM0 --device-id ethan_follower \
                     --torque-on-start --source-filter leader_arm
"""
from __future__ import annotations

import argparse
import os
import sys


def _resolve_auto_port(mode: str) -> str:
    """Auto-scan serial ports and pick one based on mode + env hints."""
    from .port_scan import scan_feetech_ports, auto_assign_roles

    print("[INFO] --com_port auto: scanning for Feetech motors...")
    results = scan_feetech_ports()
    if not results:
        print("[ERR] no Feetech motors found; falling back to /dev/ttyACM0")
        return "/dev/ttyACM0"

    assignments = auto_assign_roles(results)
    for port, role in assignments.items():
        if role == mode:
            print(f"[OK] auto-scan: {mode} → {port} (motors: {results[port].motor_ids})")
            return port

    first = next(iter(assignments))
    print(f"[WARN] auto-scan: no port matched role '{mode}'; using {first}")
    return first


def _run_leader(args: argparse.Namespace) -> None:
    from .sender import BotclawSender

    print("=" * 60)
    print(f"BotverseX Sender — LEADER mode  [runtime={args.runtime}]")
    print("=" * 60)
    print(f"COM port:    {args.com_port}")
    print(f"device_id:   {args.device_id or '(auto)'}")
    print(f"arm_id:      {args.arm_id}")
    print(f"api:         {args.api_url}")
    print(f"send_hz:     {args.send_hz}")
    print(f"dry_run:     {args.dry_run}")
    print("=" * 60)

    sender = BotclawSender(
        com_port=args.com_port,
        device_id=args.device_id,
        robot_id=args.robot_id,
        arm_id=args.arm_id,
        api_url=args.api_url,
        send_hz=args.send_hz,
        dry_run=args.dry_run,
        read_telemetry=not args.no_telemetry,
    )
    try:
        sender.run()
    except KeyboardInterrupt:
        sender.stop()


def _run_follower(args: argparse.Namespace) -> None:
    from runtimes import get_runtime_class

    from .follower import BotclawFollower

    runtime_cls = get_runtime_class(args.runtime)

    if not args.com_port and not args.dry_run:
        print(
            "[ERR] follower mode needs --com_port (run `lerobot-find-port` to discover). "
            "Use --dry_run to use the mock writer for smoke tests."
        )
        sys.exit(2)

    print("=" * 60)
    print(f"BotverseX Sender — FOLLOWER mode  [runtime={args.runtime}]")
    print("=" * 60)
    print(f"COM port:        {args.com_port or '(dry, no port)'}")
    print(f"device_id:       {args.device_id or '(auto)'}")
    print(f"arm_id:          {args.arm_id}")
    print(f"ui_url:          {args.ui_url}")
    print(f"robotstate_url:  {args.robotstate_url}")
    print(f"max_delta_rad:   {args.max_delta}")
    print(f"heartbeat_s:     {args.heartbeat_timeout}")
    print(f"torque_on_start: {args.torque_on_start}")
    print(f"warmup_seconds:  {args.warmup_seconds}")
    print(f"dry_run:         {args.dry_run}")
    print("=" * 60)

    if args.dry_run:
        writer = runtime_cls.create_mock_writer(name="follower_dry")
    else:
        writer = runtime_cls.create_writer(
            port=args.com_port,
            device_id=args.device_id,
            warmup_seconds=args.warmup_seconds,
        )

    follower = BotclawFollower(
        writer=writer,
        arm_id=args.arm_id,
        ui_url=args.ui_url,
        robotstate_url=args.robotstate_url,
        max_delta_rad=args.max_delta,
        heartbeat_timeout_s=args.heartbeat_timeout,
        torque_on_start=args.torque_on_start,
        source_filter=args.source_filter,
    )
    try:
        follower.run()
    except KeyboardInterrupt:
        follower.stop()


def main() -> None:
    from runtimes import list_runtimes

    available_runtimes = list_runtimes()

    parser = argparse.ArgumentParser(
        description="BotverseX Sender — leader / follower (lerobot-calibrated)"
    )
    parser.add_argument(
        "--runtime",
        default=os.environ.get("BOTVERSEX_RUNTIME", "so101"),
        choices=available_runtimes,
        help=f"hardware runtime backend (default: so101). Available: {available_runtimes}",
    )
    parser.add_argument(
        "--mode",
        choices=("leader", "follower"),
        default="leader",
        help="leader = read arm -> /ws/teleop (default); follower = /ws/ui -> drive arm",
    )

    # Shared --------------------------------------------------------------
    parser.add_argument("--com_port", default=os.environ.get("BOTVERSEX_COM_PORT", "/dev/ttyACM0"),
                        help="serial port (or 'auto' for auto-scan)")
    parser.add_argument("--arm_id", default=os.environ.get("BOTVERSEX_ARM_ID", "arm_0"),
                        help="arm_id placeholder")
    parser.add_argument("--dry_run", action="store_true",
                        help="no hardware: leader emits synthetic motion, follower uses mock writer")
    parser.add_argument(
        "--device-id", dest="device_id",
        default=None,
        help=(
            "lerobot calibration device_id (filename under "
            "~/.cache/huggingface/lerobot/calibration/{robots|teleoperators}/so101_*). "
            "Omit to auto-discover if exactly one calibration is present."
        ),
    )

    # Leader-only ---------------------------------------------------------
    parser.add_argument("--robot_id", default=None, help="BotClaw robot_id; env BOTVERSEX_ROBOT_ID")
    parser.add_argument("--api_url", default="ws://localhost:8002/ws/teleop",
                        help="leader: realtime /ws/teleop URL")
    parser.add_argument(
        "--send_hz", type=float, default=60.0,
        help="leader: send rate in Hz (lerobot_teleoperate default fps=60)",
    )
    parser.add_argument("--no_telemetry", action="store_true",
                        help="leader: skip temperature/current reads")

    # Follower-only -------------------------------------------------------
    parser.add_argument("--ui_url", default="ws://localhost:8002/ws/ui",
                        help="follower: realtime /ws/ui URL to subscribe")
    parser.add_argument("--robotstate_url", default="ws://localhost:8002/ws/robotstate",
                        help="follower: realtime /ws/robotstate URL for estop watchdog")
    parser.add_argument("--max_delta", type=float, default=0.18,
                        help=(
                            "follower: SafetyGate max_delta_rad per tick. "
                            "Default 0.18 (~10.3°/tick, ~661°/s at 64Hz) matches "
                            "the value safety.py documents as stable for real-arm "
                            "teleop. Lower it (e.g. 0.05) only for inference runs "
                            "where model output may spike."
                        ))
    parser.add_argument("--heartbeat_timeout", type=float, default=1.0,
                        help="follower: seconds without inference frame -> disable_torque (default 1.0)")
    parser.add_argument("--torque-on-start", dest="torque_on_start", action="store_true",
                        help="follower: enable torque immediately after preflight")
    parser.add_argument("--warmup-seconds", dest="warmup_seconds",
                        type=float, default=0.4,
                        help=(
                            "follower: short lerp after torque-on (default 0.4s). "
                            "Native lerobot has no ramp when max_relative_target=None; "
                            "we keep a brief blend only for mis-aligned starts."
                        ))
    parser.add_argument("--source-filter", dest="source_filter", default="inference",
                        help=(
                            "follower: only mirror /ws/ui frames whose meta.source matches. "
                            "Default 'inference' = only follow model output. "
                            "Use 'leader_arm' for direct leader->follower teleop."
                        ))

    args = parser.parse_args()

    if args.com_port and args.com_port.lower() == "auto" and not args.dry_run:
        args.com_port = _resolve_auto_port(args.mode)

    if args.mode == "leader":
        _run_leader(args)
    elif args.mode == "follower":
        _run_follower(args)
    else:  # pragma: no cover
        parser.error(f"unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
