"""Extract the full conversation transcript from the JSONL log into a readable markdown file."""
import json
import sys
from pathlib import Path

TRANSCRIPT_PATH = r"c:\Users\brigh\AppData\Roaming\Code\User\workspaceStorage\59ce210a8c59bff81c580380ee665748\GitHub.copilot-chat\transcripts\f1bfb05c-9e77-48b2-9311-100ad573b379.jsonl"
OUTPUT_PATH = r"c:\Users\brigh\Desktop\trying_new\Screen-AI\run-mem.md"


def load_events(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def build_turns(events):
    """Group events into turns: each user.message starts a new turn."""
    turns = []
    current = None
    for e in events:
        t = e.get("type", "")
        if t == "user.message":
            if current is not None:
                turns.append(current)
            current = {"user": e["data"].get("content", ""), "assistant": [], "tools": []}
        elif t == "assistant.message":
            if current is None:
                current = {"user": "", "assistant": [], "tools": []}
            msg = e["data"]
            content = msg.get("content", "")
            if content:
                current["assistant"].append(content)
            for tr in msg.get("toolRequests", []) or []:
                current["tools"].append(
                    {"name": tr.get("name"), "args": tr.get("arguments", "")}
                )
        elif t == "tool.execution_complete":
            if current is not None:
                current["tools"].append(
                    {"result": "completed", "id": e["data"].get("toolCallId", "")}
                )
    if current is not None:
        turns.append(current)
    return turns


def render_markdown(turns):
    out = []
    out.append("# Run Memory — Screen-AI Session (Full Transcript)\n")
    out.append(
        "> Full transcript of this chat run, copied verbatim from the conversation between user and assistant.\n"
    )
    out.append(
        "> Includes all messages, tool calls, terminal outputs, and context.\n"
    )
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Session Metadata")
    out.append("")
    out.append("- **Date**: 2026-07-30")
    out.append("- **Workspace**: `c:\\Users\\brigh\\Desktop\\trying_new\\Screen-AI`")
    out.append("- **Project**: Screen-AI — local/offline PC operator AI with mobile remote control")
    out.append("- **Hackathon**: Radeon-hackathon-2026-07, Track 2: Agentic AI")
    out.append(f"- **Total turns**: {len(turns)}")
    out.append("")
    out.append("---")
    out.append("")

    for i, turn in enumerate(turns, 1):
        out.append(f"## Turn {i}")
        out.append("")
        if turn["user"]:
            out.append("### User")
            out.append("")
            out.append("```")
            out.append(turn["user"])
            out.append("```")
            out.append("")
        for j, msg in enumerate(turn["assistant"], 1):
            out.append(f"### Assistant (message {j})")
            out.append("")
            out.append(msg)
            out.append("")
        if turn["tools"]:
            out.append("### Tool Calls")
            out.append("")
            for k, tool in enumerate(turn["tools"], 1):
                if "name" in tool:
                    out.append(f"**Tool {k}**: `{tool['name']}`")
                    out.append("")
                    out.append("```json")
                    out.append(tool["args"])
                    out.append("```")
                    out.append("")
                else:
                    out.append(f"**Tool {k}**: completed (id={tool.get('id', '')})")
                    out.append("")
        out.append("---")
        out.append("")

    return "\n".join(out)


def main():
    events = load_events(TRANSCRIPT_PATH)
    print(f"Loaded {len(events)} events", file=sys.stderr)
    turns = build_turns(events)
    print(f"Built {len(turns)} turns", file=sys.stderr)
    md = render_markdown(turns)
    Path(OUTPUT_PATH).write_text(md, encoding="utf-8")
    print(f"Wrote {len(md)} chars to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
