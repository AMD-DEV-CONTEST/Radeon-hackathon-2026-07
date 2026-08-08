"""Planner - converts user text into executable plans.

This planner is the brain of the Desktop AI Agent. It has full awareness of:

- 268 pipeline graphs across 13+ domains (browser, file, window, app, terminal,
  dev, ocr, vision, clipboard, email, network, media, doc)
- 154 phase utilities (intent, context, observation, verification, recovery,
  memory, skill, state, workflow, provider, agent runtime)
- 14 operations in the operations registry
- The memory engine, router, and every backend file
- Fuzzy matching, synonym expansion, and learned memory

It can plan any desktop AI agent task by composing the right pipeline graphs
and operations into a coherent execution plan.
"""

from __future__ import annotations

import re
import json
import os
import time
import difflib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# ===========================================================================
# SECTION 1: SYNONYMS - expand user phrasing before pattern matching
# ===========================================================================
SYNONYMS: Dict[str, List[str]] = {
    "close": ["close", "quit", "exit", "shut down", "shutdown", "kill",
              "terminate", "end", "dismiss", "stop", "wrap up", "finish",
              "get rid of", "remove"],
    "open": ["open", "launch", "start", "run", "fire up", "boot",
             "bring up", "show", "spin up", "kick off", "go to",
             "navigate to", "visit", "take me to"],
    "search": ["search", "google", "find", "look up", "lookup", "query",
               "research", "investigate", "explore"],
    "delete": ["delete", "remove", "erase", "wipe", "trash", "get rid of",
               "clear", "drop", "purge", "destroy"],
    "list": ["list", "show", "display", "enumerate", "view", "see"],
    "check": ["check", "inspect", "report", "status", "diagnose", "scan",
              "analyze", "examine"],
    "app": ["app", "application", "program", "software", "window",
            "process", "tool", "service"],
    "all": ["all", "every", "each", "any", "every single", "everything"],
    "desktop": ["desktop", "taskbar", "screen", "foreground", "running",
                "open windows", "open apps", "open applications",
                "currently open", "active"],
    "browser": ["browser", "chrome", "edge", "firefox", "web", "internet"],
    "file": ["file", "document", "doc", "folder", "directory"],
    "create": ["create", "make", "new", "generate", "build", "produce"],
    "send": ["send", "transmit", "dispatch", "deliver", "submit"],
    "receive": ["receive", "get", "fetch", "retrieve", "download"],
    "move": ["move", "transfer", "relocate", "shift"],
    "copy": ["copy", "duplicate", "clone", "replicate"],
    "rename": ["rename", "relabel", "change name"],
    "compress": ["compress", "zip", "archive", "pack"],
    "extract": ["extract", "unzip", "unpack", "decompress"],
    "click": ["click", "press", "tap", "select", "hit", "choose"],
    "type": ["type", "enter", "input", "write", "fill"],
    "screenshot": ["screenshot", "capture", "snap", "screen capture",
                   "take picture"],
    "record": ["record", "capture video", "screen record"],
    "install": ["install", "setup", "set up", "deploy"],
    "uninstall": ["uninstall", "remove", "delete"],
    "update": ["update", "upgrade", "patch", "refresh"],
    "restart": ["restart", "reboot", "reset", "reload"],
    "shutdown": ["shutdown", "shut down", "power off", "turn off"],
    "lock": ["lock", "secure", "protect"],
    "unlock": ["unlock", "release", "free"],
    "login": ["login", "sign in", "log in", "authenticate"],
    "logout": ["logout", "sign out", "log out"],
    "upload": ["upload", "push", "send up"],
    "download": ["download", "pull", "fetch", "grab"],
    "backup": ["backup", "save", "snapshot", "copy"],
    "restore": ["restore", "recover", "bring back"],
    "minimize": ["minimize", "minify", "shrink"],
    "maximize": ["maximize", "enlarge", "expand", "fullscreen"],
    "focus": ["focus", "activate", "bring to front", "select"],
    "switch": ["switch", "change", "toggle", "flip"],
    "verify": ["verify", "check", "confirm", "validate", "test"],
    "retry": ["retry", "try again", "redo", "repeat"],
    "cancel": ["cancel", "abort", "stop", "revoke"],
    "approve": ["approve", "accept", "allow", "grant", "permit"],
    "reject": ["reject", "deny", "refuse", "block", "disallow"],
    "remember": ["remember", "save", "store", "note", "record"],
    "forget": ["forget", "delete", "erase", "clear"],
    "summarize": ["summarize", "condense", "shorten", "tldr"],
    "help": ["help", "assist", "support", "aid"],
    "enable": ["enable", "activate", "turn on", "switch on"],
    "disable": ["disable", "deactivate", "turn off", "switch off"],
    "show": ["show", "display", "reveal", "expose", "unveil"],
    "hide": ["hide", "conceal", "mask", "cover"],
    "find": ["find", "locate", "search", "discover", "spot"],
    "replace": ["replace", "substitute", "swap", "exchange"],
    "sort": ["sort", "order", "arrange", "rank"],
    "filter": ["filter", "sieve", "strain", "narrow"],
    "count": ["count", "tally", "enumerate", "number"],
    "validate": ["validate", "verify", "confirm", "authenticate"],
    "log": ["log", "record", "trace", "track"],
    "debug": ["debug", "troubleshoot", "diagnose", "fix"],
    "optimize": ["optimize", "improve", "enhance", "tune"],
    "secure": ["secure", "protect", "harden", "lock down"],
    "encrypt": ["encrypt", "encode", "scramble", "cipher"],
    "decrypt": ["decrypt", "decode", "descramble", "decipher"],
    "clean": ["clean", "tidy", "purge", "scrub"],
    "organize": ["organize", "arrange", "structure", "order"],
    "plan": ["plan", "schedule", "design", "draft"],
    "execute": ["execute", "run", "perform", "carry out"],
    "test": ["test", "try", "experiment", "validate"],
    "deploy": ["deploy", "release", "publish", "ship"],
    "build": ["build", "compile", "construct", "assemble"],
    "compile": ["compile", "build", "assemble"],
    "run": ["run", "execute", "start", "launch"],
    "stop": ["stop", "halt", "kill", "terminate"],
    "pause": ["pause", "suspend", "freeze"],
    "resume": ["resume", "continue", "proceed"],
    "skip": ["skip", "jump", "bypass"],
    "undo": ["undo", "reverse", "revert"],
    "redo": ["redo", "repeat", "do again"],
    "save": ["save", "store", "persist", "write"],
    "load": ["load", "read", "open", "fetch"],
    "import": ["import", "bring in", "load"],
    "export": ["export", "send out", "output"],
    "scan": ["scan", "examine", "inspect", "check"],
    "detect": ["detect", "find", "discover", "identify"],
    "recognize": ["recognize", "identify", "detect"],
    "classify": ["classify", "categorize", "sort", "label"],
    "tag": ["tag", "label", "mark"],
    "select": ["select", "choose", "pick"],
    "connect": ["connect", "join", "link", "attach"],
    "disconnect": ["disconnect", "detach", "unlink", "separate"],
    "insert": ["insert", "add", "put in"],
    "remove": ["remove", "take out", "extract", "delete"],
    "push": ["push", "send", "upload"],
    "pull": ["pull", "fetch", "download", "get"],
    "ping": ["ping", "check", "test"],
    "trace": ["trace", "track", "follow"],
    "route": ["route", "direct", "guide"],
    "forward": ["forward", "pass on", "relay"],
    "back": ["back", "reverse", "return"],
    "next": ["next", "forward", "skip ahead"],
    "previous": ["previous", "back", "prior"],
    "first": ["first", "initial", "primary"],
    "last": ["last", "final", "ultimate"],
    "top": ["top", "peak", "highest"],
    "bottom": ["bottom", "lowest", "base"],
    "left": ["left", "west"],
    "right": ["right", "east"],
    "up": ["up", "north", "above"],
    "down": ["down", "south", "below"],
    "center": ["center", "middle", "centered"],
    "now": ["now", "immediately", "instantly"],
    "later": ["later", "afterwards", "subsequently"],
    "soon": ["soon", "shortly", "quickly"],
    "always": ["always", "forever", "constantly"],
    "never": ["never", "not ever"],
    "today": ["today", "this day"],
    "tomorrow": ["tomorrow", "next day"],
    "yesterday": ["yesterday", "previous day"],
    "this": ["this", "current", "present"],
    "that": ["that", "specific", "particular"],
    "my": ["my", "personal", "own"],
    "your": ["your", "belonging to you"],
    "our": ["our", "shared", "common"],
    "their": ["their", "belonging to them"],
}


def _expand_synonyms(text: str) -> str:
    """Expand synonyms in the text so pattern matching is more forgiving.

    Example: "shut down chrome" -> "close chrome"
             "kill all apps"    -> "close all apps"
    """
    out = text.lower().strip()
    multiword = sorted(
        [(k, v) for v in SYNONYMS.values() for k in v if " " in k],
        key=lambda kv: -len(kv[0]),
    )
    for phrase, canonical_list in multiword:
        canonical = canonical_list[0]
        out = re.sub(r"\b" + re.escape(phrase) + r"\b", canonical, out)
    return out


# ===========================================================================
# SECTION 2: APP / SITE ALIASES
# ===========================================================================
APP_NAME_ALIASES: Dict[str, str] = {
    "chrome": "chrome", "google chrome": "chrome", "browser": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox", "opera": "opera", "opera gx": "opera-gx",
    "notepad": "notepad", "calculator": "calc", "calc": "calc",
    "explorer": "explorer", "file explorer": "explorer",
    "paint": "mspaint", "cmd": "cmd", "command prompt": "cmd",
    "powershell": "powershell", "terminal": "wt",
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "code": "code",
    "excel": "excel", "word": "winword", "powerpoint": "powerpnt",
    "outlook": "outlook", "spotify": "spotify", "discord": "discord",
    "slack": "slack", "telegram": "telegram", "whatsapp": "whatsapp",
    "steam": "steam", "epic games": "epicgameslauncher",
    "epic": "epicgameslauncher",
    "settings": "ms-settings:", "control panel": "control",
    "task manager": "taskmgr", "registry editor": "regedit",
    "device manager": "devmgmt", "disk management": "diskmgmt",
    "event viewer": "eventvwr", "services": "services.msc",
    "notepad++": "notepad++", "sublime text": "sublime_text",
    "atom": "atom", "vim": "vim", "emacs": "emacs",
    "photoshop": "photoshop", "illustrator": "illustrator",
    "premiere": "premiere", "after effects": "afterfx",
    "blender": "blender", "unity": "unity", "unreal": "ue4",
    "docker": "docker", "vmware": "vmware", "virtualbox": "virtualbox",
    "obs": "obs64", "streamlabs": "streamlabs",
    "zoom": "zoom", "teams": "teams", "skype": "skype",
    "vlc": "vlc", "media player": "wmplayer",
    "photos": "photos", "snipping tool": "snippingtool",
    "sticky notes": "stickynotes", "onenote": "onenote",
    "todo": "todo", "sticky": "stickynotes",
    "mail": "mail", "calendar": "calendar",
    "maps": "maps", "weather": "weather",
    "store": "store", "xbox": "xbox",
    "groove music": "music", "movies": "movies",
    "3d builder": "3dbuilder", "3d viewer": "3dviewer",
    "alarms": "alarms",
    "camera": "camera", "cortana": "cortana",
    "feedback hub": "feedbackhub", "get help": "gethelp",
    "mixed reality": "mixedreality", "mobile plans": "mobileplans",
    "money": "money", "news": "news",
    "office": "office",
    "people": "people", "phone": "phone",
    "projecting to this pc": "projecting",
    "security": "security", "tips": "tips",
    "voice recorder": "soundrecorder", "wallet": "wallet",
    "your phone": "yourphone",
}


# ===========================================================================
# SECTION 3: PIPELINE KNOWLEDGE BASE
# ===========================================================================
# Maps intent keywords to the pipeline graphs that can fulfill them.
# This is the planner's awareness of the 268 pipeline graphs.

PIPELINE_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "browser": {
        "keywords": ["browser", "chrome", "edge", "firefox", "web", "internet",
                     "navigate", "url", "site", "tab", "page"],
        "pipelines": {
            "launch": "browserLaunchGraph",
            "close": "browserCloseGraph",
            "restart": "browserRestartGraph",
            "detect": "browserDetectGraph",
            "attach": "browserAttachGraph",
            "open_url": "browserOpenUrlGraph",
            "back": "browserBackGraph",
            "forward": "browserForwardGraph",
            "refresh": "browserRefreshGraph",
            "home": "browserHomeGraph",
            "search_google": "browserSearchGoogleGraph",
            "search_bing": "browserSearchBingGraph",
            "search_duckduckgo": "browserSearchDuckduckgoGraph",
            "search_youtube": "browserSearchYoutubeGraph",
            "search_github": "browserSearchGithubGraph",
            "tab_new": "browserTabNewGraph",
            "tab_close": "browserTabCloseGraph",
            "tab_duplicate": "browserTabDuplicateGraph",
            "tab_switch": "browserTabSwitchGraph",
            "tab_pin": "browserTabPinGraph",
            "tab_reopen": "browserTabReopenGraph",
            "download_file": "browserDownloadFileGraph",
            "verify_download": "browserVerifyDownloadGraph",
            "cancel_download": "browserCancelDownloadGraph",
            "upload_file": "browserUploadFileGraph",
            "upload_folder": "browserUploadFolderGraph",
            "login": "browserLoginGraph",
            "logout": "browserLogoutGraph",
            "session_restore": "browserSessionRestoreGraph",
        },
    },
    "file": {
        "keywords": ["file", "document", "doc", "folder", "directory",
                     "read", "write", "delete", "move", "copy", "rename"],
        "pipelines": {
            "read": "fileReadGraph",
            "write": "fileWriteGraph",
            "append": "fileAppendGraph",
            "rename": "fileRenameGraph",
            "delete": "fileDeleteGraph",
            "restore": "fileRestoreGraph",
            "move": "fileMoveGraph",
            "copy": "fileCopyGraph",
            "compress": "fileCompressGraph",
            "extract": "fileExtractGraph",
            "archive": "fileArchiveGraph",
            "duplicate": "fileDuplicateGraph",
            "organize_folder": "folderOrganizeGraph",
            "search_files": "filesSearchGraph",
            "search_folders": "foldersSearchGraph",
            "find_duplicates": "findDuplicateFilesGraph",
            "sort_downloads": "sortDownloadsGraph",
            "backup_folder": "backupFolderGraph",
            "sync_folder": "syncFolderGraph",
            "watch_folder": "watchFolderGraph",
            "metadata": "fileMetadataGraph",
            "permissions": "filePermissionsGraph",
            "temp_files": "tempFilesGraph",
            "trash": "trashManagementGraph",
            "secure_delete": "secureDeleteGraph",
            "compare": "compareFilesGraph",
            "merge": "mergeFilesGraph",
            "split": "splitFileGraph",
            "report": "generateReportGraph",
            "hash": "fileHashGraph",
        },
    },
    "window": {
        "keywords": ["window", "focus", "switch", "resize", "minimize",
                     "maximize", "close", "move", "arrange", "always on top"],
        "pipelines": {
            "focus": "windowFocusGraph",
            "detect": "windowDetectGraph",
            "switch": "windowSwitchGraph",
            "resize": "windowResizeGraph",
            "maximize": "windowMaximizeGraph",
            "minimize": "windowMinimizeGraph",
            "restore": "windowRestoreGraph",
            "close": "windowCloseGraph",
            "move": "windowMoveGraph",
            "arrange": "windowArrangeGraph",
            "always_on_top": "windowAlwaysOnTopGraph",
            "multi_monitor": "windowMultiMonitorGraph",
            "capture": "windowCaptureGraph",
            "enumerate": "windowEnumerateGraph",
            "find_dialog": "windowFindDialogGraph",
            "activate_tab": "windowActivateTabGraph",
            "wait": "windowWaitGraph",
            "observe": "windowObserveGraph",
            "verify": "windowVerifyGraph",
            "screenshot": "windowScreenshotGraph",
        },
    },
    "app": {
        "keywords": ["app", "application", "program", "software", "install",
                     "uninstall", "update", "launch", "process"],
        "pipelines": {
            "open": "appOpenGraph",
            "close": "appCloseGraph",
            "restart": "appRestartGraph",
            "install": "appInstallGraph",
            "uninstall": "appUninstallGraph",
            "update": "appUpdateGraph",
            "detect_running": "appDetectRunningGraph",
            "activate": "appActivateGraph",
            "kill_process": "appKillProcessGraph",
            "background_service": "appBackgroundServiceGraph",
            "launch_arguments": "appLaunchArgumentsGraph",
            "default_apps": "appDefaultAppsGraph",
            "associate_files": "appAssociateFilesGraph",
            "health_check": "appHealthCheckGraph",
            "process_monitor": "appProcessMonitorGraph",
            "memory_usage": "appMemoryUsageGraph",
            "cpu_usage": "appCpuUsageGraph",
            "crash_recovery": "appCrashRecoveryGraph",
            "startup_apps": "appStartupAppsGraph",
            "running_services": "appRunningServicesGraph",
        },
    },
    "terminal": {
        "keywords": ["terminal", "command", "shell", "powershell", "cmd",
                     "bash", "ssh", "script", "execute"],
        "pipelines": {
            "execute_command": "terminalExecuteCommandGraph",
            "execute_script": "terminalExecuteScriptGraph",
            "powershell": "terminalPowershellGraph",
            "cmd": "terminalCmdGraph",
            "bash": "terminalBashGraph",
            "ssh": "terminalSshGraph",
            "env_vars": "terminalEnvironmentVariablesGraph",
            "long_running": "terminalLongRunningTaskGraph",
            "interactive": "terminalInteractiveShellGraph",
            "parse_output": "terminalParseOutputGraph",
            "kill_process": "terminalKillProcessGraph",
            "monitor_output": "terminalMonitorOutputGraph",
            "exit_code": "terminalExitCodeGraph",
            "retry": "terminalRetryCommandGraph",
            "stream_logs": "terminalStreamLogsGraph",
        },
    },
    "dev": {
        "keywords": ["code", "git", "build", "compile", "test", "debug",
                     "docker", "kubernetes", "npm", "python", "java",
                     "vscode", "workspace", "project"],
        "pipelines": {
            "open_vscode": "devOpenVscodeGraph",
            "workspace_detect": "devWorkspaceDetectionGraph",
            "git_clone": "devGitCloneGraph",
            "git_commit": "devGitCommitGraph",
            "git_push": "devGitPushGraph",
            "git_pull": "devGitPullGraph",
            "git_branch": "devGitBranchGraph",
            "git_merge": "devGitMergeGraph",
            "git_status": "devGitStatusGraph",
            "build": "devBuildProjectGraph",
            "run": "devRunProjectGraph",
            "stop": "devStopProjectGraph",
            "install_deps": "devInstallDependenciesGraph",
            "test": "devTestProjectGraph",
            "debug": "devDebugSessionGraph",
            "docker_build": "devDockerBuildGraph",
            "docker_run": "devDockerRunGraph",
            "docker_compose": "devDockerComposeGraph",
            "k8s_apply": "devKubernetesApplyGraph",
            "npm": "devNpmGraph",
            "python": "devPythonGraph",
            "java": "devJavaGraph",
            "csharp": "devCsharpGraph",
            "logs": "devLogsGraph",
            "package_manager": "devPackageManagerGraph",
        },
    },
    "ocr": {
        "keywords": ["ocr", "text recognition", "read text", "extract text",
                     "scan text", "receipt", "handwriting"],
        "pipelines": {
            "screen": "ocrScreenGraph",
            "region": "ocrRegionGraph",
            "window": "ocrWindowGraph",
            "table": "ocrTableGraph",
            "receipt": "ocrReceiptGraph",
            "handwriting": "ocrHandwritingGraph",
            "text_detection": "ocrTextDetectionGraph",
            "confidence_filter": "ocrConfidenceFilterGraph",
            "language_detection": "ocrLanguageDetectionGraph",
            "translate": "ocrTranslateGraph",
            "structured": "ocrStructuredGraph",
            "verify": "ocrVerifyGraph",
            "cache": "ocrCacheGraph",
            "history": "ocrHistoryGraph",
            "compare": "ocrCompareGraph",
        },
    },
    "vision": {
        "keywords": ["vision", "detect", "recognize", "see", "look",
                     "button", "icon", "image", "logo", "color", "cursor",
                     "object", "region", "ui", "layout", "template"],
        "pipelines": {
            "detect_button": "visionDetectButtonGraph",
            "detect_icon": "visionDetectIconGraph",
            "detect_window": "visionDetectWindowGraph",
            "detect_form": "visionDetectFormGraph",
            "detect_image": "visionDetectImageGraph",
            "detect_logo": "visionDetectLogoGraph",
            "detect_color": "visionDetectColorGraph",
            "detect_text": "visionDetectTextGraph",
            "detect_cursor": "visionDetectCursorGraph",
            "object_tracking": "visionObjectTrackingGraph",
            "region_selection": "visionRegionSelectionGraph",
            "ui_analysis": "visionUiAnalysisGraph",
            "screen_segmentation": "visionScreenSegmentationGraph",
            "layout_detection": "visionLayoutDetectionGraph",
            "confidence_scoring": "visionConfidenceScoringGraph",
            "element_ranking": "visionElementRankingGraph",
            "element_verification": "visionElementVerificationGraph",
            "visual_comparison": "visionVisualComparisonGraph",
            "pixel_difference": "visionPixelDifferenceGraph",
            "template_matching": "visionTemplateMatchingGraph",
        },
    },
    "clipboard": {
        "keywords": ["clipboard", "copy", "paste", "clip", "cut"],
        "pipelines": {
            "copy": "clipboardCopyGraph",
            "paste": "clipboardPasteGraph",
            "read": "clipboardReadGraph",
            "clear": "clipboardClearGraph",
            "history": "clipboardHistoryGraph",
            "monitor": "clipboardMonitorGraph",
            "rich_text": "clipboardRichTextGraph",
            "html": "clipboardHtmlGraph",
            "image": "clipboardImageGraph",
            "file": "clipboardFileGraph",
        },
    },
    "email": {
        "keywords": ["email", "mail", "gmail", "outlook", "message",
                     "compose", "reply", "forward", "attach", "send",
                     "draft", "search", "label", "archive", "spam"],
        "pipelines": {
            "compose": "emailComposeGraph",
            "reply": "emailReplyGraph",
            "forward": "emailForwardGraph",
            "attach": "emailAttachGraph",
            "send": "emailSendGraph",
            "draft": "emailDraftGraph",
            "search": "emailSearchGraph",
            "download_attachment": "emailDownloadAttachmentGraph",
            "save_attachment": "emailSaveAttachmentGraph",
            "label": "emailLabelGraph",
            "archive": "emailArchiveGraph",
            "delete": "emailDeleteGraph",
            "spam": "emailSpamGraph",
            "contacts": "emailContactsGraph",
            "calendar_invite": "emailCalendarInviteGraph",
        },
    },
    "network": {
        "keywords": ["network", "internet", "wifi", "http", "download",
                     "upload", "ping", "dns", "port", "websocket", "ftp",
                     "smb", "vpn", "lan", "api"],
        "pipelines": {
            "http_request": "networkHttpRequestGraph",
            "download": "networkDownloadGraph",
            "upload": "networkUploadGraph",
            "ping": "networkPingGraph",
            "dns_lookup": "networkDnsLookupGraph",
            "port_scan": "networkPortScanGraph",
            "websocket": "networkWebsocketGraph",
            "ftp": "networkFtpGraph",
            "smb": "networkSmbGraph",
            "vpn_status": "networkVpnStatusGraph",
            "internet_check": "networkInternetCheckGraph",
            "wifi": "networkWifiGraph",
            "lan_devices": "networkLanDevicesGraph",
            "api_auth": "networkApiAuthGraph",
            "monitor": "networkMonitorGraph",
        },
    },
    "media": {
        "keywords": ["media", "screenshot", "screen record", "camera",
                     "audio", "video", "image", "pdf", "watermark",
                     "thumbnail", "convert", "resize", "crop"],
        "pipelines": {
            "screenshot": "mediaScreenshotGraph",
            "screen_record": "mediaScreenRecordGraph",
            "camera": "mediaCameraGraph",
            "audio_record": "mediaAudioRecordGraph",
            "audio_play": "mediaAudioPlayGraph",
            "video_play": "mediaVideoPlayGraph",
            "convert_image": "mediaConvertImageGraph",
            "resize_image": "mediaResizeImageGraph",
            "crop_image": "mediaCropImageGraph",
            "pdf_to_image": "mediaPdfToImageGraph",
            "image_to_pdf": "mediaImageToPdfGraph",
            "watermark": "mediaWatermarkGraph",
            "thumbnail": "mediaThumbnailGraph",
            "ocr_image": "mediaOcrImageGraph",
            "metadata": "mediaMetadataGraph",
        },
    },
    "doc": {
        "keywords": ["document", "pdf", "word", "excel", "powerpoint",
                     "csv", "markdown", "html", "json", "xml", "print",
                     "signature", "compare", "convert"],
        "pipelines": {
            "pdf_read": "docPdfReadGraph",
            "pdf_write": "docPdfWriteGraph",
            "pdf_merge": "docPdfMergeGraph",
            "pdf_split": "docPdfSplitGraph",
            "word_read": "docWordReadGraph",
            "word_write": "docWordWriteGraph",
            "excel_read": "docExcelReadGraph",
            "excel_write": "docExcelWriteGraph",
            "powerpoint_read": "docPowerpointReadGraph",
            "powerpoint_write": "docPowerpointWriteGraph",
            "csv_read": "docCsvReadGraph",
            "csv_write": "docCsvWriteGraph",
            "markdown": "docMarkdownGraph",
            "html": "docHtmlGraph",
            "json": "docJsonGraph",
            "xml": "docXmlGraph",
            "compare": "docCompareDocumentsGraph",
            "convert": "docConvertDocumentsGraph",
            "print": "docPrintGraph",
            "digital_signature": "docDigitalSignatureGraph",
        },
    },
    "system": {
        "keywords": ["system", "pc", "computer", "laptop", "status",
                     "disk", "memory", "ram", "cpu", "process", "service",
                     "startup", "settings", "control panel"],
        "pipelines": {
            "status": "systemStatusGraph",
            "disk_usage": "systemDiskUsageGraph",
            "ram_usage": "systemRamUsageGraph",
            "cpu_usage": "systemCpuUsageGraph",
            "processes": "systemProcessesGraph",
            "services": "systemServicesGraph",
            "startup": "systemStartupGraph",
            "settings": "systemSettingsGraph",
            "shutdown": "systemShutdownGraph",
            "restart": "systemRestartGraph",
            "lock": "systemLockGraph",
            "sleep": "systemSleepGraph",
            "hibernate": "systemHibernateGraph",
            "wake": "systemWakeGraph",
            "keep_awake": "systemKeepAwakeGraph",
            "mouse_jiggle": "systemMouseJiggleGraph",
        },
    },
    "screen": {
        "keywords": ["screen", "display", "monitor", "screenshot", "ui",
                     "element", "click", "tap", "scan"],
        "pipelines": {
            "scan": "screenScanGraph",
            "click_text": "screenClickTextGraph",
            "screenshot": "screenScreenshotGraph",
            "find_element": "screenFindElementGraph",
            "wait_for": "screenWaitForGraph",
            "verify": "screenVerifyGraph",
        },
    },
    "vault": {
        "keywords": ["vault", "password", "credential", "login", "sign in",
                     "authenticate", "passkey", "secret"],
        "pipelines": {
            "unlock": "vaultUnlockGraph",
            "lock": "vaultLockGraph",
            "add": "vaultAddGraph",
            "get": "vaultGetGraph",
            "list": "vaultListGraph",
            "rotate": "vaultRotateGraph",
            "password_login": "authPasswordLoginGraph",
            "passkey_login": "authPasskeyLoginGraph",
        },
    },
    "memory": {
        "keywords": ["memory", "remember", "recall", "forget", "learn",
                     "history", "preference", "workflow"],
        "pipelines": {
            "remember": "memoryRememberGraph",
            "recall": "memoryRecallGraph",
            "search": "memorySearchGraph",
            "forget": "memoryForgetGraph",
            "list": "memoryListGraph",
            "save_template": "memorySaveTemplateGraph",
            "get_template": "memoryGetTemplateGraph",
            "list_templates": "memoryListTemplatesGraph",
            "match_template": "memoryMatchTemplateGraph",
        },
    },
    "task": {
        "keywords": ["task", "workflow", "schedule", "automate", "chain",
                     "pipeline", "dag", "graph"],
        "pipelines": {
            "create": "taskCreateGraph",
            "run": "taskRunGraph",
            "cancel": "taskCancelGraph",
            "status": "taskStatusGraph",
            "schedule": "taskScheduleGraph",
            "chain": "taskChainGraph",
            "parallel": "taskParallelGraph",
            "branch": "taskBranchGraph",
            "loop": "taskLoopGraph",
            "template": "taskTemplateGraph",
        },
    },
    "approval": {
        "keywords": ["approval", "approve", "reject", "permission", "allow",
                     "deny", "gate"],
        "pipelines": {
            "request": "approvalRequestGraph",
            "resolve": "approvalResolveGraph",
            "list_pending": "approvalListPendingGraph",
            "history": "approvalHistoryGraph",
        },
    },
    "research": {
        "keywords": ["research", "investigate", "study", "explore",
                     "collect", "gather", "compile"],
        "pipelines": {
            "collect": "researchCollectGraph",
            "summarize": "researchSummarizeGraph",
            "compare_sources": "researchCompareSourcesGraph",
            "save_report": "researchSaveReportGraph",
        },
    },
}


