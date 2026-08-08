"""Verify run-mem.md is complete and intact."""
import os
import re

path = r"c:\Users\brigh\Desktop\trying_new\Screen-AI\run-mem.md"
size = os.path.getsize(path)

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

turns = re.findall(r"^## Turn (\d+)", content, re.MULTILINE)
lines = content.count("\n")

print(f"File: {path}")
print(f"Size: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
print(f"Lines: {lines:,}")
print(f"Chars: {len(content):,}")
print(f"Turns: {len(turns)} (Turn {turns[0]} -> Turn {turns[-1]})")
print(f"Has header: {content.startswith('# Run Memory')}")
print(f"Has footer: {'extract_transcript.py' in content[-5000:]}")
print(f"Has session metadata: {'## Session Metadata' in content[:5000]}")
print(f"Has Turn 1: {'## Turn 1' in content}")
print(f"Has Turn 71: {'## Turn 71' in content}")
print(f"Has User sections: {content.count('### User')}")
print(f"Has Assistant sections: {content.count('### Assistant')}")
print(f"Has Tool Calls sections: {content.count('### Tool Calls')}")
