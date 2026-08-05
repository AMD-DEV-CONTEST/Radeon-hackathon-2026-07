#!/usr/bin/env python3
"""determinex_notify.py — webhook notifications (Discord/Slack/Telegram/Generic).

Reads webhook URL from env DETERMINEX_NOTIFY_URL. Posts JSON.
Supports auto-detect of platform via URL pattern.

Usage:
    determinex_notify.py "Pool drained — 75/87 done, 12 scored"
    determinex_notify.py --level=critical "Pool stalled — 0 progress in 30 min"
    determinex_notify.py --tool=cheat --score=14.98 "Tool result"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request


def detect_platform(url: str) -> str:
    if "discord.com" in url or "discordapp.com" in url:
        return "discord"
    if "hooks.slack.com" in url:
        return "slack"
    if "api.telegram.org" in url:
        return "telegram"
    return "generic"


def discord_payload(
    msg: str, level: str = "info", tool: str | None = None, score: float | None = None
) -> dict:
    colors = {"info": 0x3498DB, "ok": 0x2ECC71, "warn": 0xF39C12, "critical": 0xE74C3C}
    embed = {
        "title": f"Determinex {level.upper()}",
        "description": msg,
        "color": colors.get(level, 0x95A5A6),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fields": [],
    }
    if tool:
        embed["fields"].append({"name": "tool", "value": tool, "inline": True})
    if score is not None:
        embed["fields"].append({"name": "score", "value": f"{score:.2f}%", "inline": True})
    return {"embeds": [embed]}


def slack_payload(
    msg: str, level: str = "info", tool: str | None = None, score: float | None = None
) -> dict:
    icons = {
        "info": ":information_source:",
        "ok": ":white_check_mark:",
        "warn": ":warning:",
        "critical": ":rotating_light:",
    }
    text = f"{icons.get(level, '')} *Determinex* — {msg}"
    if tool:
        text += f"  `{tool}`"
    if score is not None:
        text += f"  `{score:.2f}%`"
    return {"text": text}


def post(url: str, payload: dict) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except Exception as e:
        sys.stderr.write(f"webhook post failed: {e}\n")
        return False


# ── desktop, because a webhook only helps if you are looking at your phone ───────────────
#
# Ryan, 2026-08-03: *"those notifications should also work on desktop and all, just in case
# the user games or is multitasking while building."* A long build is exactly when you alt-tab,
# and a Discord message on a phone in another room is not a notification, it is a message you
# will read later. The desktop channel needs NO configuration -- it is the zero-barrier default,
# and the webhook is the addition for when you are away.


def desktop(msg: str, level: str = "info", title: str = "Determinex") -> bool:
    """Raise a native notification on this machine. Returns whether one was actually shown.

    Fixed argv, no shell, and the only interpolated values are our own status text -- no model
    or user payload reaches a command line. Falls back quietly per-platform; a machine with no
    notifier available returns False rather than pretending.
    """
    import shutil
    import subprocess

    body = (msg or "").strip()
    if not body:
        return False
    # One line; a balloon that scrolls is a balloon nobody reads.
    flat = " | ".join(line.strip() for line in body.splitlines() if line.strip())[:220]

    if sys.platform == "win32":
        # NotifyIcon balloon via PowerShell: present on stock Windows, no module to install.
        # Quotes are stripped from the payload so nothing can terminate the literal early.
        safe = flat.replace("'", "").replace('"', "")
        safe_title = title.replace("'", "").replace('"', "")
        icon = "Warning" if level in ("warn", "critical") else "Info"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            f"$n.BalloonTipIcon='{icon}';"
            f"$n.BalloonTipTitle='{safe_title}';"
            f"$n.BalloonTipText='{safe}';"
            "$n.Visible=$true;$n.ShowBalloonTip(10000);Start-Sleep -Seconds 6;$n.Dispose()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=30, check=False,
            )
            return True
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"desktop notification failed: {e}\n")
            return False

    if sys.platform == "darwin":
        # BOTH halves are sanitized. `title` used to be interpolated raw while only the body
        # was stripped -- a title containing a double quote would close the AppleScript string
        # literal early and whatever followed would be parsed as AppleScript. The title is
        # caller-supplied (agent name, session label), so "it is a constant" was never true.
        safe = flat.replace('"', "").replace("\\", "")
        safe_title = (title or "Determinex").replace('"', "").replace("\\", "")
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe}" with title "{safe_title}"'],
                capture_output=True, timeout=20, check=False,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-u", "critical" if level == "critical" else "normal",
                 title, flat],
                capture_output=True, timeout=20, check=False,
            )
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def send(msg: str, level: str = "info", url: str | None = None, title: str = "Determinex") -> dict:
    """Fan out to every channel that is actually available. Reports each one.

    Returns `{"desktop": bool, "webhook": bool|None}` -- `None` meaning "not configured",
    which is different from "tried and failed" and has a different remedy. A single boolean
    would collapse "you have no webhook set up" into "sending failed".
    """
    result: dict[str, bool | None] = {"desktop": desktop(msg, level, title), "webhook": None}
    target = url or os.environ.get("DETERMINEX_NOTIFY_URL")
    if target:
        platform = detect_platform(target)
        if platform == "discord":
            payload = discord_payload(msg, level)
        elif platform == "slack":
            payload = slack_payload(msg, level)
        else:
            payload = {"message": msg, "level": level}
        result["webhook"] = post(target, payload)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="+")
    ap.add_argument("--level", default="info", choices=["info", "ok", "warn", "critical"])
    ap.add_argument("--tool")
    ap.add_argument("--score", type=float)
    ap.add_argument("--url", default=os.environ.get("DETERMINEX_NOTIFY_URL"))
    args = ap.parse_args()
    msg = " ".join(args.message)

    # DESKTOP FIRST, AND WITHOUT CONFIGURATION. This used to refuse outright when no webhook
    # was set -- "no webhook URL" and exit 1 -- so on a machine with no Discord configured the
    # notifier did nothing at all, which is the machine the user is most likely sitting at.
    # The desktop channel needs no setup; the webhook is what you add for when you are away.
    if not args.url:
        shown = desktop(msg, args.level)
        if shown:
            print("notified on this desktop (no webhook configured -- set "
                  "DETERMINEX_NOTIFY_URL to also reach your phone)")
            return 0
        sys.stderr.write(
            "nowhere to send this: no desktop notifier available and no webhook URL.\n"
            "Set DETERMINEX_NOTIFY_URL to a Discord/Slack/Telegram webhook.\n"
        )
        return 1

    platform = detect_platform(args.url)
    if platform == "discord":
        payload = discord_payload(msg, args.level, args.tool, args.score)
    elif platform == "slack":
        payload = slack_payload(msg, args.level, args.tool, args.score)
    else:
        payload = {"message": msg, "level": args.level, "tool": args.tool, "score": args.score}

    ok = post(args.url, payload)
    desktop(msg, args.level)  # both, always -- you may be at the machine or away from it
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