# ===========================================================================
# SECTION 4: PHASE UTILITY KNOWLEDGE
# ===========================================================================
PHASE_UTILITY_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "intent": {
        "keywords": ["intent", "classify", "understand", "interpret"],
        "utilities": [
            "globalIntentClassifier", "globalIntentEngine",
            "globalIntentNormalizer", "globalIntentMapper",
            "globalIntentHistory", "globalMultiIntentSplitter",
            "globalEntityExtractor", "globalParameterExtractor",
            "globalSlotFiller", "globalConfidenceScorer",
            "globalContextEnricher", "globalPipelineSelector",
            "globalGoalDecomposer",
        ],
    },
    "context": {
        "keywords": ["context", "environment", "state", "gather"],
        "utilities": [
            "globalContextEngine", "globalDesktopStateProvider",
            "globalActiveWindowTracker", "globalFocusedAppDetector",
            "globalClipboardContext", "globalSelectedFilesTracker",
            "globalProcessRegistry", "globalBrowserSessionRegistry",
            "globalUserPreferencesStore", "globalVariableStore",
            "globalEnvironmentState",
        ],
    },
    "observation": {
        "keywords": ["observe", "watch", "monitor", "track", "detect"],
        "utilities": [
            "globalWindowObserver", "globalProcessObserver",
            "globalBrowserObserver", "globalFilesystemObserver",
            "globalClipboardObserver", "globalOCRObserver",
            "globalVisionObserver", "globalAccessibilityObserver",
            "globalNetworkObserver", "globalSystemObserver",
            "globalObservationEngineBridge",
        ],
    },
    "verification": {
        "keywords": ["verify", "check", "confirm", "validate", "test"],
        "utilities": [
            "globalStateVerifier", "globalUIVerifier", "globalDOMVerifier",
            "globalOCRVerifier", "globalFilesystemVerifier",
            "globalAPIVerifier", "globalProcessVerifier",
            "globalWindowVerifier", "globalImageVerifier",
            "globalCustomVerifier", "globalVerificationEngineBridge",
        ],
    },
    "recovery": {
        "keywords": ["recover", "retry", "rollback", "replan", "abort"],
        "utilities": [
            "globalRetryStrategy", "globalAlternativePipeline",
            "globalRollbackManager", "globalReObserver",
            "globalReplanner", "globalSafeAbort",
            "globalUserApprovalGate", "globalFailureClassifier",
            "globalRecoveryPolicy", "globalRecoveryHistory",
            "globalRecoveryEngineBridge",
        ],
    },
    "memory": {
        "keywords": ["memory", "remember", "recall", "forget", "learn"],
        "utilities": [
            "globalShortTermMemory", "globalLongTermMemory",
            "globalTaskHistory", "globalWorkflowMemory",
            "globalUserPreferences", "globalApplicationProfile",
            "globalActionFrequency", "globalObservationCache",
            "globalMemoryCleanup", "globalMemoryIndex",
            "globalMemoryUpdateBridge",
        ],
    },
    "skill": {
        "keywords": ["skill", "capability", "provider", "fallback"],
        "utilities": [
            "globalSkillDiscovery", "globalSkillRanking",
            "globalSkillFallback", "globalSkillChaining",
            "globalSkillDependencyResolver", "globalSkillCache",
            "globalSkillHealthMonitor", "globalProviderSelector",
            "globalSkillRetryPolicy", "globalSkillMetrics",
            "globalSkillOrchestratorBridge",
        ],
    },
    "state": {
        "keywords": ["state", "snapshot", "track", "persist"],
        "utilities": [
            "globalDesktopState", "globalBrowserState", "globalWindowState",
            "globalFileState", "globalTaskState", "globalExecutionState",
            "globalPipelineState", "globalAgentState",
            "globalResourceState", "globalStateVariableStore",
        ],
    },
    "workflow": {
        "keywords": ["workflow", "schedule", "chain", "branch", "loop"],
        "utilities": [
            "globalWorkflowBuilder", "globalWorkflowBrancher",
            "globalWorkflowLoop", "globalWorkflowCondition",
            "globalWorkflowParallel", "globalWorkflowScheduler",
            "globalWorkflowTrigger", "globalWorkflowTemplate",
            "globalWorkflowNested", "globalWorkflowPersistence",
        ],
    },
    "provider": {
        "keywords": ["provider", "service", "backend", "implementation"],
        "utilities": [
            "globalProviderRegistry", "globalProviderSelectorV2",
            "globalProviderFallback", "globalProviderLoadBalancer",
            "globalProviderCircuitBreaker", "globalProviderHealthMonitor",
            "globalProviderCapabilityMatcher", "globalProviderConfigManager",
            "globalProviderMetricsCollector", "globalProviderLifecycleManager",
        ],
    },
    "agent_runtime": {
        "keywords": ["agent", "runtime", "orchestrate", "execute"],
        "utilities": [
            "globalIntentEngine", "globalContextEngine",
            "globalRuntimePlanner", "globalRuntimeExecutionGraphBuilder",
            "globalPipelineRegistryBridge", "globalRuntimeExecutionEngine",
            "globalSkillOrchestratorBridge", "globalObservationEngineBridge",
            "globalVerificationEngineBridge", "globalRecoveryEngineBridge",
            "globalMemoryUpdateBridge", "globalAgentRuntime",
        ],
    },
    "event": {
        "keywords": ["event", "emit", "subscribe", "listen", "notify"],
        "utilities": [
            "globalEventBus", "globalEventTypes", "globalEventFilter",
            "globalEventRouter", "globalEventRecorder",
            "globalEventReplayer", "globalEventAggregator",
            "globalEventTracer",
        ],
    },
    "native": {
        "keywords": ["native", "cpp", "c++", "accelerator", "fast"],
        "utilities": ["globalNativeBridge"],
    },
}


# ===========================================================================
# SECTION 5: BACKEND FILE KNOWLEDGE
# ===========================================================================
BACKEND_FILE_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "agent": {
        "path": "ai_pc_operator/backend/app/agent/",
        "files": {
            "planner.py": "Intent classification + plan creation (this file)",
            "router.py": "AgentRouter - main command pipeline",
            "task_planner.py": "High-level compound task planner",
            "task_graph.py": "DAG task executor",
            "memory_engine.py": "Persistent memory engine",
            "prompts.py": "LLM prompt templates",
            "graph_schema.py": "Execution graph schema",
        },
    },
    "tools": {
        "path": "ai_pc_operator/backend/app/tools/",
        "files": {
            "file_tools.py": "File operations (list, scan, quarantine, restore)",
            "system_tools.py": "System control (status, open_app, close_app, etc.)",
            "browser_tools.py": "Browser automation (open, search, click, type)",
            "download_tools.py": "Download manager",
            "auth_tools.py": "Authentication (password, passkey)",
            "screen_tools.py": "Screen perception (scan, click_text)",
        },
    },
    "security": {
        "path": "ai_pc_operator/backend/app/security/",
        "files": {
            "risk.py": "Risk classifier",
            "permissions.py": "Permission engine",
            "pairing.py": "Device pairing (6-digit code)",
            "pairing_v2.py": "Enhanced pairing (QR, trust, biometric)",
            "vault.py": "Encrypted password vault",
        },
    },
    "approvals": {
        "path": "ai_pc_operator/backend/app/approvals/",
        "files": {
            "manager.py": "Approval request manager",
        },
    },
    "db": {
        "path": "ai_pc_operator/backend/app/db/",
        "files": {
            "database.py": "SQLite connection + schema",
            "models.py": "Pydantic models",
        },
    },
    "logs": {
        "path": "ai_pc_operator/backend/app/logs/",
        "files": {
            "redactor.py": "Log redactor (removes secrets)",
        },
    },
    "runtime": {
        "path": "ai_pc_operator/backend/app/runtime/",
        "files": {
            "resource_budget.py": "RAM budget measurement",
            "io_pool.py": "Shared I/O thread pool",
            "model_registry.py": "Lazy model registry",
            "heatmap.py": "Intent-to-tool heat map",
            "tier_manager.py": "RAM-aware tier decisions",
            "model_insights.py": "Model routing insights",
        },
    },
    "skills": {
        "path": "ai_pc_operator/backend/app/skills/",
        "files": {
            "contracts.py": "Pydantic skill types",
            "registry.py": "SQLite-backed skill registry",
            "verification.py": "Verification engine (8 verifiers)",
            "runtime.py": "Skill runtime (retry, timeout, verify)",
            "handlers.py": "Async tool wrappers",
            "mvp_pack.py": "50-skill MVP pack",
        },
    },
    "observability": {
        "path": "ai_pc_operator/backend/app/observability/",
        "files": {
            "tracer.py": "Structured trace events",
        },
    },
    "pipeline": {
        "path": "pipeline/",
        "files": {
            "screenai_pipelines.js": "30k lines, 268 pipeline graphs, 154 phase utilities",
            "operations.js": "14 operations registry",
            "engine.js": "ExecutionGraphRunner + legacy Pipeline",
            "cli.js": "CLI for graph validation and execution",
            "test_pipeline.js": "43 regression tests",
        },
    },
}


# ===========================================================================
# SECTION 6: COGNITIVE PLANNER LAYERS (Master Cognitive Planner v1.0)
# ===========================================================================
# These layers implement the SCREEN-AI MASTER COGNITIVE PLANNER specification:
#   - Language understanding (synonyms, abbreviations, acronyms, typos)
#   - Command normalization (canonical actions)
#   - Task decomposition (atomic actions)
#   - Pipeline router (dynamic pipeline selection)
#   - Model selection (only invoke required models)
#   - OCR strategy (semantic matching, not exact text)
#   - Vision strategy (UI element detection)
#   - Accessibility strategy (fallback chain)
#   - Website strategy (browser detection + reuse)
#   - Wait strategy (dynamic waits, no fixed delays)
#   - Verification (every action)
#   - Recovery (intelligent retry, max 3)
#   - Memory (aliases)
#   - Context (multi-step task tracking)
#   - Planning output (confidence + risk scores)
#   - Autonomy (infer obvious steps)
#   - Failure policy (explain why, suggest alternatives)

