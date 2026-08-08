"""Test batch of commands via curl."""
import urllib.request
import json

cmds = [
    "close all apps in desktop",
    "open chrome",
    "search best air coolers",
    "check my pc status",
    "list files in downloads",
    "open youtube",
    "browser session",
    "keep awake for 30 minutes",
    "lock my pc",
    "restart my pc",
    "shutdown my pc",
    "take a screenshot",
    "ping google.com",
    "compose email to alice@example.com",
    "remember that my favorite color is blue",
    "research AMD ROCm",
    "git clone repo",
    "docker build",
    "read pdf",
    "open excel",
    "close notepad",
    "minimize window",
    "maximize window",
    "arrange windows",
    "install vscode",
    "uninstall chrome",
    "update spotify",
    "restart discord",
    "run powershell command",
    "run cmd",
    "build project",
    "run tests",
    "run dev server",
    "read text on screen",
    "detect buttons",
    "copy to clipboard",
    "paste from clipboard",
    "read clipboard",
    "send email",
    "search email",
    "download file",
    "upload file",
    "check wifi",
    "record screen",
    "open camera",
    "create pdf",
    "read word document",
    "read excel spreadsheet",
    "read csv file",
    "forget that",
    "create task",
    "run task",
    "cancel task",
    "summarize article",
    "what is my pc status",
    "show me disk usage",
    "how much memory am i using",
    "delete files in downloads",
]

for cmd in cmds:
    req = urllib.request.Request(
        "http://localhost:8000/command/preview",
        data=json.dumps({"text": cmd}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
            intent = d.get("intent", "?")
            print(f"{cmd} -> {intent}")
    except Exception as e:
        print(f"{cmd} -> ERROR: {e}")
