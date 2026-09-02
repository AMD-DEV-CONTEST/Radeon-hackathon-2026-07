"""Foundry chat CLI: the multi-turn interface to the agent.

Usage:
    python chat.py --config configs/local_4060.toml
    python chat.py --config ... --script "build me a triage model||yes, go ahead"

--script feeds turns non-interactively (validation harness); each turn is
separated by '||'.
"""

import argparse
import json
import sys

# Windows console defaults to cp1252; the agent emits unicode freely.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from foundry import config as config_mod
from foundry.agent import Agent
from foundry.teacher import TeacherClient, start_server, stop_server
from foundry.tools import ToolBox

DIM = "\x1b[2m"
BOLD = "\x1b[1m"
CYAN = "\x1b[36m"
YELLOW = "\x1b[33m"
RESET = "\x1b[0m"


class TeacherCtl:
    """Start/stop control for the shared llama-server, handed to tools."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None

    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        t = self.cfg["teacher"]
        port = int(t["base_url"].rsplit(":", 1)[1].split("/")[0])
        print(f"{DIM}[teacher server starting...]{RESET}", flush=True)
        self.proc = start_server(t["server_exe"], t["gguf"], port,
                                 t["n_gpu_layers"], t["parallel"],
                                 t["ctx_per_slot"])

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            print(f"{DIM}[teacher server stopping to free GPU...]{RESET}",
                  flush=True)
            stop_server(self.proc)
        self.proc = None


def render(events):
    for kind, data in events:
        if kind == "text":
            print(f"\n{BOLD}Foundry:{RESET} {data}", flush=True)
        elif kind == "tool_call":
            args = json.dumps(data["args"]) if data["args"] else ""
            if len(args) > 160:
                args = args[:160] + "..."
            print(f"{CYAN}  -> {data['name']}({args}){RESET}", flush=True)
        elif kind == "tool_result":
            body = json.dumps(data["result"], default=str)
            if len(body) > 400:
                body = body[:400] + "..."
            print(f"{YELLOW}  <- {body}{RESET}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/local_4060.toml")
    ap.add_argument("--script", default=None)
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    ctl = TeacherCtl(cfg)
    client = TeacherClient(cfg["teacher"]["base_url"])
    external_server = client.healthy()
    if not external_server:
        ctl.start()

    toolbox = ToolBox(cfg, args.config, ctl)
    agent = Agent(cfg, toolbox)
    print(f"{BOLD}Foundry{RESET} — small-model factory. "
          f"Describe the model you need. (exit/quit to leave)")

    try:
        if args.script:
            for line in args.script.split("||"):
                print(f"\n{BOLD}You:{RESET} {line}")
                render(agent.turn(line))
        else:
            while True:
                try:
                    line = input(f"\n{BOLD}You:{RESET} ").strip()
                except EOFError:
                    break
                if line.lower() in ("exit", "quit"):
                    break
                if not line:
                    continue
                render(agent.turn(line))
    finally:
        if not external_server:
            ctl.stop()


if __name__ == "__main__":
    main()