# ---------------------------------------------------------------------------
# 6.1 CANONICAL ACTIONS - normalize user language into canonical verbs
# ---------------------------------------------------------------------------
CANONICAL_ACTIONS: Dict[str, List[str]] = {
    "ACTION_OPEN": ["open", "launch", "run", "fire up", "bring up", "access",
                    "load", "start", "boot", "spin up", "kick off", "show",
                    "go to", "navigate to", "visit", "browse"],
    "ACTION_CLOSE": ["close", "quit", "exit", "shut down", "shutdown", "kill",
                     "terminate", "end", "dismiss", "stop", "wrap up",
                     "finish", "get rid of", "remove"],
    "ACTION_CLICK": ["click", "tap", "press", "hit", "choose", "select",
                     "pick", "activate"],
    "ACTION_TYPE": ["type", "enter", "write", "fill", "input", "key in",
                    "put in"],
    "ACTION_SEARCH": ["search", "find", "locate", "look for", "look up",
                      "lookup", "query", "google"],
    "ACTION_NAVIGATE": ["go to", "visit", "browse", "navigate", "open website",
                        "take me to"],
    "ACTION_SEND": ["send", "transmit", "dispatch", "deliver", "submit",
                    "fire off"],
    "ACTION_RECEIVE": ["receive", "get", "fetch", "retrieve", "download",
                       "grab"],
    "ACTION_DELETE": ["delete", "remove", "erase", "wipe", "trash",
                      "get rid of", "clear", "drop", "purge", "destroy"],
    "ACTION_LIST": ["list", "show", "display", "enumerate", "view", "see"],
    "ACTION_CHECK": ["check", "inspect", "report", "status", "diagnose",
                     "scan", "analyze", "examine"],
    "ACTION_SAVE": ["save", "store", "persist", "write", "keep"],
    "ACTION_LOAD": ["load", "read", "open", "fetch", "import"],
    "ACTION_INSTALL": ["install", "setup", "set up", "deploy"],
    "ACTION_UNINSTALL": ["uninstall", "remove", "delete"],
    "ACTION_UPDATE": ["update", "upgrade", "patch", "refresh"],
    "ACTION_RESTART": ["restart", "reboot", "reset", "reload"],
    "ACTION_SHUTDOWN": ["shutdown", "shut down", "power off", "turn off"],
    "ACTION_LOCK": ["lock", "secure", "protect"],
    "ACTION_UNLOCK": ["unlock", "release", "free"],
    "ACTION_LOGIN": ["login", "sign in", "log in", "authenticate"],
    "ACTION_LOGOUT": ["logout", "sign out", "log out"],
    "ACTION_UPLOAD": ["upload", "push", "send up"],
    "ACTION_DOWNLOAD": ["download", "pull", "fetch", "grab"],
    "ACTION_BACKUP": ["backup", "save", "snapshot", "copy"],
    "ACTION_RESTORE": ["restore", "recover", "bring back"],
    "ACTION_MINIMIZE": ["minimize", "minify", "shrink"],
    "ACTION_MAXIMIZE": ["maximize", "enlarge", "expand", "fullscreen"],
    "ACTION_FOCUS": ["focus", "activate", "bring to front", "select"],
    "ACTION_SWITCH": ["switch", "change", "toggle", "flip"],
    "ACTION_VERIFY": ["verify", "check", "confirm", "validate", "test"],
    "ACTION_RETRY": ["retry", "try again", "redo", "repeat"],
    "ACTION_CANCEL": ["cancel", "abort", "stop", "revoke"],
    "ACTION_APPROVE": ["approve", "accept", "allow", "grant", "permit"],
    "ACTION_REJECT": ["reject", "deny", "refuse", "block", "disallow"],
    "ACTION_REMEMBER": ["remember", "save", "store", "note", "record"],
    "ACTION_FORGET": ["forget", "delete", "erase", "clear"],
    "ACTION_SUMMARIZE": ["summarize", "condense", "shorten", "tldr"],
    "ACTION_HELP": ["help", "assist", "support", "aid"],
    "ACTION_ENABLE": ["enable", "activate", "turn on", "switch on"],
    "ACTION_DISABLE": ["disable", "deactivate", "turn off", "switch off"],
    "ACTION_HIDE": ["hide", "conceal", "mask", "cover"],
    "ACTION_REPLACE": ["replace", "substitute", "swap", "exchange"],
    "ACTION_SORT": ["sort", "order", "arrange", "rank"],
    "ACTION_FILTER": ["filter", "sieve", "strain", "narrow"],
    "ACTION_COUNT": ["count", "tally", "enumerate", "number"],
    "ACTION_VALIDATE": ["validate", "verify", "confirm", "authenticate"],
    "ACTION_LOG": ["log", "record", "trace", "track"],
    "ACTION_DEBUG": ["debug", "troubleshoot", "diagnose", "fix"],
    "ACTION_OPTIMIZE": ["optimize", "improve", "enhance", "tune"],
    "ACTION_SECURE": ["secure", "protect", "harden", "lock down"],
    "ACTION_ENCRYPT": ["encrypt", "encode", "scramble", "cipher"],
    "ACTION_DECRYPT": ["decrypt", "decode", "descramble", "decipher"],
    "ACTION_CLEAN": ["clean", "tidy", "purge", "scrub"],
    "ACTION_ORGANIZE": ["organize", "arrange", "structure", "order"],
    "ACTION_PLAN": ["plan", "schedule", "design", "draft"],
    "ACTION_EXECUTE": ["execute", "run", "perform", "carry out"],
    "ACTION_TEST": ["test", "try", "experiment", "validate"],
    "ACTION_DEPLOY": ["deploy", "release", "publish", "ship"],
    "ACTION_BUILD": ["build", "compile", "construct", "assemble"],
    "ACTION_PAUSE": ["pause", "suspend", "freeze"],
    "ACTION_RESUME": ["resume", "continue", "proceed"],
    "ACTION_SKIP": ["skip", "jump", "bypass"],
    "ACTION_UNDO": ["undo", "reverse", "revert"],
    "ACTION_REDO": ["redo", "repeat", "do again"],
    "ACTION_IMPORT": ["import", "bring in", "load"],
    "ACTION_EXPORT": ["export", "send out", "output"],
    "ACTION_SCAN": ["scan", "examine", "inspect", "check"],
    "ACTION_DETECT": ["detect", "find", "discover", "identify"],
    "ACTION_RECOGNIZE": ["recognize", "identify", "detect"],
    "ACTION_CLASSIFY": ["classify", "categorize", "sort", "label"],
    "ACTION_TAG": ["tag", "label", "mark"],
    "ACTION_SELECT": ["select", "choose", "pick"],
    "ACTION_CONNECT": ["connect", "join", "link", "attach"],
    "ACTION_DISCONNECT": ["disconnect", "detach", "unlink", "separate"],
    "ACTION_INSERT": ["insert", "add", "put in"],
    "ACTION_PUSH": ["push", "send", "upload"],
    "ACTION_PULL": ["pull", "fetch", "download", "get"],
    "ACTION_PING": ["ping", "check", "test"],
    "ACTION_TRACE": ["trace", "track", "follow"],
    "ACTION_ROUTE": ["route", "direct", "guide"],
    "ACTION_FORWARD": ["forward", "pass on", "relay"],
    "ACTION_BACK": ["back", "reverse", "return"],
    "ACTION_NEXT": ["next", "forward", "skip ahead"],
    "ACTION_PREVIOUS": ["previous", "back", "prior"],
}


def normalize_to_canonical(text: str) -> List[Tuple[str, str]]:
    """Normalize user text into a list of (canonical_action, original_phrase).

    Example:
        "Open Chrome" -> [("ACTION_OPEN", "Open")]
        "Click Login" -> [("ACTION_OPEN", "Open"), ("ACTION_CLICK", "Click")]
    """
    if not text:
        return []
    text_lower = text.lower()
    found: List[Tuple[str, str]] = []
    # Sort by phrase length (longest first) so multi-word phrases match first
    all_phrases: List[Tuple[str, str, str]] = []
    for canonical, phrases in CANONICAL_ACTIONS.items():
        for phrase in phrases:
            all_phrases.append((canonical, phrase, phrase))
    all_phrases.sort(key=lambda x: -len(x[1]))
    used_spans: List[Tuple[int, int]] = []
    for canonical, phrase, _ in all_phrases:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        for m in re.finditer(pattern, text_lower):
            span = (m.start(), m.end())
            if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in used_spans):
                continue
            used_spans.append(span)
            found.append((canonical, phrase))
            break  # one match per phrase is enough
    return found


# ---------------------------------------------------------------------------
# 6.2 USER ALIASES - remember user-specific shortcuts
# ---------------------------------------------------------------------------
USER_ALIASES: Dict[str, str] = {
    # Chat / messaging
    "dc": "discord",
    "discord": "discord",
    "tg": "telegram",
    "wa": "whatsapp",
    "imessage": "messages",
    "sms": "messages",
    # Editors / IDEs
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "vsc": "visual studio code",
    "code": "visual studio code",
    "sublime": "sublime text",
    "intellij": "intellij idea",
    "pycharm": "pycharm",
    "webstorm": "webstorm",
    "rider": "jetbrains rider",
    "android studio": "android studio",
    "xcode": "xcode",
    # Browsers
    "ff": "firefox",
    "gc": "google chrome",
    "msedge": "microsoft edge",
    "edge": "microsoft edge",
    # Sites
    "yt": "youtube",
    "gh": "github",
    "gmail": "gmail",
    "gm": "gmail",
    "fb": "facebook",
    "ig": "instagram",
    "in": "linkedin",
    "li": "linkedin",
    "rd": "reddit",
    "tw": "twitter",
    "x": "twitter",
    "wp": "wordpress",
    "so": "stackoverflow",
    "wiki": "wikipedia",
    "ddg": "duckduckgo",
    "maps": "google maps",
    "gmap": "google maps",
    "gd": "google drive",
    "drive": "google drive",
    # Productivity
    "gcal": "google calendar",
    "cal": "calendar",
    "notes": "notes",
    "keep": "google keep",
    "todo": "microsoft todo",
    "tasks": "microsoft todo",
    # Office
    "word": "microsoft word",
    "excel": "microsoft excel",
    "ppt": "microsoft powerpoint",
    "powerpoint": "microsoft powerpoint",
    "outlook": "microsoft outlook",
    "onenote": "microsoft onenote",
    # System
    "explorer": "file explorer",
    "fe": "file explorer",
    "taskmgr": "task manager",
    "tm": "task manager",
    "regedit": "registry editor",
    "devmgmt": "device manager",
    "dm": "device manager",
    "mspaint": "paint",
    "ms-settings": "settings",
    "control": "control panel",
    "cmd": "command prompt",
    "ps": "powershell",
    "wt": "windows terminal",
    "terminal": "windows terminal",
    # Media
    "yt music": "youtube music",
    "ytm": "youtube music",
    "spotify": "spotify",
    "vlc": "vlc media player",
    # Dev tools
    "gh cli": "github cli",
    "docker": "docker desktop",
    "k8s": "kubernetes",
    "kubectl": "kubernetes",
    # AI tools
    "gpt": "chatgpt",
    "claude": "claude",
    "gemini": "gemini",
    "copilot": "github copilot",
    "cursor": "cursor",
    # Common shortcuts
    "calc": "calculator",
    "sticky": "sticky notes",
    "snip": "snipping tool",
    "recorder": "voice recorder",
}


def resolve_user_alias(text: str) -> str:
    """Resolve user-specific aliases in text.

    Example:
        "Open DC" -> "Open Discord"
        "VSCode please" -> "Visual Studio Code please"
        "YT" -> "YouTube"
    """
    if not text:
        return text
    # Single-pass left-to-right scan with a cursor. When an alias matches at
    # the cursor, we append its replacement and advance the cursor past the
    # ORIGINAL match — so a replacement that itself contains another alias's
    # text (e.g. "vscode" -> "visual studio code" contains "code") is never
    # re-expanded.
    aliases = sorted(USER_ALIASES.keys(), key=len, reverse=True)
    compiled = [(a, re.compile(r"\b" + re.escape(a) + r"\b", re.IGNORECASE))
                for a in aliases]
    out_parts: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        matched = None
        for alias, pattern in compiled:
            m = pattern.match(text, i)
            if m:
                matched = (alias, m)
                break
        if matched is None:
            out_parts.append(text[i])
            i += 1
        else:
            alias, m = matched
            out_parts.append(USER_ALIASES[alias])
            i = m.end()
    return "".join(out_parts)


# ---------------------------------------------------------------------------
# 6.3 SPELLING CORRECTIONS - handle common typos
# ---------------------------------------------------------------------------
SPELLING_CORRECTIONS: Dict[str, str] = {
    # Apps
    "chrom": "chrome", "chorme": "chrome", "crome": "chrome",
    "chrone": "chrome", "chromme": "chrome",
    "edeg": "edge", "edg": "edge", "mircosoft edge": "microsoft edge",
    "firefoxx": "firefox", "firfox": "firefox", "firef ox": "firefox",
    "explorere": "explorer", "exploror": "explorer",
    "notepadplus": "notepad++", "notepadpluss": "notepad++",
    "power shel": "powershell", "powereshell": "powershell",
    "powereshel": "powershell", "powrshell": "powershell",
    "termianl": "terminal", "terminall": "terminal", "termianl": "terminal",
    "calculater": "calculator", "calcualtor": "calculator",
    "calculater": "calculator", "calcultor": "calculator",
    "excell": "excel", "exel": "excel", "excelll": "excel",
    "powerpoin": "powerpoint", "powerpoit": "powerpoint",
    "powerpointe": "powerpoint",
    "wordd": "word", "wordl": "word",
    "outlok": "outlook", "outllok": "outlook",
    "spotfy": "spotify", "spotfiy": "spotify", "spotifi": "spotify",
    "discorde": "discord", "discor": "discord", "discod": "discord",
    "slcak": "slack", "slakc": "slack",
    "telegramm": "telegram", "telgram": "telegram",
    "whatsap": "whatsapp", "whatsupp": "whatsapp",
    "vscodee": "vscode", "vscde": "vscode", "vscod": "vscode",
    "vscodee": "vscode", "vscodd": "vscode",
    "sublim": "sublime", "sublimee": "sublime",
    "photoshope": "photoshop", "photosho": "photoshop",
    "blendr": "blender", "blenderr": "blender",
    "obss": "obs", "obbs": "obs",
    "zoomme": "zoom", "zooom": "zoom",
    "teamss": "teams", "teamms": "teams",
    # Sites
    "youtub": "youtube", "youtbe": "youtube", "youtubee": "youtube",
    "yutube": "youtube", "youtubee": "youtube",
    "githb": "github", "githun": "github", "githhub": "github",
    "githhub": "github", "githb": "github",
    "googel": "google", "goole": "google", "gogle": "google",
    "gmaill": "gmail", "gmial": "gmail", "gmaiil": "gmail",
    "facebok": "facebook", "faceboook": "facebook", "fb": "facebook",
    "instgram": "instagram", "instagramm": "instagram", "instgram": "instagram",
    "linkedin": "linkedin", "linkdin": "linkedin", "linkedinn": "linkedin",
    "reddi": "reddit", "reditt": "reddit", "reddit": "reddit",
    "twiter": "twitter", "twiiter": "twitter", "twiter": "twitter",
    "wikipedi": "wikipedia", "wikipedea": "wikipedia",
    "stackoverflo": "stackoverflow", "stackoverfow": "stackoverflow",
    "stackoverflow": "stackoverflow",
    "duckduckg": "duckduckgo", "duckduckgo": "duckduckgo",
    "amazom": "amazon", "amazonn": "amazon", "amzon": "amazon",
    "netfli": "netflix", "netflixx": "netflix", "netflx": "netflix",
    "spotfy": "spotify", "spotfiy": "spotify",
    "twitchh": "twitch", "twich": "twitch",
    # Verbs
    "opne": "open", "oen": "open", "oopen": "open", "opem": "open",
    "clsoe": "close", "clsose": "close", "cloase": "close", "cloes": "close",
    "laucnh": "launch", "lanuch": "launch", "lauch": "launch",
    "serach": "search", "seach": "search", "saerch": "search",
    "seearch": "search", "serch": "search",
    "fnd": "find", "fin": "find", "finnd": "find",
    "deleet": "delete", "delte": "delete", "delelte": "delete",
    "delet": "delete", "deltee": "delete",
    "clik": "click", "clikc": "click", "clicck": "click", "clik": "click",
    "typpe": "type", "tyep": "type", "tpye": "type",
    "navigte": "navigate", "naviagte": "navigate", "naviagte": "navigate",
    "vist": "visit", "visti": "visit", "visitt": "visit",
    "instll": "install", "intall": "install", "instlal": "install",
    "uninstll": "uninstall", "unintall": "uninstall",
    "updte": "update", "upate": "update", "updat": "update",
    "restrt": "restart", "restat": "restart", "restarrt": "restart",
    "shutdonw": "shutdown", "shutdwon": "shutdown", "shutdowm": "shutdown",
    "rebot": "reboot", "reboto": "reboot",
    "logi": "login", "logni": "login", "loginn": "login",
    "logou": "logout", "loguot": "logout",
    "donwload": "download", "dwonload": "download", "dowload": "download",
    "uplad": "upload", "upoload": "upload", "uploda": "upload",
    "savve": "save", "saev": "save", "svae": "save",
    "lod": "load", "loadd": "load",
    "chekc": "check", "chek": "check", "checkk": "check",
    "verfiy": "verify", "veriy": "verify", "verfiy": "verify",
    "confimr": "confirm", "confim": "confirm", "conifrm": "confirm",
    "aprove": "approve", "aprrove": "approve", "apporve": "approve",
    "rejct": "reject", "rejcet": "reject", "rejetc": "reject",
    "cance": "cancel", "canel": "cancel", "cancell": "cancel",
    "minimze": "minimize", "minimze": "minimize", "minimiz": "minimize",
    "maximze": "maximize", "maximze": "maximize", "maximiz": "maximize",
    "focuss": "focus", "foucs": "focus", "focs": "focus",
    "swich": "switch", "swtich": "switch", "swtich": "switch",
    "scren": "screen", "screnn": "screen", "screeen": "screen",
    "screeshot": "screenshot", "screensht": "screenshot",
    "screeshot": "screenshot", "screeshott": "screenshot",
    "writre": "write", "wirte": "write", "wriet": "write",
    "creat": "create", "craete": "create", "cretae": "create",
    "mkae": "make", "maek": "make", "makee": "make",
    "shwo": "show", "sho": "show", "showw": "show",
    "hidde": "hide", "hid": "hide", "hdie": "hide",
    "stpo": "stop", "stp": "stop", "stopp": "stop",
    "statr": "start", "strat": "start", "startt": "start",
    "resetr": "reset", "resett": "reset", "reeset": "reset",
    "lockk": "lock", "lokc": "lock", "lcok": "lock",
    "unlcok": "unlock", "unlok": "unlock", "unlockk": "unlock",
    "emial": "email", "emial": "email", "emial": "email",
    "messsage": "message", "mesage": "message", "messag": "message",
    "attchment": "attachment", "atachment": "attachment",
    "foldr": "folder", "foldre": "folder", "foler": "folder",
    "documnet": "document", "documet": "document", "documnt": "document",
    "pictuer": "picture", "picutre": "picture", "pictre": "picture",
    "vidoe": "video", "vido": "video", "videeo": "video",
    "audoi": "audio", "audii": "audio", "audoo": "audio",
    "settngs": "settings", "setings": "settings", "settnigs": "settings",
    "prefernces": "preferences", "preferneces": "preferences",
    "passwrod": "password", "passwrd": "password", "passowrd": "password",
    "usernme": "username", "usernam": "username", "useranme": "username",
    "passkeyy": "passkey", "passke": "passkey", "pas key": "passkey",
    "notifcation": "notification", "notificaton": "notification",
    "calnder": "calendar", "calander": "calendar", "calenda": "calendar",
    "remnder": "reminder", "remider": "reminder", "reminde": "reminder",
    "weathr": "weather", "wheather": "weather", "wetaher": "weather",
    "newss": "news", "nwes": "news", "newss": "news",
    "mapp": "map", "mapss": "map", "mpas": "map",
    "phoo": "photo", "phoot": "photo", "photto": "photo",
    "gallry": "gallery", "galery": "gallery", "galllery": "gallery",
    "musci": "music", "msuic": "music", "muscic": "music",
    "plylist": "playlist", "playlsit": "playlist", "playlis": "playlist",
    "albumm": "album", "albm": "album", "albun": "album",
    "plyer": "player", "playr": "player", "playeer": "player",
    "dowload": "download", "donwload": "download", "dwonload": "download",
    "uploadd": "upload", "uplod": "upload", "upolad": "upload",
    "backupp": "backup", "backu": "backup", "bakcup": "backup",
    "restor": "restore", "restorre": "restore", "restoe": "restore",
    "syncc": "sync", "syn": "sync", "syncc": "sync",
    "shar": "share", "shre": "share", "shaer": "share",
    "prinr": "print", "prnt": "print", "prinnt": "print",
    "scann": "scan", "scna": "scan", "scannn": "scan",
    "analyz": "analyze", "analyz": "analyze", "analysee": "analyze",
    "optimiz": "optimize", "optimse": "optimize", "optimizee": "optimize",
    "secur": "secure", "secuer": "secure", "securr": "secure",
    "encryp": "encrypt", "encrpyt": "encrypt", "encryp": "encrypt",
    "decryp": "decrypt", "decrpyt": "decrypt", "decryp": "decrypt",
    "compess": "compress", "compres": "compress", "comress": "compress",
    "extrat": "extract", "extrac": "extract", "extratc": "extract",
    "archiev": "archive", "archve": "archive", "archiev": "archive",
    "deply": "deploy", "depoy": "deploy", "deplooy": "deploy",
    "releas": "release", "releaes": "release", "releas": "release",
    "publis": "publish", "publsh": "publish", "publissh": "publish",
    "buidl": "build", "bild": "build", "buld": "build",
    "compiel": "compile", "compiel": "compile", "compiel": "compile",
    "assembl": "assemble", "asemble": "assemble", "assmble": "assemble",
    "exectue": "execute", "exectue": "execute", "exectue": "execute",
    "perorm": "perform", "perfom": "perform", "perfoorm": "perform",
    "caryy": "carry", "cary": "carry", "carryy": "carry",
    "valiate": "validate", "valdate": "validate", "valdiate": "validate",
    "autenticate": "authenticate", "athenticate": "authenticate",
    "authoize": "authorize", "athorize": "authorize",
    "permitt": "permit", "permit": "permit", "permitt": "permit",
    "denny": "deny", "deni": "deny", "denny": "deny",
    "refusee": "refuse", "refusse": "refuse", "refues": "refuse",
    "allaw": "allow", "alow": "allow", "alllow": "allow",
    "granr": "grant", "grnt": "grant", "grannt": "grant",
    "revok": "revoke", "revokke": "revoke", "revoke": "revoke",
    "abotr": "abort", "abor": "abort", "abortt": "abort",
    "susped": "suspend", "suspned": "suspend", "susped": "suspend",
    "freez": "freeze", "freze": "freeze", "freez": "freeze",
    "contniue": "continue", "contniue": "continue", "contniue": "continue",
    "proceeed": "proceed", "proceeed": "proceed", "proceeed": "proceed",
    "skipp": "skip", "skp": "skip", "skipp": "skip",
    "jummp": "jump", "jmp": "jump", "jummp": "jump",
    "bypas": "bypass", "bypas": "bypass", "bypas": "bypass",
    "revers": "reverse", "revers": "reverse", "revers": "reverse",
    "reverr": "revert", "revert": "revert", "revert": "revert",
    "repat": "repeat", "reppeat": "repeat", "repaet": "repeat",
    "doagain": "do again", "doagain": "do again",
    "persit": "persist", "persit": "persist", "persit": "persist",
    "wrtie": "write", "wrtie": "write", "wrtie": "write",
    "imporrt": "import", "impor": "import", "imporrt": "import",
    "exporrt": "export", "expor": "export", "exporrt": "export",
    "outpu": "output", "outpu": "output", "outpu": "output",
    "inpu": "input", "inpu": "input", "inpu": "input",
    "examin": "examine", "examin": "examine", "examin": "examine",
    "inspec": "inspect", "inspec": "inspect", "inspec": "inspect",
    "diagnos": "diagnose", "diagnos": "diagnose", "diagnos": "diagnose",
    "troubleshoo": "troubleshoot", "troubleshoo": "troubleshoot",
    "identiy": "identify", "identfy": "identify", "identiy": "identify",
    "discove": "discover", "discove": "discover", "discove": "discover",
    "recogniz": "recognize", "recogniz": "recognize", "recogniz": "recognize",
    "categoriz": "categorize", "categoriz": "categorize",
    "labbel": "label", "labbel": "label", "labbel": "label",
    "maark": "mark", "maark": "mark", "maark": "mark",
    "jooin": "join", "jooin": "join", "jooin": "join",
    "linnk": "link", "linnk": "link", "linnk": "link",
    "attac": "attach", "attac": "attach", "attac": "attach",
    "detac": "detach", "detac": "detach", "detac": "detach",
    "sepaarate": "separate", "sepaarate": "separate",
    "addd": "add", "addd": "add", "addd": "add",
    "puut": "put", "puut": "put", "puut": "put",
    "takee": "take", "takee": "take", "takee": "take",
    "geet": "get", "geet": "get", "geet": "get",
    "fetche": "fetch", "fetche": "fetch", "fetche": "fetch",
    "retrieev": "retrieve", "retrieev": "retrieve",
    "pull": "pull", "pull": "pull", "pull": "pull",
    "graab": "grab", "graab": "grab", "graab": "grab",
    "pus": "push", "pus": "push", "pus": "push",
    "tranmit": "transmit", "tranmit": "transmit",
    "dispatc": "dispatch", "dispatc": "dispatch",
    "deliveer": "deliver", "deliveer": "deliver",
    "submitt": "submit", "submitt": "submit",
    "fireoff": "fire off", "fireoff": "fire off",
    "transfeer": "transfer", "transfeer": "transfer",
    "relocat": "relocate", "relocat": "relocate",
    "shiift": "shift", "shiift": "shift",
    "duplicat": "duplicate", "duplicat": "duplicate",
    "cloone": "clone", "cloone": "clone",
    "replicat": "replicate", "replicat": "replicate",
    "relabeel": "relabel", "relabeel": "relabel",
    "ziip": "zip", "ziip": "zip",
    "arrchive": "archive", "arrchive": "arrchive",
    "paack": "pack", "paack": "pack",
    "unziip": "unzip", "unziip": "unzip",
    "unpaack": "unpack", "unpaack": "unpack",
    "decompres": "decompress", "decompres": "decompress",
    "substitut": "substitute", "substitut": "substitute",
    "swaap": "swap", "swaap": "swap",
    "exchaange": "exchange", "exchaange": "exchange",
    "ordr": "order", "ordr": "order",
    "arrang": "arrange", "arrang": "arrange",
    "ranck": "rank", "ranck": "rank",
    "sieeve": "sieve", "sieeve": "sieve",
    "straain": "strain", "straain": "strain",
    "narroow": "narrow", "narroow": "narrow",
    "tally": "tally", "tally": "tally",
    "enumerat": "enumerate", "enumerat": "enumerate",
    "numbber": "number", "numbber": "number",
    "veriy": "verify", "veriy": "verify",
    "confim": "confirm", "confim": "confirm",
    "autenticate": "authenticate", "autenticate": "authenticate",
    "traace": "trace", "traace": "trace",
    "traack": "track", "traack": "track",
    "folloow": "follow", "folloow": "follow",
    "directt": "direct", "directt": "direct",
    "guiide": "guide", "guiide": "guide",
    "passon": "pass on", "passon": "pass on",
    "relaay": "relay", "relaay": "relay",
    "retunr": "return", "retunr": "return",
    "forwarrd": "forward", "forwarrd": "forward",
    "skipah": "skip ahead", "skipah": "skip ahead",
    "prio": "prior", "prio": "prior",
    "initi": "initial", "initi": "initial",
    "primay": "primary", "primay": "primary",
    "finall": "final", "finall": "final",
    "ultimat": "ultimate", "ultimat": "ultimate",
    "peakk": "peak", "peakk": "peak",
    "highe": "highest", "highe": "highest",
    "lowe": "lowest", "lowe": "lowest",
    "baase": "base", "baase": "base",
    "weest": "west", "weest": "west",
    "eaast": "east", "eaast": "east",
    "nort": "north", "nort": "north",
    "sout": "south", "sout": "south",
    "abov": "above", "abov": "above",
    "belo": "below", "belo": "below",
    "middl": "middle", "middl": "middle",
    "centere": "centered", "centere": "centered",
    "immediat": "immediately", "immediat": "immediately",
    "instantl": "instantly", "instantl": "instantly",
    "afterward": "afterwards", "afterward": "afterwards",
    "subsequentl": "subsequently", "subsequentl": "subsequently",
    "shortl": "shortly", "shortl": "shortly",
    "quickl": "quickly", "quickl": "quickly",
    "foreve": "forever", "foreve": "forever",
    "constantl": "constantly", "constantl": "constantly",
    "noteve": "not ever", "noteve": "not ever",
    "thiis": "this", "thiis": "this",
    "curren": "current", "curren": "current",
    "presen": "present", "presen": "present",
    "specifc": "specific", "specifc": "specific",
    "particul": "particular", "particul": "particular",
    "persone": "personal", "persone": "personal",
    "belongin": "belonging", "belongin": "belonging",
    "sharee": "shared", "sharee": "shared",
    "commo": "common", "commo": "common",
    "belongin": "belonging", "belongin": "belonging",
}


