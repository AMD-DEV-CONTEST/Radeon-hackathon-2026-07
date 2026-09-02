"""
windows_literacy_tasks.py — Canonical Windows literacy task bank for Determinex benchmarks.

Each task is a dict with:
  id:       unique identifier
  category: path | envvar | process | registry | tools | syntax | filesystem
  prompt:   the user-facing ask
  rubric:   list of (pattern, required:bool, description) checks on the model output
             pattern is a regex; required=True means MUST match, False means MUST NOT match
  weight:   importance (1-3, higher = more critical)
"""

TASKS = [
    # ── PATH CONVENTIONS ─────────────────────────────────────────────────────
    {
        "id": "path_join_01",
        "category": "path",
        "weight": 3,
        "prompt": "Write PowerShell to build the path C:\\Users\\ryan\\Documents\\report.txt from its components.",
        "rubric": [
            (r"Join-Path", True, "Must use Join-Path"),
            (r"/usr/|/home/|~/", False, "Must NOT use Unix-style paths"),
            (r"\\\\|\\\\\\\\", False, "Must NOT hardcode double-backslash"),
        ],
    },
    {
        "id": "path_env_01",
        "category": "path",
        "weight": 3,
        "prompt": "Write PowerShell to find the user's Downloads folder path.",
        "rubric": [
            (
                r"\$env:USERPROFILE|\[Environment\]::GetFolderPath|Known\w+Folders|Shell\.Application|shell:Downloads|SHGetKnownFolderPath",
                True,
                "Must use Windows env, known folders API, or Shell COM",
            ),
            (r"~/Downloads|/home/", False, "Must NOT use Unix home path"),
            (r"Downloads", True, "Must reference Downloads folder"),
        ],
    },
    {
        "id": "path_temp_01",
        "category": "path",
        "weight": 2,
        "prompt": "Write PowerShell to create a temp file and write 'hello' to it.",
        "rubric": [
            (
                r"\$env:TEMP|\$env:TMP|\[System\.IO\.Path\]::GetTempPath|\[System\.IO\.Path\]::GetTempFileName",
                True,
                "Must use Windows temp dir",
            ),
            (r"/tmp/", False, "Must NOT use /tmp/"),
            (
                r"New-TemporaryFile|New-Item.*Temp|\[System\.IO\.Path\]::GetTemp|\[System\.IO\.Path\]::GetRandom|Out-File|Set-Content|WriteAllText",
                True,
                "Must write to temp file",
            ),
        ],
    },
    {
        "id": "path_appdata_01",
        "category": "path",
        "weight": 3,
        "prompt": "Write PowerShell to store application config in the user's AppData\\Roaming folder.",
        "rubric": [
            (
                r"\$env:APPDATA|\[Environment\]::GetFolderPath.*ApplicationData",
                True,
                "Must use $env:APPDATA",
            ),
            (r"~/\.config|/home/.*\.config", False, "Must NOT use Linux config path"),
        ],
    },
    # ── ENVIRONMENT VARIABLES ────────────────────────────────────────────────
    {
        "id": "envvar_set_01",
        "category": "envvar",
        "weight": 3,
        "prompt": "Write PowerShell to set an environment variable MY_API_KEY to 'abc123' for the current session.",
        "rubric": [
            (r"\$env:MY_API_KEY\s*=", True, "Must use $env: prefix"),
            (
                r"export MY_API_KEY|setenv|os\.environ",
                False,
                "Must NOT use bash export or Python syntax",
            ),
            (
                r"\[Environment\]::SetEnvironmentVariable",
                False,
                "Not required for session scope but acceptable",
            ),
        ],
    },
    {
        "id": "envvar_read_01",
        "category": "envvar",
        "weight": 3,
        "prompt": "Write PowerShell to read the PATH environment variable and split it into individual entries.",
        "rubric": [
            (r"\$env:PATH", True, "Must use $env:PATH"),
            (
                r"-split\s*['\"];\s*['\"]|\$env:PATH.*-split|Split.*\$env:PATH",
                True,
                "Must split on semicolon",
            ),
            (r"-split\s*['\"]:", False, "Must NOT split on colon (Linux PATH separator)"),
        ],
    },
    {
        "id": "envvar_persist_01",
        "category": "envvar",
        "weight": 2,
        "prompt": "Write PowerShell to permanently set an environment variable DETERMINEX_HOME for the current user.",
        "rubric": [
            (
                r"\[(?:System\.)?Environment\]::SetEnvironmentVariable.*(?:User|Machine)|SetEnvironmentVariable.*(?:User|Machine)",
                True,
                "Must use SetEnvironmentVariable with scope",
            ),
            (r"export|\.bashrc|\.profile|\.zshrc", False, "Must NOT reference bash profile files"),
        ],
    },
    # ── PROCESS MANAGEMENT ───────────────────────────────────────────────────
    {
        "id": "process_list_01",
        "category": "process",
        "weight": 2,
        "prompt": "Write PowerShell to list all running processes and sort by CPU usage.",
        "rubric": [
            (r"Get-Process", True, "Must use Get-Process"),
            (r"ps aux|top|htop", False, "Must NOT use Unix process tools"),
            (r"Sort-Object|sort\s+CPU", True, "Must sort"),
        ],
    },
    {
        "id": "process_kill_01",
        "category": "process",
        "weight": 2,
        "prompt": "Write PowerShell to stop a process named 'notepad' if it is running.",
        "rubric": [
            (r"Stop-Process|Get-Process.*Stop", True, "Must use Stop-Process"),
            (r"kill\s+-9|pkill|killall", False, "Must NOT use Unix kill"),
            (
                r"-ErrorAction\s+SilentlyContinue|-ErrorAction\s+Ignore|try|if.*Get-Process",
                True,
                "Must handle case where process not running",
            ),
        ],
    },
    {
        "id": "process_start_01",
        "category": "process",
        "weight": 2,
        "prompt": "Write PowerShell to run notepad.exe and wait for it to close before continuing.",
        "rubric": [
            (
                r"Start-Process.*-Wait|Start-Process.*Wait|\.WaitForExit",
                True,
                "Must wait for process",
            ),
            (r"subprocess\.run|os\.system|exec\s+", False, "Must NOT use Python/bash subprocess"),
        ],
    },
    # ── REGISTRY ─────────────────────────────────────────────────────────────
    {
        "id": "registry_read_01",
        "category": "registry",
        "weight": 3,
        "prompt": "Write PowerShell to read the Windows version from the registry at HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion.",
        "rubric": [
            (r"Get-ItemProperty|Get-Item.*HKLM:", True, "Must use PowerShell registry provider"),
            (
                r"HKLM:\\\\SOFTWARE\\\\Microsoft\\\\Windows NT\\\\CurrentVersion|HKLM:.*CurrentVersion",
                True,
                "Must reference correct key",
            ),
            (r"/etc/os-release|lsb_release|uname", False, "Must NOT use Linux version commands"),
        ],
    },
    {
        "id": "registry_write_01",
        "category": "registry",
        "weight": 3,
        "prompt": "Write PowerShell to create a registry value 'DeterminexVersion' set to '1.0' under HKCU:\\SOFTWARE\\Determinex.",
        "rubric": [
            (
                r"New-Item.*HKCU:|Set-ItemProperty.*HKCU:|New-ItemProperty.*HKCU:",
                True,
                "Must use registry provider with HKCU",
            ),
            (
                r"regedit|reg\s+add",
                False,
                "Must NOT use legacy reg.exe (acceptable but PowerShell preferred)",
            ),
        ],
    },
    # ── PACKAGE MANAGEMENT / TOOLS ───────────────────────────────────────────
    {
        "id": "tools_install_01",
        "category": "tools",
        "weight": 3,
        "prompt": "Write a command to install the 'git' package on Windows.",
        "rubric": [
            (
                r"winget\s+install|choco\s+install|scoop\s+install",
                True,
                "Must use Windows package manager",
            ),
            (
                r"apt(?:-get)?\s+install|yum\s+install|brew\s+install|dnf\s+install",
                False,
                "Must NOT use Linux/Mac package managers",
            ),
        ],
    },
    {
        "id": "tools_service_01",
        "category": "tools",
        "weight": 2,
        "prompt": "Write PowerShell to start the Windows Update service and set it to start automatically.",
        "rubric": [
            (r"Start-Service|Set-Service", True, "Must use PowerShell service cmdlets"),
            (
                r"systemctl|service\s+\w+\s+start|/etc/init.d",
                False,
                "Must NOT use Linux service management",
            ),
            (r"-StartupType\s+Automatic|StartupType.*Auto", True, "Must set startup type"),
        ],
    },
    {
        "id": "tools_firewall_01",
        "category": "tools",
        "weight": 2,
        "prompt": "Write PowerShell to open port 8080 in the Windows Firewall for inbound TCP connections.",
        "rubric": [
            (r"New-NetFirewallRule|netsh\s+advfirewall", True, "Must use Windows firewall tool"),
            (r"iptables|ufw\s+allow|firewall-cmd", False, "Must NOT use Linux firewall tools"),
            (r"TCP|Inbound|8080", True, "Must specify TCP, inbound, port 8080"),
        ],
    },
    # ── SHELL SYNTAX ─────────────────────────────────────────────────────────
    {
        "id": "syntax_loop_01",
        "category": "syntax",
        "weight": 3,
        "prompt": "Write PowerShell to iterate over all .log files in C:\\Logs and print each filename.",
        "rubric": [
            (r"Get-ChildItem|Get-Item|ls\b", True, "Must use Get-ChildItem or alias"),
            (r"foreach\s*\(|ForEach-Object|\| foreach", True, "Must use PowerShell foreach"),
            (r"for\s+f\s+in|find\s+\.", False, "Must NOT use bash for loop or find"),
            (r"\\Logs|C:\\Logs|Logs", True, "Must reference C:\\Logs path"),
        ],
    },
    {
        "id": "syntax_error_handling_01",
        "category": "syntax",
        "weight": 2,
        "prompt": "Write PowerShell to read a file and handle the case where it doesn't exist.",
        "rubric": [
            (
                r"Get-Content|Test-Path|try\s*\{|catch\s*\{",
                True,
                "Must use PowerShell file read with error handling",
            ),
            (
                r"open\(|with\s+open|cat\s+\w+\s+\|\|",
                False,
                "Must NOT use Python open() or bash cat with ||",
            ),
            (r"-ErrorAction|-ErrorVariable|try|Test-Path", True, "Must handle missing file"),
        ],
    },
    {
        "id": "syntax_string_01",
        "category": "syntax",
        "weight": 2,
        "prompt": "Write PowerShell to replace all occurrences of 'foo' with 'bar' in a string variable $text.",
        "rubric": [
            (
                r"\$text\s*-replace\s*|\.Replace\s*\(",
                True,
                "Must use PowerShell -replace or .Replace()",
            ),
            (r"sed\s+-i|\.sub\s*\(|re\.sub", False, "Must NOT use sed or Python regex sub"),
        ],
    },
    # ── FILESYSTEM ───────────────────────────────────────────────────────────
    {
        "id": "fs_permissions_01",
        "category": "filesystem",
        "weight": 3,
        "prompt": "Write PowerShell to give user 'DOMAIN\\john' full control permissions on the folder C:\\Data.",
        "rubric": [
            (
                r"icacls|Set-Acl|Get-Acl|cacls|New-Object\s+System\.Security",
                True,
                "Must use Windows ACL tools",
            ),
            (r"chmod|chown|setfacl", False, "Must NOT use Unix permission tools"),
            (r"FullControl|F\b", True, "Must specify full control"),
        ],
    },
    {
        "id": "fs_symlink_01",
        "category": "filesystem",
        "weight": 2,
        "prompt": "Write PowerShell to create a symbolic link from C:\\link to C:\\target.",
        "rubric": [
            (r"New-Item.*SymbolicLink|mklink\b", True, "Must use New-Item SymbolicLink or mklink"),
            (r"ln\s+-s\s*", False, "Must NOT use Unix ln -s"),
        ],
    },
    {
        "id": "fs_watch_01",
        "category": "filesystem",
        "weight": 1,
        "prompt": "Write PowerShell to watch a directory C:\\Logs for new files and print the filename when one appears.",
        "rubric": [
            (
                r"FileSystemWatcher|System\.IO\.FileSystemWatcher",
                True,
                "Must use .NET FileSystemWatcher",
            ),
            (r"inotifywait|fswatch\b", False, "Must NOT use Linux file watchers"),
        ],
    },
]

# Quick lookup
TASK_BY_ID = {t["id"]: t for t in TASKS}
CATEGORIES = list({t["category"] for t in TASKS})

if __name__ == "__main__":
    print(f"Task bank: {len(TASKS)} tasks across {len(CATEGORIES)} categories")
    for cat in sorted(CATEGORIES):
        n = sum(1 for t in TASKS if t["category"] == cat)
        print(f"  {cat}: {n}")