def correct_spelling(text: str) -> str:
    """Correct common spelling mistakes in user text.

    Example:
        "opne chrom" -> "open chrome"
        "lauch firefoxx" -> "launch firefox"
    """
    if not text:
        return text
    out = text
    # Sort by length (longest first) so multi-word typos match first
    for typo in sorted(SPELLING_CORRECTIONS.keys(), key=len, reverse=True):
        pattern = r"\b" + re.escape(typo) + r"\b"
        out = re.sub(pattern, SPELLING_CORRECTIONS[typo], out, flags=re.IGNORECASE)
    return out


# ---------------------------------------------------------------------------
# 6.4 BROWSER PRIORITY - detect installed browser, reuse existing
# ---------------------------------------------------------------------------
BROWSER_PRIORITY: List[str] = [
    "chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc",
    "librewolf",
]

BROWSER_PROCESS_NAMES: Dict[str, List[str]] = {
    "chrome": ["chrome.exe", "google chrome"],
    "msedge": ["msedge.exe", "microsoft edge"],
    "firefox": ["firefox.exe"],
    "brave": ["brave.exe"],
    "opera": ["opera.exe", "opera_gx.exe"],
    "vivaldi": ["vivaldi.exe"],
    "arc": ["arc.exe"],
    "librewolf": ["librewolf.exe"],
}


def detect_browser_priority() -> List[str]:
    """Return the list of browsers in priority order.

    In a real implementation, this would check which browsers are installed
    on the system. For now, we return the default priority list.
    """
    return list(BROWSER_PRIORITY)


# ---------------------------------------------------------------------------
# 6.5 WAIT STRATEGIES - dynamic waits, never fixed delays
# ---------------------------------------------------------------------------
WAIT_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "dom_ready": {
        "description": "Wait until DOM is fully loaded and parsed",
        "timeout_ms": 30000,
        "check": "document.readyState === 'complete'",
        "applies_to": ["browser_open", "browser_navigate", "browser_search"],
    },
    "visual_stability": {
        "description": "Wait until visual elements stop moving/changing",
        "timeout_ms": 10000,
        "check": "no layout shifts in last 500ms",
        "applies_to": ["browser_open", "browser_navigate", "screen_click"],
    },
    "spinner_gone": {
        "description": "Wait until loading spinner/indicator disappears",
        "timeout_ms": 30000,
        "check": "no spinner/loader visible",
        "applies_to": ["browser_open", "browser_navigate", "browser_search",
                        "screen_click"],
    },
    "window_idle": {
        "description": "Wait until window is idle (no animations, no updates)",
        "timeout_ms": 5000,
        "check": "window not animating, no pending updates",
        "applies_to": ["app_open", "window_focus", "window_switch"],
    },
    "animation_complete": {
        "description": "Wait until CSS/JS animations complete",
        "timeout_ms": 5000,
        "check": "no running animations",
        "applies_to": ["screen_click", "window_minimize", "window_maximize"],
    },
    "network_idle": {
        "description": "Wait until network is idle (no pending requests)",
        "timeout_ms": 30000,
        "check": "no pending network requests for 500ms",
        "applies_to": ["browser_open", "browser_navigate", "browser_search",
                        "browser_download"],
    },
}


def get_wait_strategy(intent: str) -> List[str]:
    """Return the list of wait strategies that apply to a given intent."""
    strategies: List[str] = []
    for name, info in WAIT_STRATEGIES.items():
        if intent in info.get("applies_to", []):
            strategies.append(name)
    return strategies


# ---------------------------------------------------------------------------
# 6.6 VISION TARGETS - UI elements that vision can detect
# ---------------------------------------------------------------------------
VISION_TARGETS: List[str] = [
    "button", "icon", "checkbox", "radio", "tab", "window", "menu",
    "image", "card", "avatar", "logo", "toolbar", "scrollbar",
    "dropdown", "input", "link", "text", "label", "form", "modal",
    "dialog", "popup", "notification", "badge", "chip", "tag",
    "slider", "switch", "toggle", "progress", "spinner", "loader",
    "tooltip", "breadcrumb", "pagination", "accordion", "carousel",
    "sidebar", "header", "footer", "navbar", "searchbar", "addressbar",
]


def is_vision_target(text: str) -> Optional[str]:
    """Check if text refers to a vision-detectable UI element."""
    text_lower = text.lower()
    for target in VISION_TARGETS:
        if re.search(r"\b" + re.escape(target) + r"\b", text_lower):
            return target
    return None


# ---------------------------------------------------------------------------
# 6.7 ACCESSIBILITY FALLBACK CHAIN
# ---------------------------------------------------------------------------
ACCESSIBILITY_FALLBACK_CHAIN: List[str] = [
    "ocr",            # First: OCR text matching
    "accessibility",  # Second: Accessibility tree (UIA)
    "vision",         # Third: Vision/UI detection
    "template",       # Fourth: Template matching
    "object_detection",  # Fifth: Object detection (last resort)
]


def get_accessibility_fallback(level: int = 0) -> str:
    """Get the next fallback strategy at the given level."""
    if 0 <= level < len(ACCESSIBILITY_FALLBACK_CHAIN):
        return ACCESSIBILITY_FALLBACK_CHAIN[level]
    return ACCESSIBILITY_FALLBACK_CHAIN[-1]


# ---------------------------------------------------------------------------
# 6.8 RECOVERY STRATEGIES - intelligent retry
# ---------------------------------------------------------------------------
RECOVERY_STRATEGIES: List[Dict[str, Any]] = [
    {
        "name": "retry_ocr",
        "description": "Retry OCR with different parameters",
        "applies_to": ["screen_click", "ocr_screen", "ocr_region"],
        "max_attempts": 3,
    },
    {
        "name": "retry_vision",
        "description": "Retry vision detection with different model",
        "applies_to": ["screen_click", "vision_detect"],
        "max_attempts": 3,
    },
    {
        "name": "retry_accessibility",
        "description": "Retry accessibility tree query",
        "applies_to": ["screen_click", "screen_scan"],
        "max_attempts": 3,
    },
    {
        "name": "scroll",
        "description": "Scroll to find the target element",
        "applies_to": ["screen_click", "browser_search"],
        "max_attempts": 3,
    },
    {
        "name": "zoom",
        "description": "Zoom in/out to better see the target",
        "applies_to": ["screen_click", "ocr_screen"],
        "max_attempts": 2,
    },
    {
        "name": "refocus_window",
        "description": "Refocus the window before retrying",
        "applies_to": ["screen_click", "screen_scan", "ocr_screen"],
        "max_attempts": 2,
    },
    {
        "name": "alternative_browser",
        "description": "Try a different browser",
        "applies_to": ["browser_open", "browser_navigate", "browser_search"],
        "max_attempts": 3,
    },
    {
        "name": "alternative_click_point",
        "description": "Try a different click point on the same element",
        "applies_to": ["screen_click"],
        "max_attempts": 3,
    },
]


def get_recovery_strategies(intent: str) -> List[str]:
    """Return the list of recovery strategies that apply to a given intent."""
    strategies: List[str] = []
    for s in RECOVERY_STRATEGIES:
        if intent in s.get("applies_to", []):
            strategies.append(s["name"])
    return strategies


# ---------------------------------------------------------------------------
# 6.9 TASK CONTEXT - maintain context across multi-step tasks
# ---------------------------------------------------------------------------
class TaskContext:
    """Maintains context across multi-step tasks.

    Example:
        User: "Open Gmail"
        User: "Compose email"
        User: "Type Hello"
        User: "Send"
        -> All steps know we're in Gmail compose flow
    """

    def __init__(self) -> None:
        self.app: Optional[str] = None
        self.window: Optional[str] = None
        self.url: Optional[str] = None
        self.workflow: Optional[str] = None
        self.last_action: Optional[str] = None
        self.last_target: Optional[str] = None
        self.history: List[Dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.history.append(kwargs)

    def is_in_workflow(self, workflow: str) -> bool:
        return self.workflow == workflow

    def get_active_app(self) -> Optional[str]:
        return self.app

    def get_active_url(self) -> Optional[str]:
        return self.url

    def clear(self) -> None:
        self.app = None
        self.window = None
        self.url = None
        self.workflow = None
        self.last_action = None
        self.last_target = None
        self.history = []


# Global task context (per-session)
_global_task_context: Optional[TaskContext] = None


def get_task_context() -> TaskContext:
    """Get or create the global task context."""
    global _global_task_context
    if _global_task_context is None:
        _global_task_context = TaskContext()
    return _global_task_context


def reset_task_context() -> None:
    """Reset the global task context."""
    global _global_task_context
    _global_task_context = TaskContext()


# ---------------------------------------------------------------------------
# 6.10 CONFIDENCE + RISK SCORES
# ---------------------------------------------------------------------------
def compute_confidence(text: str, intent: str) -> float:
    """Compute confidence score (0.0-1.0) for an intent classification.

    Higher confidence means the intent is more certain.
    """
    if not text or not intent:
        return 0.0
    text_lower = text.lower()
    # Base confidence
    confidence = 0.5
    # Boost if exact match in memory
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text_lower)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Boost if text contains strong intent keywords
    strong_keywords = {
        "open_app": ["open", "launch", "start", "run"],
        "close_app": ["close", "quit", "exit", "kill"],
        "search_web": ["search", "google", "find"],
        "browser_open": ["browser", "chrome", "edge", "firefox"],
        "delete_files": ["delete", "remove", "erase"],
        "system_status": ["status", "health", "check"],
    }
    keywords = strong_keywords.get(intent, [])
    if keywords:
        matches = sum(1 for kw in keywords if re.search(r"\b" + kw + r"\b", text_lower))
        confidence += min(0.3, matches * 0.1)
    # Reduce confidence for very short or very long inputs
    word_count = len(text_lower.split())
    if word_count < 2:
        confidence -= 0.1
    elif word_count > 20:
        confidence -= 0.1
    return max(0.0, min(1.0, confidence))


def compute_risk(intent: str) -> int:
    """Compute risk score (0-5) for an intent.

    Higher risk means more dangerous.
    """
    risk_map = {
        "system_status": 0,
        "disk_usage": 0,
        "ram_usage": 0,
        "list_files": 0,
        "file_read": 0,
        "screen_scan": 0,
        "ocr_screen": 0,
        "vision_detect": 0,
        "memory_recall": 0,
        "open_app": 1,
        "open_website": 1,
        "browser_open": 1,
        "browser_close": 1,
        "browser_session": 1,
        "search_web": 1,
        "window_focus": 1,
        "window_minimize": 1,
        "window_maximize": 1,
        "window_switch": 1,
        "window_arrange": 1,
        "window_screenshot": 1,
        "keep_awake": 1,
        "mouse_jiggle": 1,
        "media_screenshot": 1,
        "media_screen_record": 1,
        "media_camera": 1,
        "take_camera_photo": 1,
        "clipboard_copy": 1,
        "clipboard_paste": 1,
        "clipboard_read": 1,
        "doc_pdf_read": 1,
        "doc_word_read": 1,
        "doc_excel_read": 1,
        "doc_csv_read": 1,
        "file_write": 2,
        "file_rename": 2,
        "file_move": 2,
        "file_copy": 2,
        "file_compress": 2,
        "file_extract": 2,
        "file_search": 2,
        "file_backup": 2,
        "app_install": 2,
        "app_update": 2,
        "app_restart": 2,
        "network_download": 2,
        "network_upload": 2,
        "network_wifi": 2,
        "email_compose": 2,
        "email_search": 2,
        "research_collect": 2,
        "research_summarize": 2,
        "memory_remember": 2,
        "memory_forget": 2,
        "task_create": 2,
        "task_run": 2,
        "task_cancel": 2,
        "dev_git": 2,
        "dev_build": 2,
        "dev_test": 2,
        "dev_run": 2,
        "dev_docker": 2,
        "terminal_run": 3,
        "terminal_powershell": 3,
        "terminal_cmd": 3,
        "run_command": 3,
        "download_file": 3,
        "login": 3,
        "send_email": 3,
        "email_send": 3,
        "delete_files": 4,
        "app_uninstall": 4,
        "shutdown_pc": 4,
        "restart_pc": 4,
        "lock_pc": 4,
        "logout": 4,
        "file_delete_permanent": 5,
    }
    return risk_map.get(intent, 1)


# ---------------------------------------------------------------------------
# 6.11 AUTONOMY - infer obvious steps
# ---------------------------------------------------------------------------
AUTONOMY_INFERENCE: Dict[str, List[str]] = {
    "open_website": ["detect_browser", "launch_browser", "focus_browser",
                     "navigate_url", "wait_dom_ready", "verify_page"],
    "browser_open": ["detect_browser", "launch_browser", "focus_browser",
                     "wait_window_idle"],
    "browser_search": ["detect_browser", "launch_browser", "focus_browser",
                       "navigate_search_engine", "type_query", "submit",
                       "wait_dom_ready", "verify_results"],
    "open_app": ["detect_app", "launch_app", "focus_window",
                 "wait_window_idle"],
    "login": ["open_browser", "navigate_site", "detect_login_form",
              "request_vault_unlock", "fill_credentials", "submit",
              "verify_login"],
    "send_email": ["open_email_client", "compose_email", "fill_recipient",
                   "fill_subject", "fill_body", "send", "verify_sent"],
    "delete_files": ["scan_files", "count_files", "request_approval",
                     "quarantine_files", "verify_quarantine"],
    "search_web": ["detect_browser", "launch_browser", "focus_browser",
                   "navigate_search_engine", "type_query", "submit",
                   "wait_dom_ready", "verify_results"],
    "download_file": ["detect_browser", "navigate_url", "click_download",
                      "wait_download", "verify_file"],
    "screen_click": ["scan_screen", "match_target", "compute_click_point",
                     "click", "verify_action"],
    "ocr_screen": ["capture_screen", "run_ocr", "extract_text",
                   "verify_text"],
    "vision_detect": ["capture_screen", "run_vision", "detect_target",
                      "verify_detection"],
    "file_read": ["check_path", "open_file", "read_content",
                  "verify_content"],
    "file_write": ["check_path", "create_file", "write_content",
                   "verify_write"],
    "shutdown_pc": ["request_approval", "save_work", "close_apps",
                    "shutdown", "verify_shutdown"],
    "restart_pc": ["request_approval", "save_work", "close_apps",
                   "restart", "verify_restart"],
    "lock_pc": ["save_work", "lock_screen", "verify_lock"],
    "media_camera": ["launch_camera", "wait_preview", "verify_preview"],
    "take_camera_photo": ["launch_camera", "wait_preview", "verify_preview",
                          "capture_photo", "verify_saved"],
}


def infer_autonomous_steps(intent: str) -> List[str]:
    """Infer the obvious steps needed to complete an intent."""
    return AUTONOMY_INFERENCE.get(intent, [])


# ---------------------------------------------------------------------------
# 6.12 FAILURE POLICY - explain why, suggest alternatives
# ---------------------------------------------------------------------------
def explain_failure(intent: str, reason: str) -> Dict[str, Any]:
    """Generate a failure explanation with alternatives.

    Returns:
        {
            "explanation": "Why this failed",
            "alternatives": ["Closest achievable workflow 1", ...],
            "suggestion": "What the user should try"
        }
    """
    alternatives_map = {
        "open_app": [
            "Try specifying the full app name (e.g., 'Google Chrome')",
            "Check if the app is installed",
            "Try launching from Start menu",
        ],
        "open_website": [
            "Check your internet connection",
            "Verify the URL is correct",
            "Try a different browser",
        ],
        "delete_files": [
            "Use 'move to quarantine' instead of permanent delete",
            "Specify the exact path",
            "Check file permissions",
        ],
        "login": [
            "Unlock the password vault first",
            "Check if the site supports passkey login",
            "Verify your credentials",
        ],
        "search_web": [
            "Try a different search engine",
            "Simplify your query",
            "Check your internet connection",
        ],
        "shutdown_pc": [
            "Save your work first",
            "Close all open applications",
            "Use 'restart' instead",
        ],
        "browser_open": [
            "Try a different browser",
            "Check if the browser is installed",
            "Use the system default browser",
        ],
        "screen_click": [
            "Try clicking by coordinates",
            "Use keyboard shortcut instead",
            "Scroll to find the element",
        ],
    }
    return {
        "explanation": f"Could not {intent}: {reason}",
        "alternatives": alternatives_map.get(intent, [
            "Try rephrasing your command",
            "Check if the required tool is available",
            "Contact support if the issue persists",
        ]),
        "suggestion": "Please try one of the alternatives above.",
    }


# ---------------------------------------------------------------------------
# 6.13 MODEL REQUIREMENTS - only invoke required models
# ---------------------------------------------------------------------------
MODEL_REQUIREMENTS: Dict[str, List[str]] = {
    "screen_click": ["ocr", "vision", "ui_detector"],
    "ocr_screen": ["ocr"],
    "ocr_region": ["ocr"],
    "vision_detect": ["vision", "ui_detector"],
    "open_app": ["app_detector", "window_manager"],
    "browser_open": ["browser_automation"],
    "open_website": ["browser_automation"],
    "browser_search": ["browser_automation"],
    "browser_navigate": ["browser_automation"],
    "file_read": ["filesystem"],
    "file_write": ["filesystem"],
    "delete_files": ["filesystem"],
    "list_files": ["filesystem"],
    "system_status": ["system_monitor"],
    "disk_usage": ["system_monitor"],
    "ram_usage": ["system_monitor"],
    "login": ["browser_automation", "vault", "ocr", "vision"],
    "send_email": ["email_client", "ocr"],
    "download_file": ["browser_automation", "filesystem"],
    "shutdown_pc": ["system_control"],
    "restart_pc": ["system_control"],
    "lock_pc": ["system_control"],
    "media_screenshot": ["screen_capture"],
    "media_screen_record": ["screen_capture"],
    "media_camera": ["system_control"],
    "take_camera_photo": ["camera", "system_control"],
    "doc_pdf_read": ["pdf_reader", "ocr"],
    "doc_word_read": ["doc_reader"],
    "doc_excel_read": ["excel_reader"],
    "doc_csv_read": ["csv_reader"],
    "email_compose": ["email_client"],
    "email_send": ["email_client"],
    "email_search": ["email_client", "ocr"],
    "clipboard_copy": ["clipboard"],
    "clipboard_paste": ["clipboard"],
    "clipboard_read": ["clipboard"],
    "network_ping": ["network"],
    "network_download": ["network", "filesystem"],
    "network_upload": ["network", "filesystem"],
    "network_wifi": ["network"],
    "terminal_run": ["terminal"],
    "terminal_powershell": ["terminal"],
    "terminal_cmd": ["terminal"],
    "dev_git": ["terminal", "filesystem"],
    "dev_build": ["terminal", "filesystem"],
    "dev_test": ["terminal"],
    "dev_run": ["terminal"],
    "dev_docker": ["terminal"],
    "memory_remember": ["memory"],
    "memory_recall": ["memory"],
    "memory_forget": ["memory"],
    "task_create": ["task_engine"],
    "task_run": ["task_engine"],
    "task_cancel": ["task_engine"],
    "research_collect": ["browser_automation", "ocr", "llm"],
    "research_summarize": ["llm"],
    "keep_awake": ["system_control"],
    "mouse_jiggle": ["system_control"],
    "window_focus": ["window_manager"],
    "window_minimize": ["window_manager"],
    "window_maximize": ["window_manager"],
    "window_switch": ["window_manager"],
    "window_close": ["window_manager"],
    "window_arrange": ["window_manager"],
    "window_screenshot": ["screen_capture", "window_manager"],
    "app_install": ["system_control", "filesystem"],
    "app_uninstall": ["system_control", "filesystem"],
    "app_update": ["system_control"],
    "app_restart": ["system_control"],
    "browser_session": ["system_control", "window_manager"],
    "browser_close": ["window_manager"],
    "close_app": ["window_manager"],
    "close_all_apps": ["window_manager"],
    "open_settings": ["system_control"],
    "file_rename": ["filesystem"],
    "file_move": ["filesystem"],
    "file_copy": ["filesystem"],
    "file_compress": ["filesystem"],
    "file_extract": ["filesystem"],
    "file_search": ["filesystem"],
    "file_backup": ["filesystem"],
    "screen_scan": ["ocr", "vision", "ui_detector"],
}


def get_required_models(intent: str) -> List[str]:
    """Return the list of models required for a given intent."""
    return MODEL_REQUIREMENTS.get(intent, [])


# ---------------------------------------------------------------------------
# 6.14 VERIFICATION STEPS - every action requires verification
# ---------------------------------------------------------------------------
VERIFICATION_STEPS: Dict[str, List[str]] = {
    "open_app": ["verify_window_visible", "verify_window_title",
                 "verify_app_responsive"],
    "browser_open": ["verify_window_visible", "verify_browser_ready",
                     "verify_url_loaded"],
    "browser_search": ["verify_search_results", "verify_results_count"],
    "open_website": ["verify_url_loaded", "verify_page_title",
                     "verify_logo_visible"],
    "browser_navigate": ["verify_url_loaded", "verify_page_title"],
    "screen_click": ["verify_dialog_appears", "verify_button_disappears",
                     "verify_new_screen_loaded"],
    "delete_files": ["verify_files_quarantined", "verify_count_matches"],
    "file_read": ["verify_content_read", "verify_file_exists"],
    "file_write": ["verify_file_created", "verify_content_written"],
    "login": ["verify_login_success", "verify_dashboard_loaded"],
    "send_email": ["verify_email_sent", "verify_recipient_received"],
    "download_file": ["verify_file_downloaded", "verify_file_size"],
    "shutdown_pc": ["verify_shutdown_complete"],
    "restart_pc": ["verify_restart_complete", "verify_system_responsive"],
    "lock_pc": ["verify_screen_locked"],
    "media_screenshot": ["verify_screenshot_saved"],
    "media_camera": ["verify_preview_visible"],
    "take_camera_photo": ["verify_preview_visible", "verify_photo_saved"],
    "ocr_screen": ["verify_text_extracted", "verify_confidence_score"],
    "vision_detect": ["verify_target_detected", "verify_confidence_score"],
    "system_status": ["verify_status_returned"],
    "list_files": ["verify_files_listed", "verify_count_matches"],
}


def get_verification_steps(intent: str) -> List[str]:
    """Return the list of verification steps for a given intent."""
    return VERIFICATION_STEPS.get(intent, ["verify_action_completed"])


# ---------------------------------------------------------------------------
# 6.15 SEMANTIC OCR MATCHES - match semantically, not exactly
# ---------------------------------------------------------------------------
SEMANTIC_OCR_MATCHES: Dict[str, List[str]] = {
    "login": ["sign in", "log in", "signin", "login", "authenticate",
              "continue with email", "continue with google",
              "continue with microsoft", "continue with apple",
              "get started", "join"],
    "logout": ["sign out", "log out", "logout", "exit", "disconnect"],
    "continue": ["next", "proceed", "continue", "forward", "go ahead",
                 "ok", "okay", "yes", "confirm", "submit", "send",
                 "done", "finish", "complete"],
    "cancel": ["cancel", "abort", "stop", "no", "back", "discard",
               "never mind", "nevermind"],
    "close": ["close", "dismiss", "x", "exit", "hide", "minimize"],
    "submit": ["submit", "send", "post", "publish", "save", "apply",
               "confirm", "ok", "okay", "done"],
    "save": ["save", "store", "keep", "remember", "apply", "ok"],
    "delete": ["delete", "remove", "trash", "erase", "discard", "drop"],
    "edit": ["edit", "modify", "change", "update", "revise"],
    "create": ["create", "new", "add", "make", "compose", "write"],
    "search": ["search", "find", "look", "query", "go"],
    "settings": ["settings", "preferences", "options", "config",
                 "configuration", "setup"],
    "help": ["help", "support", "assist", "?", "info", "information"],
    "back": ["back", "previous", "return", "undo", "<"],
    "next": ["next", "forward", "continue", ">", "skip"],
    "yes": ["yes", "ok", "okay", "confirm", "accept", "approve", "agree",
            "sure", "yeah", "yep"],
    "no": ["no", "nope", "cancel", "reject", "deny", "refuse", "disagree"],
    "menu": ["menu", "hamburger", "options", "more", "..."],
    "profile": ["profile", "account", "user", "me", "avatar"],
    "home": ["home", "main", "start", "dashboard", "overview"],
    "notifications": ["notifications", "alerts", "bell", "messages"],
    "messages": ["messages", "chat", "inbox", "mail", "email"],
    "send_message": ["send", "submit", "post", "share", "fire"],
    "attach": ["attach", "upload", "add file", "paperclip"],
    "emoji": ["emoji", "smiley", "face", "表情"],
    "gif": ["gif", "sticker", "animated"],
    "voice": ["voice", "mic", "microphone", "record"],
    "video": ["video", "camera", "record", "film"],
    "call": ["call", "phone", "ring", "dial"],
    "end_call": ["end call", "hang up", "disconnect", "stop"],
    "accept_call": ["accept", "answer", "pick up", "decline"],
    "decline_call": ["decline", "reject", "ignore", "busy"],
    "play": ["play", "start", "resume", "go"],
    "pause": ["pause", "stop", "halt", "wait"],
    "stop": ["stop", "halt", "end", "finish"],
    "next_track": ["next", "skip", "forward", ">>"],
    "prev_track": ["previous", "back", "rewind", "<<"],
    "volume_up": ["volume up", "louder", "+", "increase volume"],
    "volume_down": ["volume down", "quieter", "-", "decrease volume"],
    "mute": ["mute", "silent", "quiet", "no sound"],
    "unmute": ["unmute", "sound on", "audio on"],
    "fullscreen": ["fullscreen", "maximize", "expand", "full"],
    "exit_fullscreen": ["exit fullscreen", "minimize", "shrink"],
    "refresh": ["refresh", "reload", "update", "f5"],
    "bookmark": ["bookmark", "star", "favorite", "save"],
    "share": ["share", "send", "forward", "export"],
    "print": ["print", "printer", "output"],
    "download": ["download", "save", "get", "fetch"],
    "upload": ["upload", "send", "push", "submit"],
    "copy": ["copy", "duplicate", "clone"],
    "paste": ["paste", "insert", "put"],
    "cut": ["cut", "remove", "extract"],
    "undo": ["undo", "reverse", "revert", "back"],
    "redo": ["redo", "repeat", "forward", "again"],
    "select_all": ["select all", "all", "everything", "ctrl+a"],
    "find": ["find", "search", "locate", "look"],
    "replace": ["replace", "substitute", "swap", "change"],
    "zoom_in": ["zoom in", "enlarge", "bigger", "+"],
    "zoom_out": ["zoom out", "shrink", "smaller", "-"],
    "rotate": ["rotate", "turn", "spin"],
    "crop": ["crop", "trim", "cut"],
    "filter": ["filter", "sort", "narrow", "refine"],
    "sort": ["sort", "order", "arrange", "rank"],
    "view": ["view", "see", "show", "display"],
    "list_view": ["list", "rows", "detailed"],
    "grid_view": ["grid", "tiles", "cards"],
    "dark_mode": ["dark", "night", "black"],
    "light_mode": ["light", "day", "white", "bright"],
    "language": ["language", "locale", "region", "translate"],
    "logout_button": ["logout", "sign out", "log out", "exit"],
    "upgrade": ["upgrade", "premium", "pro", "subscribe", "buy"],
    "trial": ["trial", "free", "demo", "try"],
    "buy": ["buy", "purchase", "order", "checkout", "pay"],
    "add_to_cart": ["add to cart", "buy", "purchase", "add"],
    "checkout": ["checkout", "pay", "buy", "purchase", "order"],
    "wishlist": ["wishlist", "favorite", "save", "bookmark"],
    "review": ["review", "rate", "comment", "feedback"],
    "rating": ["rating", "stars", "score", "rate"],
    "comment": ["comment", "reply", "respond", "feedback"],
    "reply": ["reply", "respond", "answer", "comment"],
    "like": ["like", "love", "heart", "thumbs up", "+1"],
    "dislike": ["dislike", "hate", "thumbs down", "-1"],
    "follow": ["follow", "subscribe", "join"],
    "unfollow": ["unfollow", "unsubscribe", "leave"],
    "block": ["block", "ban", "restrict", "mute"],
    "report": ["report", "flag", "spam", "abuse"],
    "delete_account": ["delete account", "remove account", "close account"],
    "privacy": ["privacy", "private", "secure", "hidden"],
    "terms": ["terms", "conditions", "tos", "agreement"],
    "about": ["about", "info", "information", "details"],
    "contact": ["contact", "support", "help", "reach"],
    "feedback": ["feedback", "review", "comment", "suggestion"],
    "bug_report": ["bug", "issue", "problem", "error", "report"],
    "feature_request": ["feature", "request", "suggestion", "idea"],
    "version": ["version", "release", "update", "changelog"],
    "changelog": ["changelog", "history", "updates", "what's new"],
    "documentation": ["docs", "documentation", "guide", "manual", "help"],
    "api": ["api", "developer", "sdk", "integration"],
    "developer": ["developer", "dev", "code", "programming"],
    "blog": ["blog", "news", "articles", "posts"],
    "careers": ["careers", "jobs", "hiring", "work"],
    "press": ["press", "media", "news", "announcements"],
    "legal": ["legal", "terms", "privacy", "policy"],
    "status": ["status", "health", "uptime", "availability"],
    "pricing": ["pricing", "plans", "cost", "price"],
    "enterprise": ["enterprise", "business", "corporate", "team"],
    "support": ["support", "help", "contact", "assistance"],
    "community": ["community", "forum", "discussion", "group"],
    "events": ["events", "calendar", "schedule", "meetups"],
    "partners": ["partners", "affiliates", "resellers"],
    "investors": ["investors", "financials", "stock"],
    "security": ["security", "secure", "protection", "safety"],
    "compliance": ["compliance", "regulations", "standards"],
    "accessibility": ["accessibility", "a11y", "disability", "inclusive"],
}


def semantic_ocr_match(target: str, detected_text: str) -> float:
    """Compute semantic similarity between target and detected text.

    Returns a score from 0.0 to 1.0.
    """
    if not target or not detected_text:
        return 0.0
    target_lower = target.lower().strip()
    detected_lower = detected_text.lower().strip()
    # Exact match
    if target_lower == detected_lower:
        return 1.0
    # Check semantic matches
    for canonical, variants in SEMANTIC_OCR_MATCHES.items():
        if target_lower in variants and detected_lower in variants:
            return 0.95
        if target_lower == canonical and detected_lower in variants:
            return 0.95
        if detected_lower == canonical and target_lower in variants:
            return 0.95
    # Token overlap
    target_tokens = set(re.findall(r"[a-z]+", target_lower))
    detected_tokens = set(re.findall(r"[a-z]+", detected_lower))
    if not target_tokens or not detected_tokens:
        return 0.0
    overlap = len(target_tokens & detected_tokens)
    union = len(target_tokens | detected_tokens)
    jaccard = overlap / union if union else 0.0
    # Sequence similarity
    seq_ratio = difflib.SequenceMatcher(None, target_lower, detected_lower).ratio()
    return max(jaccard, seq_ratio * 0.9)


# ---------------------------------------------------------------------------
# 6.16 COGNITIVE PIPELINE - the main cognitive processing pipeline
# ---------------------------------------------------------------------------
def cognitive_pipeline(text: str) -> Dict[str, Any]:
    """Run the full cognitive pipeline on user text.

    Returns:
        {
            "original": "raw user text",
            "spelling_corrected": "text after spelling correction",
            "alias_resolved": "text after alias resolution",
            "synonym_expanded": "text after synonym expansion",
            "canonical_actions": [list of (canonical, phrase) tuples],
            "normalized": "fully normalized text",
        }
    """
    if not text:
        return {
            "original": "",
            "spelling_corrected": "",
            "alias_resolved": "",
            "synonym_expanded": "",
            "canonical_actions": [],
            "normalized": "",
        }
    # Step 1: Spelling correction
    spelling_corrected = correct_spelling(text)
    # Step 2: Alias resolution
    alias_resolved = resolve_user_alias(spelling_corrected)
    # Step 3: Synonym expansion
    synonym_expanded = _expand_synonyms(alias_resolved)
    # Step 4: Canonical action extraction
    canonical_actions = normalize_to_canonical(alias_resolved)
    return {
        "original": text,
        "spelling_corrected": spelling_corrected,
        "alias_resolved": alias_resolved,
        "synonym_expanded": synonym_expanded,
        "canonical_actions": canonical_actions,
        "normalized": alias_resolved,
    }


# ===========================================================================
# SECTION 7: PLANNER CLASS
# ===========================================================================
class Planner:
    """Command planner with full system awareness."""

    SITE_ALIASES = {
        "amazon": "https://www.amazon.com",
        "bing": "https://www.bing.com",
        "chatgpt": "https://chatgpt.com",
        "edge": "https://www.microsoft.com/edge",
        "facebook": "https://www.facebook.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "youtube": "https://www.youtube.com",
        "stackoverflow": "https://stackoverflow.com",
        "wikipedia": "https://en.wikipedia.org",
        "duckduckgo": "https://duckduckgo.com",
        "yahoo": "https://www.yahoo.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://www.spotify.com",
        "twitch": "https://www.twitch.tv",
        "ebay": "https://www.ebay.com",
        "walmart": "https://www.walmart.com",
        "paypal": "https://www.paypal.com",
        "dropbox": "https://www.dropbox.com",
        "drive": "https://drive.google.com",
        "onedrive": "https://onedrive.live.com",
        "icloud": "https://www.icloud.com",
        "notion": "https://www.notion.so",
        "trello": "https://trello.com",
        "asana": "https://asana.com",
        "slack": "https://slack.com",
        "teams": "https://teams.microsoft.com",
        "zoom": "https://zoom.us",
        "meet": "https://meet.google.com",
        "discord": "https://discord.com",
        "telegram": "https://telegram.org",
        "whatsapp": "https://www.whatsapp.com",
        "signal": "https://signal.org",
        "messenger": "https://www.messenger.com",
        "snapchat": "https://www.snapchat.com",
        "tiktok": "https://www.tiktok.com",
        "pinterest": "https://www.pinterest.com",
        "medium": "https://medium.com",
        "substack": "https://substack.com",
        "wordpress": "https://wordpress.com",
        "shopify": "https://www.shopify.com",
        "etsy": "https://www.etsy.com",
        "fiverr": "https://www.fiverr.com",
        "upwork": "https://www.upwork.com",
        "glassdoor": "https://www.glassdoor.com",
        "indeed": "https://www.indeed.com",
        "coursera": "https://www.coursera.org",
        "udemy": "https://www.udemy.com",
        "edx": "https://www.edx.org",
        "khan": "https://www.khanacademy.org",
        "duolingo": "https://www.duolingo.com",
        "applemusic": "https://music.apple.com",
        "soundcloud": "https://soundcloud.com",
        "pandora": "https://www.pandora.com",
        "iheartradio": "https://www.iheart.com",
        "audible": "https://www.audible.com",
        "kindle": "https://www.amazon.com/kindle",
        "goodreads": "https://www.goodreads.com",
        "archive": "https://archive.org",
        "wayback": "https://web.archive.org",
        "maps": "https://maps.google.com",
        "earth": "https://earth.google.com",
        "waze": "https://www.waze.com",
        "uber": "https://www.uber.com",
        "lyft": "https://www.lyft.com",
        "doordash": "https://www.doordash.com",
        "grubhub": "https://www.grubhub.com",
        "ubereats": "https://www.ubereats.com",
        "instacart": "https://www.instacart.com",
        "airbnb": "https://www.airbnb.com",
        "booking": "https://www.booking.com",
        "expedia": "https://www.expedia.com",
        "kayak": "https://www.kayak.com",
        "tripadvisor": "https://www.tripadvisor.com",
        "hotels": "https://www.hotels.com",
        "yelp": "https://www.yelp.com",
        "foursquare": "https://foursquare.com",
        "opentable": "https://www.opentable.com",
        "cvs": "https://www.cvs.com",
        "walgreens": "https://www.walgreens.com",
        "amazon": "https://www.amazon.com",
        "costco": "https://www.costco.com",
        "ikea": "https://www.ikea.com",
        "wayfair": "https://www.wayfair.com",
        "homedepot": "https://www.homedepot.com",
        "lowes": "https://www.lowes.com",
        "att": "https://www.att.com",
        "verizon": "https://www.verizon.com",
        "tmobile": "https://www.t-mobile.com",
        "sprint": "https://www.sprint.com",
        "comcast": "https://www.xfinity.com",
        "spectrum": "https://www.spectrum.com",
        "googlefi": "https://fi.google.com",
        "mintmobile": "https://www.mintmobile.com",
        "googlevoice": "https://voice.google.com",
        "skype": "https://www.skype.com",
        "viber": "https://www.viber.com",
        "line": "https://line.me",
        "wechat": "https://www.wechat.com",
        "kakaotalk": "https://www.kakaocorp.com/page/service/service/KakaoTalk",
        "kik": "https://www.kik.com",
        "telegram": "https://telegram.org",
        "signal": "https://signal.org",
        "wire": "https://wire.com",
        "threema": "https://threema.ch",
        "wickr": "https://wickr.com",
        "element": "https://element.io",
        "matrix": "https://matrix.org",
        "rocket": "https://rocket.chat",
        "mattermost": "https://mattermost.com",
        "zulip": "https://zulip.com",
        "flock": "https://flock.com",
        "ryver": "https://ryver.com",
        "flowdock": "https://flowdock.com",
        "campfire": "https://campfire.com",
        "hipchat": "https://www.atlassian.com/software/hipchat",
        "yammer": "https://www.yammer.com",
        "jive": "https://www.jivesoftware.com",
        "socialcast": "https://www.socialcast.com",
        "convo": "https://www.convo.com",
        "chatter": "https://www.salesforce.com/products/chatter",
        "workplace": "https://www.workplace.com",
        "fbworkplace": "https://www.workplace.com",
        "symphony": "https://symphony.com",
        "perzo": "https://www.perzo.com",
        "huddle": "https://www.huddle.com",
        "basecamp": "https://basecamp.com",
        "podio": "https://podio.com",
        "redbooth": "https://www.redbooth.com",
        "projectplace": "https://www.projectplace.com",
        "wrike": "https://www.wrike.com",
        "smartsheet": "https://www.smartsheet.com",
        "clarizen": "https://www.clarizen.com",
        "workfront": "https://www.workfront.com",
        "targetprocess": "https://www.targetprocess.com",
        "liquidplanner": "https://www.liquidplanner.com",
        "teamwork": "https://www.teamwork.com",
        "paymo": "https://www.paymoapp.com",
        "productive": "https://www.productive.io",
        "functionpoint": "https://www.functionpoint.com",
        "ravetools": "https://www.ravetools.com",
        "hubstaff": "https://hubstaff.com",
        "toggl": "https://toggl.com",
        "harvest": "https://www.getharvest.com",
        "freshbooks": "https://www.freshbooks.com",
        "quickbooks": "https://quickbooks.intuit.com",
        "xero": "https://www.xero.com",
        "wave": "https://www.waveapps.com",
        "zipbooks": "https://www.zipbooks.com",
        "sage": "https://www.sage.com",
        "netsuite": "https://www.netsuite.com",
        "sap": "https://www.sap.com",
        "oracle": "https://www.oracle.com",
        "microsoft": "https://www.microsoft.com",
        "dynamics": "https://dynamics.microsoft.com",
        "salesforce": "https://www.salesforce.com",
        "hubspot": "https://www.hubspot.com",
        "zoho": "https://www.zoho.com",
        "pipedrive": "https://www.pipedrive.com",
        "insightly": "https://www.insightly.com",
        "nimble": "https://www.nimble.com",
        "copper": "https://www.copper.com",
        "freshsales": "https://www.freshworks.com/freshsales-crm",
        "bitrix24": "https://www.bitrix24.com",
        "vtiger": "https://www.vtiger.com",
        "sugarcrm": "https://www.sugarcrm.com",
        "apptivo": "https://www.apptivo.com",
        "reallysimple": "https://www.reallysimplecrm.com",
        "capsule": "https://capsulecrm.com",
        "agile": "https://www.agilecrm.com",
        "lessannoying": "https://www.lessannoyingcrm.com",
        "hatchbuck": "https://www.hatchbuck.com",
        "mailchimp": "https://mailchimp.com",
        "constantcontact": "https://www.constantcontact.com",
        "sendinblue": "https://www.sendinblue.com",
        "getresponse": "https://www.getresponse.com",
        "aweber": "https://www.aweber.com",
        "activecampaign": "https://www.activecampaign.com",
        "convertkit": "https://convertkit.com",
        "drip": "https://www.drip.com",
        "klaviyo": "https://www.klaviyo.com",
        "omnisend": "https://www.omnisend.com",
        "mailerlite": "https://www.mailerlite.com",
        "mailjet": "https://www.mailjet.com",
        "sendgrid": "https://sendgrid.com",
        "postmark": "https://postmarkapp.com",
        "mailgun": "https://www.mailgun.com",
        "amazon ses": "https://aws.amazon.com/ses",
        "sparkpost": "https://www.sparkpost.com",
        "socketlabs": "https://www.socketlabs.com",
        "smtp": "https://www.smtp.com",
        "jango": "https://www.jangomail.com",
        "benchmark": "https://www.benchmarkemail.com",
        "verticalresponse": "https://www.verticalresponse.com",
        "icontact": "https://www.icontact.com",
        "emma": "https://www.myemma.com",
        "campaignmonitor": "https://www.campaignmonitor.com",
        "moonmail": "https://moonmail.com",
        "mailify": "https://www.mailify.com",
        "epic": "https://www.epic.com",
        "hubspot": "https://www.hubspot.com",
        "marketo": "https://www.marketo.com",
        "pardot": "https://www.pardot.com",
        "eloqua": "https://www.eloqua.com",
        "infusionsoft": "https://www.infusionsoft.com",
        "keap": "https://keap.com",
        "ontraport": "https://ontraport.com",
        "autopilot": "https://autopilot.com",
        "customerio": "https://customer.io",
        "iterable": "https://iterable.com",
        "braze": "https://www.braze.com",
        "leanplum": "https://www.leanplum.com",
        "appboy": "https://www.braze.com",
        "localytics": "https://www.localytics.com",
        "swrve": "https://www.swrve.com",
        "kahuna": "https://www.kahuna.com",
        "responsys": "https://www.responsys.com",
        "silverpop": "https://www.silverpop.com",
        "unica": "https://www.unica.com",
        "teradata": "https://www.teradata.com",
        "netezza": "https://www.ibm.com/analytics/netezza",
        "vertica": "https://www.vertica.com",
        "greenplum": "https://greenplum.org",
        "redshift": "https://aws.amazon.com/redshift",
        "snowflake": "https://www.snowflake.com",
        "bigquery": "https://cloud.google.com/bigquery",
        "azure": "https://azure.microsoft.com",
        "databricks": "https://databricks.com",
        "synapse": "https://azure.microsoft.com/en-us/services/synapse-analytics",
        "athena": "https://aws.amazon.com/athena",
        "glue": "https://aws.amazon.com/glue",
        "lakeformation": "https://aws.amazon.com/lake-formation",
        "kinesis": "https://aws.amazon.com/kinesis",
        "firehose": "https://aws.amazon.com/firehose",
        "msk": "https://aws.amazon.com/msk",
        "kafka": "https://kafka.apache.org",
        "rabbitmq": "https://www.rabbitmq.com",
        "activemq": "https://activemq.apache.org",
        "zeromq": "https://zeromq.org",
        "nats": "https://nats.io",
        "pulsar": "https://pulsar.apache.org",
        "rocketmq": "https://rocketmq.apache.org",
        "beanstalkd": "https://beanstalkd.github.io",
        "gearman": "http://gearman.org",
        "sidekiq": "https://sidekiq.org",
        "resque": "https://github.com/resque/resque",
        "delayed_job": "https://github.com/collectiveidea/delayed_job",
        "celery": "https://docs.celeryproject.org",
        "rq": "https://python-rq.org",
        "huey": "https://huey.readthedocs.io",
        "dramatiq": "https://dramatiq.io",
        "tasktiger": "https://tasktiger.readthedocs.io",
        "apscheduler": "https://apscheduler.readthedocs.io",
        "schedule": "https://schedule.readthedocs.io",
        "spiff": "https://spiffworkflow.org",
        "airflow": "https://airflow.apache.org",
        "dagster": "https://dagster.io",
        "prefect": "https://www.prefect.io",
        "luigi": "https://luigi.readthedocs.io",
        "argo": "https://argoproj.github.io",
        "temporal": "https://temporal.io",
        "cadence": "https://cadenceworkflow.io",
        "zeebe": "https://zeebe.io",
        "conductor": "https://conductor-oss.github.io/conductor",
        "stepfunctions": "https://aws.amazon.com/step-functions",
        "logicapps": "https://azure.microsoft.com/en-us/services/logic-apps",
        "durablefunctions": "https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview",
        "workflowservice": "https://cloud.google.com/workflows",
        "eventarc": "https://cloud.google.com/eventarc",
        "pubsub": "https://cloud.google.com/pubsub",
        "sns": "https://aws.amazon.com/sns",
        "sqs": "https://aws.amazon.com/sqs",
        "eventbridge": "https://aws.amazon.com/eventbridge",
        "servicebus": "https://azure.microsoft.com/en-us/services/service-bus",
        "eventgrid": "https://azure.microsoft.com/en-us/services/event-grid",
        "eventhubs": "https://azure.microsoft.com/en-us/services/event-hubs",
    }

    def __init__(self, memory_path: Optional[str] = None):
        """Initialize planner with full system awareness."""
        self.intent_patterns = self._load_patterns()
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._memory_path = memory_path or self._default_memory_path()
        self._load_memory()

    @staticmethod
    def _default_memory_path() -> str:
        try:
            base = Path(os.environ.get("SCREEN_AI_DATA_DIR")
                        or "ai_pc_operator/data")
            base.mkdir(parents=True, exist_ok=True)
            return str(base / "planner_memory.json")
        except Exception:
            return "planner_memory.json"

    def _load_memory(self) -> None:
        try:
            if os.path.exists(self._memory_path):
                with open(self._memory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._memory = data
        except Exception:
            self._memory = {}

    def _save_memory(self) -> None:
        try:
            with open(self._memory_path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def remember(self, text: str, intent: str,
                 args: Optional[Dict[str, Any]] = None) -> None:
        """Record that `text` mapped to `intent` so future similar inputs match."""
        key = self._normalize_for_memory(text)
        if not key:
            return
        entry = self._memory.get(key, {"intent": intent, "args": args or {},
                                         "count": 0, "last_used": 0.0})
        entry["intent"] = intent
        entry["args"] = args or entry.get("args", {})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_used"] = time.time()
        self._memory[key] = entry
        self._save_memory()

    @staticmethod
    def _normalize_for_memory(text: str) -> str:
        s = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _load_patterns(self) -> Dict[str, List[re.Pattern[str]]]:
        """Load intent classification patterns."""
        raw_patterns = {
            "system_status": [
                r"\b(check|show|get)\b.*\b(status|health|info)\b",
                r"\bhow is\b.*\b(pc|computer|laptop)\b",
                r"\bsystem\s+(status|info|check)\b",
                r"\b(pc|computer|laptop)\s+(status|health)\b",
            ],
            "disk_usage": [
                r"\b(check|show|get)\b.*\b(storage|disk|drive)\b",
                r"\b(disk|storage|drive)\b.*\b(usage|space|free|full)\b",
                r"\bhow much\b.*\b(space|storage)\b",
            ],
            "ram_usage": [
                r"\b(ram|memory)\b.*\b(usage|used|free)\b",
                r"\bhow much\b.*\b(memory|ram)\b",
            ],
            "list_files": [
                r"\b(list|show|display)\b.*\b(files|folder|directory)\b",
                r"\bwhat('s| is) in\b",
            ],
            "delete_files": [
                r"\b(delete|remove|clean|erase|wipe|trash|purge)\b.*\b(files?|folder|directory)\b",
                r"\bempty\b.*\b(folder|directory|trash)\b",
            ],
            "open_website": [
                r"\b(open|go to|navigate to|visit|browse)\b.*\b(website|url|site)\b",
                r"\b(open|go to|navigate to|visit|browse)\b\s+([a-zA-Z0-9.-]+\.[a-z]{2,}|amazon|bing|chatgpt|facebook|gmail|google|github|instagram|linkedin|reddit|twitter|x|youtube)\b",
                r"\bhttps?://\S+",
            ],
            "network_ping": [
                r"\bping\b.*\b(host|server|site|domain)\b",
                r"\bping\s+\S+",
                r"\bping\b",
            ],
            "email_search": [
                r"\b(search|find|look\s*up|lookup)\b.*\b(email|mail|inbox|message)\b",
                r"\b(search|find|look\s*up|lookup)\b\s+(email|mail|inbox|message)\b",
            ],
            "research_collect": [
                r"\b(research|investigate|study|explore|collect|gather)\b.*\b(topic|subject|about)\b",
                r"\bresearch\s+\w+",
            ],
            "search_web": [
                r"\b(search|google|find|look\s*up|lookup|query|research)\b.*\b(web|internet|online)\b",
                r"\bsearch\b\s+for\b",
                r"\b(search|find|look\s*up|lookup|query|research)\b\s+\w+",
                r"\bgoogle\b\s+\w+",
                r"\b(search|google|find|look\s*up|lookup)\b.*\b(in|on|with)\s+(chrome|edge|browser|google|bing)\b",
            ],
            "close_all_apps": [
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b\s+(all|every|each)\b.*\b(app|application|program|window|process|software)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b\s+(all|every|each)\b.*\b(in|on|from)\b.*\b(desktop|taskbar|screen|foreground)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b\s+(all|every|each)\b.*\b(desktop|taskbar|screen|foreground)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b\s+(all|every|each)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b.*\b(everything|all\s+(of\s+)?(it|them))\b",
                r"\bkeep\s+\w+\s+(open|running|alive)\s+but\s+(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b.*\b(everything|all|else)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b.*\b(everything|all)\b.*\b(else|but)\b",
                r"\bkeep\s+\w+\s+(open|running|alive)\s+but\b",
            ],
            "close_app": [
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b\s+(chrome|edge|firefox|opera|notepad|calculator|calc|explorer|paint|cmd|powershell|terminal|vs\s*code|vscode|code|excel|word|powerpoint|outlook|spotify|discord|slack|telegram|whatsapp|steam|epic|app|application|program)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop|end|dismiss)\b.*\b(chrome|edge|firefox|opera|notepad|calculator|calc|explorer|paint|cmd|powershell|terminal|vs\s*code|vscode|code|excel|word|powerpoint|outlook|spotify|discord|slack|telegram|whatsapp|steam|epic)\b",
            ],
            "browser_close": [
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop)\b.*\b(browser|chrome|edge|firefox|tab)\b",
                r"\b(close|quit|exit|shut\s*down|kill|terminate|stop)\b\s+(browser|chrome|edge|firefox)\b",
            ],
            "browser_session": [
                r"browser[\s_]*session",
                r"\bkeep\s+(browser|session|pc|computer)\s+(awake|alive|open|active)\b",
                r"\bkeep\s+(awake|alive|active)\b.*\b(browser|session)\b",
            ],
            "browser_open": [
                r"\b(open|launch|start|run|fire\s*up|boot|bring\s*up)\b\s+(the\s+)?(browser)\b",
                r"\b(open|launch|start|run|fire\s*up|boot|bring\s*up)\b\s+(google\s+)?(chrome|microsoft\s+edge|firefox|brave)\b(?!\s+(gx|browser)\b)",
                r"\b(open|launch|start|run|fire\s*up|boot|bring\s*up)\b\s+(edge|opera)\b(?!\s+(gx|browser)\b)",
            ],
            "open_app": [
                r"\b(open|launch|start|fire\s*up|boot|bring\s*up)\b.*\b(app|application|program|software)\b",
                r"\b(open|launch|start|fire\s*up|boot|bring\s*up)\b\s+(?!camera\b)\w+",
                r"\brun\s+(chrome|edge|firefox|opera|notepad|calc|excel|word|powerpoint|outlook|spotify|discord|slack|vscode|code|terminal|explorer|paint|wordpad|settings|camera|photos|movies|music|store|mail|calendar|clock|weather|maps|news|notes|todo|sticky|calculator)\b",
            ],
            "terminal_powershell": [
                r"\b(powershell|ps)\b.*\b(run|execute|command)\b",
                r"\brun\s+powershell\b",
                r"\b(powershell|ps)\b",
            ],
            "terminal_cmd": [
                r"\b(cmd|command\s+prompt)\b.*\b(run|execute|command)\b",
                r"\brun\s+cmd\b",
                r"\b(cmd|command\s+prompt)\b",
            ],
            "download_file": [
                r"\b(download|get|fetch)\b.*\b(file|program|app)\b",
            ],
            "login": [
                r"\b(login|sign\s*in|log\s*in)\b.*\b(to|on)\b",
                r"\blogin\b\s+to\b",
            ],
            "send_email": [
                r"\b(send|write|compose)\b.*\b(email|mail|message)\b",
                r"\b(send|write|compose)\b\s+(an?\s+)?(email|mail|message)\b",
            ],
            "run_command": [
                r"\b(run|execute)\b.*\b(command|script|code)\b",
            ],
            "screen_click": [
                r"\b(click|press|tap|select)\b\s+(?!a\s+(photo|picture|selfie)\b)(.+)",
                r"\b(click|press|tap|select)\b.*\b(button|link|tab|field)\b",
            ],
            "screen_scan": [
                r"\b(scan|show|detect|find)\b.*\b(screen|buttons|ui|controls)\b",
                r"\bwhat\b.*\b(on|in)\b.*\b(screen)\b",
            ],
            "keep_awake": [
                r"\bkeep\s+(awake|alive|active)\b",
                r"\bdon'?t\s+(sleep|go\s+to\s+sleep|lock)\b",
                r"\bprevent\s+(sleep|lock)\b",
                r"\b(stay|remain)\s+awake\b",
            ],
            "mouse_jiggle": [
                r"\bjiggle\s+(the\s+)?mouse\b",
                r"\bmove\s+(the\s+)?mouse\b",
                r"\bkeep\s+mouse\s+moving\b",
            ],
            "open_settings": [
                r"\bopen\s+(windows\s+)?settings\b",
                r"\b(settings|control\s+panel)\b",
                r"\bsystem\s+settings\b",
                r"\bopen\s+settings\s+(for|to)\b",
                r"\bsettings\s+(for|to)\b",
            ],
            "shutdown_pc": [
                r"\b(shut\s*down|power\s*off)\b.*\b(pc|computer|laptop)\b",
                r"\b(shut\s*down|power\s*off)\b\s+(the\s+)?(pc|computer|laptop)\b",
                r"\bturn\s+off\b.*\b(pc|computer|laptop)\b",
            ],
            "restart_pc": [
                r"\b(restart|reboot)\b.*\b(pc|computer|laptop)\b",
                r"\b(restart|reboot)\b\s+(the\s+)?(pc|computer|laptop)\b",
            ],
            "lock_pc": [
                r"\block\s+(the\s+)?(pc|computer|laptop|screen)\b",
                r"\block\s+(my\s+)?(screen|computer)\b",
                r"\block\s+(my\s+)?pc\b",
                r"\block\s+(my\s+)?computer\b",
                r"\block\s+(my\s+)?laptop\b",
            ],
            "file_read": [
                r"\b(read|open|view|show|display|cat)\b.*\b(file|document|doc)\b",
                r"\bwhat('s| is) in\b.*\b(file|document)\b",
            ],
            "file_write": [
                r"\b(write|create|make|save)\b.*\b(file|document|note)\b",
                r"\b(create|make)\b.*\b(note|text|file)\b",
            ],
            "file_rename": [
                r"\b(rename|relabel)\b.*\b(file|folder|directory)\b",
            ],
            "file_move": [
                r"\b(move|transfer|relocate)\b.*\b(file|folder)\b",
            ],
            "file_copy": [
                r"\b(copy|duplicate|clone)\b.*\b(file|folder)\b",
            ],
            "file_compress": [
                r"\b(compress|zip|archive|pack)\b.*\b(file|folder)\b",
            ],
            "file_extract": [
                r"\b(extract|unzip|unpack|decompress)\b.*\b(file|archive|zip)\b",
            ],
            "file_search": [
                r"\b(find|search|locate)\b.*\b(file|document)\b",
                r"\b(find|search|locate)\b.*\b[\w.-]+\.(txt|pdf|docx?|xlsx?|png|jpe?g|zip)\b",
            ],
            "file_backup": [
                r"\b(backup|save|snapshot)\b.*\b(file|folder|directory)\b",
            ],
            "window_focus": [
                r"\b(focus|activate|bring\s+to\s+front)\b.*\b(window|app)\b",
            ],
            "window_switch": [
                r"\b(switch|change)\b.*\b(window|app)\b",
            ],
            "window_minimize": [
                r"\b(minimize|minify|shrink)\b.*\b(window|app)\b",
            ],
            "window_maximize": [
                r"\b(maximize|enlarge|expand|fullscreen)\b.*\b(window|app)\b",
            ],
            "window_close": [
                r"\b(close|quit|exit)\b.*\b(window)\b",
            ],
            "window_arrange": [
                r"\b(arrange|organize|tile|cascade)\b.*\b(window)\b",
                r"\b(arrange|organize|tile|cascade)\b\s+(windows|the\s+windows)\b",
            ],
            "window_screenshot": [
                r"\b(screenshot|capture|snap)\b.*\b(window)\b",
            ],
            "app_install": [
                r"\b(install|setup|set\s+up|deploy)\b.*\b(app|program|software)\b",
                r"\b(install|setup|set\s+up|deploy)\b\s+\w+",
            ],
            "app_uninstall": [
                r"\b(uninstall|remove)\b.*\b(app|program|software)\b",
                r"\b(uninstall|remove)\b\s+\w+",
            ],
            "app_update": [
                r"\b(update|upgrade|patch)\b.*\b(app|program|software)\b",
                r"\b(update|upgrade|patch)\b\s+\w+",
            ],
            "app_restart": [
                r"\b(restart|reboot)\b.*\b(app|program|software)\b",
                r"\b(restart|reboot)\b\s+\w+",
            ],
            "dev_test": [
                r"\b(test|run\s+tests)\b.*\b(project|app|code)\b",
                r"\brun\s+tests?\b",
                r"\b(run\s+)?tests?\b",
            ],
            "dev_run": [
                r"\b(run|start|launch)\b.*\b(project|app|server)\b",
                r"\brun\s+dev\s+server\b",
                r"\bdev\s+server\b",
            ],
            "terminal_run": [
                r"\b(run|execute)\b.*\b(command|script)\b",
                r"\b(run|execute)\b\s+(bash|terminal)\b",
            ],
            "dev_git": [
                r"\bgit\s+(clone|commit|push|pull|branch|merge|status)\b",
                r"\b(clone|commit|push|pull)\b.*\b(repo|repository|code)\b",
            ],
            "dev_build": [
                r"\b(build|compile)\b.*\b(project|app|code)\b",
            ],
            "dev_docker": [
                r"\bdocker\s+(build|run|compose)\b",
            ],
            "ocr_screen": [
                r"\b(read|extract|scan)\b.*\btext\b.*\b(screen|window)\b",
                r"\bocr\b.*\b(screen|window)\b",
            ],
            "ocr_region": [
                r"\b(read|extract|scan)\b.*\btext\b.*\b(region|area|part)\b",
            ],
            "vision_detect": [
                r"\b(detect|find|recognize|see)\b.*\b(button|icon|image|logo|color|cursor|object)\b",
            ],
            "clipboard_copy": [
                r"\b(copy)\b.*\b(clipboard|clip)\b",
                r"\bclipboard\s+copy\b",
            ],
            "clipboard_paste": [
                r"\b(paste)\b.*\b(clipboard|clip)\b",
                r"\bclipboard\s+paste\b",
            ],
            "clipboard_read": [
                r"\b(read|show|get)\b.*\bclipboard\b",
            ],
            "email_compose": [
                r"\b(compose|write|draft)\b.*\b(email|mail|message)\b",
                r"\b(compose|write|draft)\b\s+(an?\s+)?(email|mail|message)\b",
            ],
            "email_send": [
                r"\b(send|dispatch|deliver)\b.*\b(email|mail|message)\b",
                r"\b(send|dispatch|deliver)\b\s+(an?\s+)?(email|mail|message)\b",
            ],
            "network_download": [
                r"\bdownload\b.*\b(file|url|link)\b",
            ],
            "network_upload": [
                r"\bupload\b.*\b(file|url|link)\b",
            ],
            "network_wifi": [
                r"\b(wifi|wi-fi|wireless)\b.*\b(status|connect|disconnect|on|off)\b",
                r"\b(check|show|get)\b.*\b(wifi|wi-fi|wireless)\b",
                r"\bwifi\b",
            ],
            "media_screenshot": [
                r"\b(screenshot|screen\s*shot|capture\s+screen|take\s+picture)\b",
                r"\bsnap\s+(the\s+)?screen\b",
            ],
            "media_screen_record": [
                r"\b(record|capture)\b.*\b(screen|video)\b",
                r"\bscreen\s+record\b",
            ],
            "media_camera": [
                r"\b(open|launch|start)\b.*\bcamera\b",
            ],
            "take_camera_photo": [
                r"\b(take|click|snap|capture|shoot)\b.*\b(picture|photo|selfie|webcam)\b",
                r"\btake\s+my\s+picture\b",
                r"\b(capture|take)\s+(a\s+)?(photo|picture|selfie)\b",
                r"\buse\s+(the\s+)?webcam\b",
                r"\btake\s+(a\s+)?(picture|photo)\s+of\s+me\b",
            ],
            "doc_pdf_read": [
                r"\b(read|open|view)\b.*\bpdf\b",
            ],
            "doc_pdf_write": [
                r"\b(create|make|write|generate)\b.*\bpdf\b",
            ],
            "doc_word_read": [
                r"\b(read|open|view)\b.*\b(word|docx|document)\b",
            ],
            "doc_excel_read": [
                r"\b(read|open|view)\b.*\b(excel|xlsx|spreadsheet)\b",
            ],
            "doc_csv_read": [
                r"\b(read|open|view)\b.*\b(csv|comma\s+separated)\b",
            ],
            "memory_remember": [
                r"\b(remember|save|store|note)\b.*\b(that|this|it)\b",
                r"\bremember\s+that\b",
            ],
            "memory_recall": [
                r"\b(recall|what\s+did|do\s+you\s+remember)\b",
                r"\bwhat\s+do\s+you\s+(know|remember)\b\s+about\b",
            ],
            "memory_forget": [
                r"\b(forget|erase|clear)\b.*\b(memory|that|this)\b",
            ],
            "task_create": [
                r"\b(create|make|add)\b.*\b(task|workflow|job)\b",
            ],
            "task_run": [
                r"\b(run|execute|start)\b.*\b(task|workflow|job)\b",
                r"\b(run|execute|start)\b\s+(task|workflow|job)\b",
            ],
            "task_cancel": [
                r"\b(cancel|abort|stop)\b.*\b(task|workflow|job)\b",
            ],
            "research_summarize": [
                r"\b(summarize|condense|tldr|shorten)\b.*\b(article|page|document|text)\b",
            ],
        }
        return {
            intent: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for intent, patterns in raw_patterns.items()
        }

    async def classify_intent(self, text: str) -> str:
        """Classify user command intent with full system awareness.

        Delegates to the sync core (the non-LLM tiers).
        """
        return self._classify_core(text)

    def classify_intent_sync(self, text: str) -> str:
        """Sync intent classification using the non-LLM tiers.

        Used by the compound-sequence planner (TaskPlanner is sync).
        """
        return self._classify_core(text)

    def _classify_core(self, text: str) -> str:
        """Cognitive Planner v1.0 classification core (no LLM fallback).

        1. Run cognitive pipeline (spelling correction, alias resolution,
           synonym expansion, canonical action extraction)
        2. Exact memory match
        3. Fuzzy memory match
        4. Synonym expansion + regex pattern match
        5. Pipeline knowledge base match (knows all 268 pipelines)
        6. Phase utility knowledge base match (knows all 154 utilities)
        7. Token-overlap fuzzy match against known intent keywords
        8. Default to "unknown"
        """
        if not text or not text.strip():
            return "unknown"

        # 1. Run cognitive pipeline (spelling, aliases, synonyms, canonical)
        cognitive = cognitive_pipeline(text)
        text_lower = cognitive["alias_resolved"].lower().strip()
        normalized = self._normalize_for_memory(cognitive["alias_resolved"])

        # 2. Exact memory match
        if normalized in self._memory:
            return self._memory[normalized].get("intent", "unknown")

        # 3. Fuzzy memory match
        if self._memory:
            best_key, best_score = self._best_memory_match(normalized)
            if best_key and best_score >= 0.78:
                return self._memory[best_key].get("intent", "unknown")

        # 4. Synonym expansion + regex pattern match
        expanded = _expand_synonyms(text_lower)
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if pattern.search(expanded) or pattern.search(text_lower):
                    return intent

        # 5. Pipeline knowledge base match
        pipeline_intent = self._match_pipeline_knowledge(text_lower)
        if pipeline_intent:
            return pipeline_intent

        # 6. Phase utility knowledge base match
        phase_intent = self._match_phase_utility(text_lower)
        if phase_intent:
            return phase_intent

        # 7. Token-overlap fuzzy match
        fuzzy_intent = self._fuzzy_intent_match(text_lower)
        if fuzzy_intent:
            return fuzzy_intent

        # 8. Default
        return "unknown"

    def _best_memory_match(self, normalized: str) -> Tuple[Optional[str], float]:
        if not normalized or not self._memory:
            return None, 0.0
        target_tokens = set(normalized.split())
        best_key, best_score = None, 0.0
        for key in self._memory.keys():
            key_tokens = set(key.split())
            if not target_tokens or not key_tokens:
                continue
            overlap = len(target_tokens & key_tokens)
            union = len(target_tokens | key_tokens)
            score = overlap / union if union else 0.0
            seq_ratio = difflib.SequenceMatcher(None, normalized, key).ratio()
            score = max(score, seq_ratio)
            if score > best_score:
                best_score = score
                best_key = key
        return best_key, best_score

    def _match_pipeline_knowledge(self, text_lower: str) -> Optional[str]:
        """Match against the 268 pipeline graphs across 13+ domains."""
        tokens = set(re.findall(r"[a-z]+", text_lower))
        if not tokens:
            return None
        best_domain, best_score = None, 0.0
        for domain, info in PIPELINE_KNOWLEDGE.items():
            kw_set = set(info["keywords"])
            overlap = len(tokens & kw_set)
            if overlap == 0:
                continue
            score = overlap / max(1, len(kw_set))
            if score > best_score:
                best_score = score
                best_domain = domain
        if best_score >= 0.30:
            domain_to_intent = {
                "browser": "browser_open",
                "file": "file_read",
                "window": "window_focus",
                "app": "open_app",
                "terminal": "terminal_run",
                "dev": "dev_git",
                "ocr": "ocr_screen",
                "vision": "vision_detect",
                "clipboard": "clipboard_read",
                "email": "email_compose",
                "network": "network_ping",
                "media": "media_screenshot",
                "doc": "doc_pdf_read",
                "system": "system_status",
                "screen": "screen_scan",
                "vault": "login",
                "memory": "memory_recall",
                "task": "task_create",
                "approval": "approval_request",
                "research": "research_collect",
            }
            return domain_to_intent.get(best_domain)
        return None

    def _match_phase_utility(self, text_lower: str) -> Optional[str]:
        """Match against the 154 phase utilities."""
        tokens = set(re.findall(r"[a-z]+", text_lower))
        if not tokens:
            return None
        best_phase, best_score = None, 0.0
        for phase, info in PHASE_UTILITY_KNOWLEDGE.items():
            kw_set = set(info["keywords"])
            overlap = len(tokens & kw_set)
            if overlap == 0:
                continue
            score = overlap / max(1, len(kw_set))
            if score > best_score:
                best_score = score
                best_phase = phase
        if best_score >= 0.40:
            phase_to_intent = {
                "intent": "system_status",
                "context": "system_status",
                "observation": "screen_scan",
                "verification": "system_status",
                "recovery": "system_status",
                "memory": "memory_recall",
                "skill": "system_status",
                "state": "system_status",
                "workflow": "task_create",
                "provider": "system_status",
                "agent_runtime": "system_status",
                "event": "system_status",
                "native": "system_status",
            }
            return phase_to_intent.get(best_phase)
        return None

    def _fuzzy_intent_match(self, text_lower: str) -> Optional[str]:
        """Last-resort fuzzy match using keyword overlap with intent labels."""
        intent_keywords = {
            "close_all_apps": ["close", "all", "apps", "desktop", "taskbar",
                                "everything", "shut", "down"],
            "close_app": ["close", "chrome", "edge", "firefox", "notepad",
                          "app", "shut", "down"],
            "open_app": ["open", "launch", "start", "app", "program"],
            "browser_open": ["open", "launch", "start", "browser", "chrome",
                             "edge", "firefox"],
            "browser_close": ["close", "browser", "chrome", "edge"],
            "browser_session": ["browser", "session", "keep", "awake"],
            "search_web": ["search", "google", "find", "web", "look"],
            "open_website": ["open", "website", "url", "site", "visit"],
            "delete_files": ["delete", "remove", "files", "folder"],
            "list_files": ["list", "show", "files", "folder"],
            "system_status": ["status", "health", "check", "system"],
            "keep_awake": ["keep", "awake", "sleep", "prevent"],
            "shutdown_pc": ["shutdown", "shut", "down", "power", "off"],
            "restart_pc": ["restart", "reboot"],
            "lock_pc": ["lock", "screen", "computer"],
            "file_read": ["read", "file", "document", "open"],
            "file_write": ["write", "create", "file", "note"],
            "file_search": ["find", "search", "file", "document"],
            "window_focus": ["focus", "window", "activate"],
            "window_minimize": ["minimize", "window"],
            "window_maximize": ["maximize", "window", "fullscreen"],
            "app_install": ["install", "app", "program"],
            "app_uninstall": ["uninstall", "app", "program"],
            "terminal_run": ["run", "command", "execute", "powershell"],
            "dev_git": ["git", "clone", "commit", "push", "pull"],
            "dev_build": ["build", "compile", "project"],
            "ocr_screen": ["read", "text", "screen", "ocr"],
            "vision_detect": ["detect", "find", "see", "recognize"],
            "clipboard_copy": ["copy", "clipboard"],
            "clipboard_paste": ["paste", "clipboard"],
            "email_compose": ["compose", "email", "mail", "write"],
            "email_send": ["send", "email", "mail"],
            "network_ping": ["ping", "host", "server"],
            "media_screenshot": ["screenshot", "capture", "screen"],
            "media_screen_record": ["record", "screen", "video"],
            "media_camera": ["open", "camera", "launch"],
            "take_camera_photo": ["take", "picture", "photo", "selfie",
                                  "webcam", "capture", "camera"],
            "doc_pdf_read": ["read", "pdf", "open"],
            "memory_recall": ["remember", "recall", "what", "know"],
            "task_create": ["create", "task", "workflow"],
            "research_collect": ["research", "investigate", "collect"],
        }
        tokens = set(re.findall(r"[a-z]+", text_lower))
        if not tokens:
            return None
        best_intent, best_score = None, 0.0
        for intent, keywords in intent_keywords.items():
            kw_set = set(keywords)
            overlap = len(tokens & kw_set)
            if overlap == 0:
                continue
            score = overlap / max(1, len(kw_set))
            if any(w in tokens for w in ["close", "quit", "exit", "shut", "kill",
                                          "terminate", "stop", "end", "dismiss"]):
                if intent in {"close_all_apps", "close_app", "browser_close"}:
                    score += 0.2
            if score > best_score:
                best_score = score
                best_intent = intent
        if best_score >= 0.35:
            return best_intent
        return None

    async def create_plan(
        self, text: str, intent: str
    ) -> Dict[str, Any]:
        """Create execution plan from intent with full system awareness.

        Delegates to the sync core (this method has no awaits).
        """
        return self.create_plan_sync(text, intent)

    def create_plan_sync(
        self, text: str, intent: str
    ) -> Dict[str, Any]:
        """Sync execution-plan builder (used by TaskPlanner's compound
        sequence planner, which is synchronous)."""
        text_lower = text.lower().strip()

        if intent == "system_status":
            return {"steps": [{"tool": "system.status", "args": {}}]}

        elif intent == "disk_usage":
            return {"steps": [{"tool": "system.disk_usage", "args": {}}]}

        elif intent == "ram_usage":
            return {"steps": [{"tool": "system.ram_usage", "args": {}}]}

        elif intent == "list_files":
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.list", "args": {"path": path}}]}

        elif intent == "delete_files":
            path = self._extract_path(text)
            return {
                "steps": [
                    {"tool": "file.scan", "args": {"path": path}},
                    {"tool": "file.quarantine", "args": {"path": path}},
                ]
            }

        elif intent == "browser_open":
            app_name = self._extract_app_name(text)
            if not app_name or app_name == "unknown":
                app_name = "chrome"
            return {"steps": [{"tool": "system.open_app", "args": {"name": app_name}}]}

        elif intent == "open_app":
            app_name = self._extract_app_name(text)
            return {"steps": [{"tool": "system.open_app", "args": {"name": app_name}}]}

        elif intent == "open_website":
            url = self._extract_url(text)
            return {"steps": [{"tool": "browser.open", "args": {"url": url}}]}

        elif intent == "search_web":
            query = self._extract_search_query(text)
            return {"steps": [{"tool": "browser.search", "args": {"query": query}}]}

        elif intent == "browser_close":
            return {"steps": [{"tool": "browser.close", "args": {}}]}

        elif intent == "browser_session":
            app = self._extract_app_name(text)
            if not app or app.replace("_", "").replace(" ", "") == intent.replace("_", ""):
                app = "chrome"
            return {
                "steps": [
                    {"tool": "system.open_app", "args": {"name": app}},
                    {"tool": "system.keep_awake", "args": {}},
                    {"tool": "system.mouse_jiggle", "args": {}},
                ]
            }

        elif intent == "close_app":
            app_name = self._extract_close_target(text)
            return {"steps": [{"tool": "system.close_app", "args": {"name": app_name}}]}

        elif intent == "close_all_apps":
            keep = self._extract_keep_names(text)
            return {
                "steps": [
                    {
                        "tool": "system.close_all_apps",
                        "args": {"exclude_system": True, "keep_names": keep},
                    },
                ]
            }

        elif intent == "keep_awake":
            minutes = self._extract_minutes(text) or 60
            return {"steps": [{"tool": "system.keep_awake", "args": {"minutes": minutes}}]}

        elif intent == "mouse_jiggle":
            minutes = self._extract_minutes(text) or 60
            return {"steps": [{"tool": "system.mouse_jiggle", "args": {"minutes": minutes}}]}

        elif intent == "open_settings":
            page = self._extract_settings_page(text)
            return {"steps": [{"tool": "system.open_settings", "args": {"page": page}}]}

        elif intent == "shutdown_pc":
            return {"steps": [{"tool": "system.shutdown", "args": {}}]}

        elif intent == "restart_pc":
            return {"steps": [{"tool": "system.restart", "args": {}}]}

        elif intent == "lock_pc":
            return {"steps": [{"tool": "system.lock", "args": {}}]}

        elif intent == "download_file":
            url = self._extract_url(text)
            return {"steps": [{"tool": "browser.download", "args": {"url": url}}]}

        elif intent == "screen_click":
            return {
                "steps": [
                    {"tool": "screen.click_text", "args": {"text": self._extract_click_text(text)}},
                ]
            }

        elif intent == "screen_scan":
            return {"steps": [{"tool": "screen.scan", "args": {}}]}

        elif intent == "login":
            site = self._extract_site(text)
            return {
                "steps": [
                    {"tool": "browser.open", "args": {"url": site}},
                    {"tool": "auth.password_login", "args": {"site": site}},
                ]
            }

        elif intent == "file_read":
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.read", "args": {"path": path}}]}

        elif intent == "file_write":
            path = self._extract_path(text)
            content = self._extract_content(text)
            return {"steps": [{"tool": "file.write", "args": {"path": path, "content": content}}]}

        elif intent == "file_rename":
            src, dst = self._extract_rename_pair(text)
            return {"steps": [{"tool": "file.rename", "args": {"src": src, "dst": dst}}]}

        elif intent == "file_move":
            src, dst = self._extract_move_pair(text)
            return {"steps": [{"tool": "file.move", "args": {"src": src, "dst": dst}}]}

        elif intent == "file_copy":
            src, dst = self._extract_move_pair(text)
            return {"steps": [{"tool": "file.copy", "args": {"src": src, "dst": dst}}]}

        elif intent == "file_compress":
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.compress", "args": {"path": path}}]}

        elif intent == "file_extract":
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.extract", "args": {"path": path}}]}

        elif intent == "file_search":
            query = self._extract_search_query(text)
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.search", "args": {"path": path, "query": query}}]}

        elif intent == "file_backup":
            path = self._extract_path(text)
            return {"steps": [{"tool": "file.backup", "args": {"path": path}}]}

        elif intent == "window_focus":
            target = self._extract_app_name(text)
            return {"steps": [{"tool": "window.focus", "args": {"target": target}}]}

        elif intent == "window_switch":
            target = self._extract_app_name(text)
            return {"steps": [{"tool": "window.switch", "args": {"target": target}}]}

        elif intent == "window_minimize":
            return {"steps": [{"tool": "window.minimize", "args": {}}]}

        elif intent == "window_maximize":
            return {"steps": [{"tool": "window.maximize", "args": {}}]}

        elif intent == "window_close":
            return {"steps": [{"tool": "window.close", "args": {}}]}

        elif intent == "window_arrange":
            return {"steps": [{"tool": "window.arrange", "args": {}}]}

        elif intent == "window_screenshot":
            return {"steps": [{"tool": "window.screenshot", "args": {}}]}

        elif intent == "app_install":
            app_name = self._extract_app_name(text)
            return {"steps": [{"tool": "app.install", "args": {"name": app_name}}]}

        elif intent == "app_uninstall":
            app_name = self._extract_app_name(text)
            return {"steps": [{"tool": "app.uninstall", "args": {"name": app_name}}]}

        elif intent == "app_update":
            app_name = self._extract_app_name(text)
            return {"steps": [{"tool": "app.update", "args": {"name": app_name}}]}

        elif intent == "app_restart":
            app_name = self._extract_app_name(text)
            return {"steps": [{"tool": "app.restart", "args": {"name": app_name}}]}

        elif intent == "terminal_run":
            cmd = self._extract_command(text)
            return {"steps": [{"tool": "terminal.run", "args": {"command": cmd}}]}

        elif intent == "terminal_powershell":
            cmd = self._extract_command(text)
            return {"steps": [{"tool": "terminal.powershell", "args": {"command": cmd}}]}

        elif intent == "terminal_cmd":
            cmd = self._extract_command(text)
            return {"steps": [{"tool": "terminal.cmd", "args": {"command": cmd}}]}

        elif intent == "dev_git":
            action = self._extract_git_action(text)
            return {"steps": [{"tool": "dev.git", "args": {"action": action}}]}

        elif intent == "dev_build":
            return {"steps": [{"tool": "dev.build", "args": {}}]}

        elif intent == "dev_test":
            return {"steps": [{"tool": "dev.test", "args": {}}]}

        elif intent == "dev_run":
            return {"steps": [{"tool": "dev.run", "args": {}}]}

        elif intent == "dev_docker":
            action = self._extract_docker_action(text)
            return {"steps": [{"tool": "dev.docker", "args": {"action": action}}]}

        elif intent == "ocr_screen":
            return {"steps": [{"tool": "ocr.screen", "args": {}}]}

        elif intent == "ocr_region":
            return {"steps": [{"tool": "ocr.region", "args": {}}]}

        elif intent == "vision_detect":
            target = self._extract_vision_target(text)
            return {"steps": [{"tool": "vision.detect", "args": {"target": target}}]}

        elif intent == "clipboard_copy":
            content = self._extract_content(text)
            return {"steps": [{"tool": "clipboard.copy", "args": {"content": content}}]}

        elif intent == "clipboard_paste":
            return {"steps": [{"tool": "clipboard.paste", "args": {}}]}

        elif intent == "clipboard_read":
            return {"steps": [{"tool": "clipboard.read", "args": {}}]}

        elif intent == "email_compose":
            recipient = self._extract_email_recipient(text)
            subject = self._extract_email_subject(text)
            return {
                "steps": [
                    {"tool": "email.compose", "args": {"to": recipient, "subject": subject}},
                ]
            }

        elif intent == "email_send":
            recipient = self._extract_email_recipient(text)
            subject = self._extract_email_subject(text)
            return {
                "steps": [
                    {"tool": "email.send", "args": {"to": recipient, "subject": subject}},
                ]
            }

        elif intent == "email_search":
            query = self._extract_search_query(text)
            return {"steps": [{"tool": "email.search", "args": {"query": query}}]}

        elif intent == "network_ping":
            host = self._extract_host(text)
            return {"steps": [{"tool": "network.ping", "args": {"host": host}}]}

        elif intent == "network_download":
            url = self._extract_url(text)
            return {"steps": [{"tool": "network.download", "args": {"url": url}}]}

        elif intent == "network_upload":
            path = self._extract_path(text)
            return {"steps": [{"tool": "network.upload", "args": {"path": path}}]}

        elif intent == "network_wifi":
            return {"steps": [{"tool": "network.wifi", "args": {}}]}

        elif intent == "media_screenshot":
            return {"steps": [{"tool": "media.screenshot", "args": {}}]}

        elif intent == "media_screen_record":
            return {"steps": [{"tool": "media.screen_record", "args": {}}]}

        elif intent == "media_camera":
            return {"steps": [{"tool": "system.open_app", "args": {"name": "camera"}}]}

        elif intent == "take_camera_photo":
            return {
                "steps": [
                    {"tool": "system.open_app", "args": {"name": "camera"}},
                    {"tool": "system.capture_photo", "args": {}},
                ]
            }

        elif intent == "doc_pdf_read":
            path = self._extract_path(text)
            return {"steps": [{"tool": "doc.pdf_read", "args": {"path": path}}]}

        elif intent == "doc_pdf_write":
            path = self._extract_path(text)
            return {"steps": [{"tool": "doc.pdf_write", "args": {"path": path}}]}

        elif intent == "doc_word_read":
            path = self._extract_path(text)
            return {"steps": [{"tool": "doc.word_read", "args": {"path": path}}]}

        elif intent == "doc_excel_read":
            path = self._extract_path(text)
            return {"steps": [{"tool": "doc.excel_read", "args": {"path": path}}]}

        elif intent == "doc_csv_read":
            path = self._extract_path(text)
            return {"steps": [{"tool": "doc.csv_read", "args": {"path": path}}]}

        elif intent == "memory_remember":
            value = self._extract_content(text)
            return {"steps": [{"tool": "memory.remember", "args": {"value": value}}]}

        elif intent == "memory_recall":
            key = self._extract_search_query(text)
            return {"steps": [{"tool": "memory.recall", "args": {"key": key}}]}

        elif intent == "memory_forget":
            key = self._extract_search_query(text)
            return {"steps": [{"tool": "memory.forget", "args": {"key": key}}]}

        elif intent == "task_create":
            name = self._extract_task_name(text)
            return {"steps": [{"tool": "task.create", "args": {"name": name}}]}

        elif intent == "task_run":
            name = self._extract_task_name(text)
            return {"steps": [{"tool": "task.run", "args": {"name": name}}]}

        elif intent == "task_cancel":
            name = self._extract_task_name(text)
            return {"steps": [{"tool": "task.cancel", "args": {"name": name}}]}

        elif intent == "research_collect":
            query = self._extract_search_query(text)
            return {"steps": [{"tool": "research.collect", "args": {"query": query}}]}

        elif intent == "research_summarize":
            return {"steps": [{"tool": "research.summarize", "args": {}}]}

        elif intent == "send_email":
            recipient = self._extract_email_recipient(text)
            subject = self._extract_email_subject(text)
            return {
                "steps": [
                    {"tool": "email.compose", "args": {"to": recipient, "subject": subject}},
                    {"tool": "email.send", "args": {"to": recipient, "subject": subject}},
                ]
            }

        else:
            suggestions = self._suggest_intents(text)
            err = f"Unknown intent: {intent}"
            if suggestions:
                err += f". Did you mean: {', '.join(suggestions)}?"
            return {
                "steps": [],
                "error": err,
                "suggestions": suggestions,
            }

    def _suggest_intents(self, text: str, limit: int = 5) -> List[str]:
        """Return up to `limit` intent names that are closest to `text`."""
        text_lower = (text or "").lower().strip()
        tokens = set(re.findall(r"[a-z]+", text_lower))
        if not tokens:
            return []
        scored: List[Tuple[str, float]] = []
        for intent, patterns in self.intent_patterns.items():
            kw: set = set()
            for p in patterns:
                kw.update(re.findall(r"[a-z]+", p.pattern.lower()))
            if not kw:
                continue
            overlap = len(tokens & kw)
            if overlap == 0:
                continue
            score = overlap / max(1, len(kw))
            scored.append((intent, score))
        scored.sort(key=lambda kv: -kv[1])
        return [name for name, _ in scored[:limit]]

    # ------------------------------------------------------------------
    # Cognitive Planner v1.0 methods
    # ------------------------------------------------------------------
    async def create_cognitive_plan(self, text: str) -> Dict[str, Any]:
        """Create a full cognitive plan with all metadata.

        Returns the complete planning output:
        - intent
        - required entities
        - execution graph (steps)
        - pipelines
        - models
        - dependencies
        - verification steps
        - recovery plan
        - confidence score
        - risk score
        - canonical actions
        - wait strategies
        - autonomous steps
        """
        # Run cognitive pipeline
        cognitive = cognitive_pipeline(text)
        # Classify intent
        intent = await self.classify_intent(text)
        # Create base plan
        plan = await self.create_plan(text, intent)
        # Compute confidence and risk
        confidence = compute_confidence(text, intent)
        risk = compute_risk(intent)
        # Get required models
        models = get_required_models(intent)
        # Get verification steps
        verification = get_verification_steps(intent)
        # Get recovery strategies
        recovery = get_recovery_strategies(intent)
        # Get wait strategies
        wait_strategies = get_wait_strategy(intent)
        # Get autonomous steps
        autonomous_steps = infer_autonomous_steps(intent)
        # Get canonical actions
        canonical_actions = cognitive.get("canonical_actions", [])
        # Build dependencies from steps
        steps = plan.get("steps", [])
        dependencies = []
        for i in range(1, len(steps)):
            dependencies.append({
                "from": steps[i - 1].get("tool", f"step_{i-1}"),
                "to": steps[i].get("tool", f"step_{i}"),
            })
        # Build pipelines list
        pipelines = []
        for step in steps:
            tool = step.get("tool", "")
            if tool:
                pipeline_domain = tool.split(".")[0] if "." in tool else "system"
                pipelines.append({
                    "step": tool,
                    "domain": pipeline_domain,
                })
        # Update task context
        ctx = get_task_context()
        if intent in ("open_app", "browser_open", "open_website"):
            app_name = self._extract_app_name(text)
            ctx.update(app=app_name, last_action=intent, last_target=app_name)
        elif intent in ("browser_search", "browser_navigate"):
            url = self._extract_url(text)
            ctx.update(url=url, last_action=intent, last_target=url)
        return {
            "intent": intent,
            "entities": self._extract_entities(text, intent),
            "execution_graph": steps,
            "pipelines": pipelines,
            "models": models,
            "dependencies": dependencies,
            "verification_steps": verification,
            "recovery_plan": recovery,
            "confidence_score": confidence,
            "risk_score": risk,
            "canonical_actions": [
                {"action": a, "phrase": p} for a, p in canonical_actions
            ],
            "wait_strategies": wait_strategies,
            "autonomous_steps": autonomous_steps,
            "cognitive": {
                "original": cognitive["original"],
                "spelling_corrected": cognitive["spelling_corrected"],
                "alias_resolved": cognitive["alias_resolved"],
                "synonym_expanded": cognitive["synonym_expanded"],
            },
            "context": {
                "active_app": ctx.get_active_app(),
                "active_url": ctx.get_active_url(),
                "workflow": ctx.workflow,
            },
        }

    def _extract_entities(self, text: str, intent: str) -> Dict[str, Any]:
        """Extract entities from text based on intent."""
        entities: Dict[str, Any] = {}
        if intent in ("open_app", "browser_open", "close_app", "app_install",
                       "app_uninstall", "app_update", "app_restart",
                       "window_focus", "window_switch"):
            entities["app_name"] = self._extract_app_name(text)
        elif intent in ("open_website", "browser_navigate"):
            entities["url"] = self._extract_url(text)
        elif intent in ("search_web", "browser_search", "research_collect",
                         "email_search", "file_search"):
            entities["query"] = self._extract_search_query(text)
        elif intent in ("file_read", "file_write", "file_rename",
                         "file_move", "file_copy", "file_compress",
                         "file_extract", "file_backup", "doc_pdf_read",
                         "doc_pdf_write", "doc_word_read", "doc_excel_read",
                         "doc_csv_read"):
            entities["path"] = self._extract_path(text)
        elif intent in ("file_rename", "file_move", "file_copy"):
            src, dst = self._extract_rename_pair(text)
            entities["src"] = src
            entities["dst"] = dst
        elif intent in ("terminal_run", "terminal_powershell",
                         "terminal_cmd", "run_command"):
            entities["command"] = self._extract_command(text)
        elif intent in ("login",):
            entities["site"] = self._extract_site(text)
        elif intent in ("send_email", "email_compose", "email_send"):
            entities["recipient"] = self._extract_email_recipient(text)
            entities["subject"] = self._extract_email_subject(text)
        elif intent in ("network_ping",):
            entities["host"] = self._extract_host(text)
        elif intent in ("take_camera_photo",):
            entities["save_dir"] = None
        elif intent in ("network_download", "download_file"):
            entities["url"] = self._extract_url(text)
        elif intent in ("network_upload",):
            entities["path"] = self._extract_path(text)
        elif intent in ("screen_click",):
            entities["target_text"] = self._extract_click_text(text)
        elif intent in ("vision_detect",):
            entities["target"] = self._extract_vision_target(text)
        elif intent in ("dev_git",):
            entities["action"] = self._extract_git_action(text)
        elif intent in ("dev_docker",):
            entities["action"] = self._extract_docker_action(text)
        elif intent in ("task_create", "task_run", "task_cancel"):
            entities["task_name"] = self._extract_task_name(text)
        elif intent in ("memory_remember", "file_write"):
            entities["content"] = self._extract_content(text)
        elif intent in ("memory_recall", "memory_forget"):
            entities["key"] = self._extract_search_query(text)
        elif intent in ("keep_awake", "mouse_jiggle"):
            entities["minutes"] = self._extract_minutes(text) or 60
        elif intent in ("open_settings",):
            entities["page"] = self._extract_settings_page(text)
        elif intent in ("close_all_apps",):
            entities["keep_names"] = self._extract_keep_names(text)
        return entities

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _extract_close_target(self, text: str) -> str:
        text_lower = text.lower().strip()
        for alias in sorted(APP_NAME_ALIASES.keys(), key=len, reverse=True):
            if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
                return APP_NAME_ALIASES[alias]
        words = re.findall(r"[a-zA-Z]+", text_lower)
        return words[-1] if words else "chrome"

    def _extract_keep_names(self, text: str) -> List[str]:
        text_lower = text.lower().strip()
        keep: List[str] = []
        m = re.search(r"\bkeep\s+([a-zA-Z0-9 .]+?)\s+(open|running|alive)\b", text_lower)
        if m:
            for alias in APP_NAME_ALIASES:
                if re.search(r"\b" + re.escape(alias) + r"\b", m.group(1)):
                    keep.append(APP_NAME_ALIASES[alias])
        m = re.search(r"\b(except|but\s+not|excluding)\s+([a-zA-Z0-9 .]+)", text_lower)
        if m:
            for alias in APP_NAME_ALIASES:
                if re.search(r"\b" + re.escape(alias) + r"\b", m.group(2)):
                    keep.append(APP_NAME_ALIASES[alias])
        return sorted(set(keep))

    def _extract_minutes(self, text: str) -> Optional[int]:
        m = re.search(r"\bfor\s+(\d+)\s*(minute|min|hour|hr)s?\b", text.lower())
        if m:
            n = int(m.group(1))
            if "hour" in m.group(2) or "hr" in m.group(2):
                return n * 60
            return n
        return None

    def _extract_settings_page(self, text: str) -> str:
        text_lower = text.lower()
        page_map = {
            "display": "ms-settings:display",
            "sound": "ms-settings:sound",
            "network": "ms-settings:network",
            "wifi": "ms-settings:network-wifi",
            "bluetooth": "ms-settings:bluetooth",
            "personalization": "ms-settings:personalization",
            "background": "ms-settings:personalization-background",
            "theme": "ms-settings:themes",
            "themes": "ms-settings:themes",
            "privacy": "ms-settings:privacy",
            "update": "ms-settings:windowsupdate",
            "storage": "ms-settings:storagesense",
            "battery": "ms-settings:batterysaver",
            "power": "ms-settings:power",
            "accounts": "ms-settings:accounts",
            "cortana": "ms-settings:cortana",
            "time": "ms-settings:dateandtime",
            "language": "ms-settings:language",
            "keyboard": "ms-settings:keyboard",
            "mouse": "ms-settings:mouse",
            "touchpad": "ms-settings:devices-touchpad",
            "apps": "ms-settings:appsfeatures",
            "default apps": "ms-settings:defaultapps",
            "startup": "ms-settings:startupapps",
            "contrast": "ms-settings:easeofaccess-highcontrast",
            "magnifier": "ms-settings:easeofaccess-magnifier",
            "narrator": "ms-settings:easeofaccess-narrator",
        }
        for key, uri in page_map.items():
            if re.search(r"\b" + re.escape(key) + r"\b", text_lower):
                return uri
        return "ms-settings:"

    def _extract_path(self, text: str) -> str:
        patterns = [
            r"[Cc]:\\[^\s]+",
            r"/[^\s]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        if "download" in text.lower():
            return "C:\\Users\\brigh\\Downloads"
        elif "desktop" in text.lower():
            return "C:\\Users\\brigh\\Desktop"
        elif "documents" in text.lower():
            return "C:\\Users\\brigh\\Documents"
        return "."

    def _extract_app_name(self, text: str) -> str:
        text_lower = text.lower()
        known_phrases = [
            "opera gx browser", "opera gx", "gx browser",
            "google chrome", "microsoft edge", "visual studio code", "vs code",
        ]
        for phrase in known_phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", text_lower):
                return phrase
        text_clean = re.sub(
            r"^\s*(open|launch|start|run|fire\s*up|boot(\s*up)?|bring\s*up|go\s+to|navigate\s+to|visit)\b",
            "", text, flags=re.IGNORECASE
        ).strip()
        text_clean = re.split(
            r"\b(and|then|after that|go to|search|stay|keep|for)\b",
            text_clean, maxsplit=1, flags=re.IGNORECASE,
        )[0].strip()
        text_clean = re.sub(
            r"\b(app|application|program)\b", " ", text_clean, flags=re.IGNORECASE
        )
        text_clean = re.sub(r"\s+", " ", text_clean).strip(" .,:;\"'")
        words = text_clean.split()
        return " ".join(words[:4]) if words else "unknown"

    def _extract_url(self, text: str) -> str:
        url_match = re.search(r"https?://\S+", text)
        if url_match:
            return url_match.group(0)
        domain_match = re.search(
            r"\b([a-zA-Z0-9-]+\.(com|org|net|io|gov|edu))\b", text
        )
        if domain_match:
            return f"https://{domain_match.group(0)}"
        text_lower = text.lower()
        for name, url in self.SITE_ALIASES.items():
            if re.search(rf"\b{name}\b", text_lower):
                return url
        return "https://www.google.com"

    def _extract_search_query(self, text: str) -> str:
        query = re.sub(
            r"\b(search|google|find|look up|lookup|for|on the web|online)\b",
            "", text, flags=re.IGNORECASE,
        ).strip()
        query = re.sub(
            r"\b(in|on|with)\s+(chrome|edge|browser|google|bing)\b",
            "", query, flags=re.IGNORECASE,
        ).strip()
        query = re.sub(r"\s+", " ", query).strip(" ?.")
        return query or text.strip()

    def _extract_site(self, text: str) -> str:
        match = re.search(r"\bto\s+([a-zA-Z0-9.-]+\.[a-z]{2,})", text)
        if match:
            return f"https://{match.group(1)}"
        return "https://www.google.com"

    def _extract_click_text(self, text: str) -> str:
        cleaned = re.sub(
            r"\b(click|press|tap|select|button|link|tab|field|on|the)\b",
            " ", text, flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:\"'")
        return cleaned or text.strip()

    def _extract_content(self, text: str) -> str:
        """Extract content from a write/remember command."""
        m = re.search(r"\b(saying|with|that|content|text)\s+[\"']?(.+?)[\"']?$",
                      text, flags=re.IGNORECASE)
        if m:
            return m.group(2).strip()
        return text.strip()

    def _extract_rename_pair(self, text: str) -> Tuple[str, str]:
        """Extract (src, dst) from a rename command."""
        m = re.search(r"\b(rename|move)\b\s+(.+?)\s+(to|as)\s+(.+)", text,
                      flags=re.IGNORECASE)
        if m:
            return m.group(2).strip(), m.group(4).strip()
        return self._extract_path(text), self._extract_path(text)

    def _extract_move_pair(self, text: str) -> Tuple[str, str]:
        return self._extract_rename_pair(text)

    def _extract_command(self, text: str) -> str:
        """Extract a shell command from text."""
        m = re.search(r"\b(run|execute)\b\s+(.+)", text, flags=re.IGNORECASE)
        if m:
            return m.group(2).strip()
        return text.strip()

    def _extract_git_action(self, text: str) -> str:
        text_lower = text.lower()
        for action in ["clone", "commit", "push", "pull", "branch", "merge", "status"]:
            if action in text_lower:
                return action
        return "status"

    def _extract_docker_action(self, text: str) -> str:
        text_lower = text.lower()
        for action in ["build", "run", "compose", "up", "down", "stop", "start"]:
            if action in text_lower:
                return action
        return "run"

    def _extract_vision_target(self, text: str) -> str:
        text_lower = text.lower()
        for target in ["button", "icon", "image", "logo", "color", "cursor",
                        "object", "text", "window", "form"]:
            if target in text_lower:
                return target
        return "object"

    def _extract_email_recipient(self, text: str) -> str:
        m = re.search(r"\bto\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,})", text)
        if m:
            return m.group(1)
        return ""

    def _extract_email_subject(self, text: str) -> str:
        m = re.search(r"\b(subject|about|re)\s+[\"']?(.+?)[\"']?$", text,
                      flags=re.IGNORECASE)
        if m:
            return m.group(2).strip()
        return ""

    def _extract_host(self, text: str) -> str:
        m = re.search(r"\bping\s+(\S+)", text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
        domain_match = re.search(
            r"\b([a-zA-Z0-9-]+\.(com|org|net|io|gov|edu))\b", text
        )
        if domain_match:
            return domain_match.group(0)
        return "8.8.8.8"

    def _extract_task_name(self, text: str) -> str:
        text_clean = re.sub(
            r"^\s*(create|make|add|run|execute|start|cancel|abort|stop)\b",
            "", text, flags=re.IGNORECASE,
        ).strip()
        text_clean = re.sub(
            r"\b(task|workflow|job)\b", " ", text_clean, flags=re.IGNORECASE
        )
        return re.sub(r"\s+", " ", text_clean).strip(" .,:;\"'") or "task"
