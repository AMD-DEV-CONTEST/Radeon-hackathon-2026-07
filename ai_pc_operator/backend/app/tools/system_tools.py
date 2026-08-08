"""System tools - status, disk, RAM, processes, app control."""

from __future__ import annotations

import psutil
import asyncio
import ctypes
import ctypes.wintypes
import difflib
import json
import platform
import re
import shlex
import subprocess
import shutil
import time
import os
from pathlib import Path
from typing import Dict, Any, List, Optional


class SystemTools:
    """System control tools."""

    APP_ALIASES = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "edge": "msedge",
        "microsoft edge": "msedge",
        "firefox": "firefox",
        "opera": "opera",
        "opera browser": "opera",
        "opera gx": "opera-gx",
        "opera gx browser": "opera-gx",
        "gx": "opera-gx",
        "gx browser": "opera-gx",
        "camera": "camera",
        "windows camera": "camera",
        "nexa": "nexa",
        "nexa app": "nexa",
        "snakelite": "snakelite",
        "snake lite": "snakelite",
        "notepad": "notepad",
        "calculator": "calc",
        "calc": "calc",
        "explorer": "explorer",
        "paint": "mspaint",
        "cmd": "cmd",
        "powershell": "powershell",
        "terminal": "wt",
        "visual studio code": "code",
        "vs code": "code",
        "vscode": "code",
        "excel": "excel",
        "word": "winword",
        "powerpoint": "powerpnt",
    }

    WINDOWS_URI_APPS = {
        "camera": "microsoft.windows.camera:",
    }

    WINDOWS_APP_PATHS = {
        "opera-gx": [
            r"%LOCALAPPDATA%\Programs\Opera GX\launcher.exe",
            r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe",
            r"%PROGRAMFILES%\Opera GX\launcher.exe",
            r"%PROGRAMFILES%\Opera GX\opera.exe",
            r"%PROGRAMFILES(X86)%\Opera GX\launcher.exe",
            r"%PROGRAMFILES(X86)%\Opera GX\opera.exe",
        ],
        "opera": [
            r"%LOCALAPPDATA%\Programs\Opera\launcher.exe",
            r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
            r"%PROGRAMFILES%\Opera\launcher.exe",
            r"%PROGRAMFILES%\Opera\opera.exe",
        ],
    }

    SHORTCUT_SEARCH_DIRS = [
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
        r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs",
        r"%USERPROFILE%\Desktop",
        r"%PUBLIC%\Desktop",
    ]

    EXE_SEARCH_DIRS = [
        r"%LOCALAPPDATA%\Programs",
        r"%PROGRAMFILES%",
        r"%PROGRAMFILES(X86)%",
    ]

    COMMON_SEARCH_DIRS = SHORTCUT_SEARCH_DIRS + EXE_SEARCH_DIRS

    APP_MATCH_STOPWORDS = {
        "app",
        "application",
        "program",
        "browser",
        "desktop",
        "windows",
    }

    _app_index_cache: list[dict[str, Any]] | None = None
    _app_index_cache_time: float = 0.0
    _app_index_ttl_seconds = 300.0

    async def status(self) -> Dict[str, Any]:
        """Get system status."""
        return {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "hostname": platform.node(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "cpu_count": psutil.cpu_count(),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_total_gb": round(
                psutil.virtual_memory().total / (1024**3), 2
            ),
            "memory_available_gb": round(
                psutil.virtual_memory().available / (1024**3), 2
            ),
            "disk_percent": psutil.disk_usage("/").percent,
            "disk_total_gb": round(
                psutil.disk_usage("/").total / (1024**3), 2
            ),
            "disk_free_gb": round(
                psutil.disk_usage("/").free / (1024**3), 2
            ),
            "boot_time": psutil.boot_time(),
            "uptime_seconds": (
                time.time() - psutil.boot_time()
            ),
        }

    async def get_status(self) -> Dict[str, Any]:
        """Alias for status."""
        return await self.status()

    async def disk_usage(self) -> Dict[str, Any]:
        """Get disk usage."""
        usage = psutil.disk_usage("/")
        return {
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "percent": usage.percent,
        }

    async def ram_usage(self) -> Dict[str, Any]:
        """Get RAM usage."""
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
        }

    async def processes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get running processes."""
        procs = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent"]
        ):
            try:
                procs.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Sort by memory usage
        procs.sort(
            key=lambda x: x.get("memory_percent", 0), reverse=True
        )
        return procs[:limit]

    async def open_app(self, name: str, target: str | None = None) -> Dict[str, Any]:
        """Open an application."""
        try:
            match = self._resolve_app_match(name)
            self._launch_app_match(match, target)
            return {
                "status": "success",
                "message": f"Opened {match['display_name']}" + (f" with {target}" if target else ""),
                "resolved": {
                    "query": name,
                    "display_name": match["display_name"],
                    "launch_type": match["launch_type"],
                    "confidence": match["confidence"],
                    "source": match["source"],
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def kill_process(self, pid: int) -> Dict[str, Any]:
        """Kill a process by PID."""
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            return {
                "status": "success",
                "message": f"Killed process {pid}",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def close_app(self, name: str, force: bool = False) -> Dict[str, Any]:
        """Close a single application by friendly name (e.g. 'chrome', 'notepad').

        Uses psutil to find processes whose name matches the alias and closes
        their top-level windows gracefully (WM_CLOSE) before falling back to
        terminate/kill when force=True.
        """
        try:
            if not name or not name.strip():
                return {"status": "failed", "error": "App name is required"}

            cleaned = name.strip().lower()
            alias = self.APP_ALIASES.get(cleaned, cleaned.split()[0])
            # Map common aliases to process names
            process_names = self._app_alias_to_process_names(alias)

            closed: List[Dict[str, Any]] = []
            skipped: List[Dict[str, Any]] = []
            for proc in psutil.process_iter(["pid", "name"]):
                pname = (proc.info.get("name") or "").lower()
                if not pname:
                    continue
                pbase = pname.replace(".exe", "")
                if pbase in process_names or any(
                    pbase.startswith(pn) for pn in process_names
                ):
                    try:
                        if not force and platform.system().lower() == "windows":
                            self._close_windows_for_pid(proc.info["pid"])
                        proc.terminate()
                        closed.append({"pid": proc.info["pid"], "name": pname})
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        skipped.append({"pid": proc.info["pid"], "name": pname, "reason": "access_denied"})
                    except Exception as e:
                        skipped.append({"pid": proc.info["pid"], "name": pname, "reason": str(e)})

            if not closed and not skipped:
                return {
                    "status": "failed",
                    "error": f"No running processes matched '{name}'",
                    "searched": process_names,
                }

            return {
                "status": "success",
                "message": f"Closed {len(closed)} process(es) for '{name}'",
                "closed": closed,
                "skipped": skipped,
                "force": force,
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def close_all_apps(
        self,
        exclude_system: bool = True,
        keep_names: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Close all user applications.

        - exclude_system=True keeps critical system processes alive
          (explorer, dwm, winlogon, csrss, services, lsass, smss, svchost,
          taskmgr, and the current python/uvicorn process).
        - keep_names is an extra list of process basenames to never close
          (e.g. ['code', 'chrome'] to keep VS Code and Chrome open).
        - force=True escalates terminate() to kill() when a process refuses
          to exit.
        """
        try:
            SYSTEM_PROCESSES = {
                "explorer", "dwm", "winlogon", "csrss", "services",
                "lsass", "smss", "svchost", "taskmgr", "system",
                "registry", "sihclient", "fontdrvhost", "wininit",
            }
            current_pid = os.getpid()
            keep = set(n.lower().replace(".exe", "") for n in (keep_names or []))

            closed: List[Dict[str, Any]] = []
            skipped: List[Dict[str, Any]] = []
            for proc in psutil.process_iter(["pid", "name"]):
                pname = (proc.info.get("name") or "").lower()
                pbase = pname.replace(".exe", "")
                if not pbase:
                    continue
                if proc.info["pid"] == current_pid:
                    continue
                if exclude_system and pbase in SYSTEM_PROCESSES:
                    continue
                if pbase in keep:
                    continue
                # Skip our own backend python process
                if pbase in {"python", "pythonw", "uvicorn"}:
                    try:
                        cmdline = " ".join(proc.cmdline() or []).lower()
                        if "ai_pc_operator" in cmdline or "uvicorn" in cmdline or "app.main" in cmdline:
                            continue
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        continue
                try:
                    if not force and platform.system().lower() == "windows":
                        self._close_windows_for_pid(proc.info["pid"])
                    proc.terminate()
                    closed.append({"pid": proc.info["pid"], "name": pname})
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    skipped.append({"pid": proc.info["pid"], "name": pname, "reason": "access_denied"})
                except Exception as e:
                    skipped.append({"pid": proc.info["pid"], "name": pname, "reason": str(e)})

            return {
                "status": "success",
                "message": f"Closed {len(closed)} application(s)",
                "closed_count": len(closed),
                "skipped_count": len(skipped),
                "closed_sample": closed[:20],
                "skipped_sample": skipped[:10],
                "excluded_system": exclude_system,
                "kept": sorted(keep),
                "force": force,
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def _app_alias_to_process_names(self, alias: str) -> set:
        """Map an app alias to a set of process basenames to look for."""
        alias = alias.lower().replace(".exe", "")
        mapping = {
            "chrome": {"chrome"},
            "msedge": {"msedge", "microsoftedge"},
            "firefox": {"firefox"},
            "opera": {"opera"},
            "opera-gx": {"opera", "opera_gx"},
            "notepad": {"notepad"},
            "calc": {"calculatorapp", "calc"},
            "explorer": {"explorer"},
            "mspaint": {"mspaint"},
            "code": {"code"},
            "excel": {"excel"},
            "winword": {"winword"},
            "powerpnt": {"powerpnt"},
            "cmd": {"cmd"},
            "powershell": {"powershell", "pwsh"},
            "wt": {"windowsterminal", "wt"},
            "camera": {"windowscamera"},
        }
        names = mapping.get(alias, {alias})
        return names

    def _close_windows_for_pid(self, pid: int) -> None:
        """Send WM_CLOSE to all top-level windows owned by pid (Windows only)."""
        if platform.system().lower() != "windows":
            return
        try:
            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
            PostMessageW = ctypes.windll.user32.PostMessageW
            WM_CLOSE = 0x0010

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            def enum_proc(hwnd, _lparam):
                owner_pid = ctypes.c_int()
                GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
                if owner_pid.value == pid:
                    PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True

            EnumWindows(enum_proc, 0)
        except Exception:
            # Best-effort; terminate() will still run.
            pass

    async def network_status(self) -> Dict[str, Any]:
        """Get network status."""
        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }

    async def capture_photo(self, save_dir: Optional[str] = None) -> Dict[str, Any]:
        """Capture a photo from the webcam (Windows dshow via ffmpeg if available).

        Follows the v2.0 camera policy: graceful failure with a clear message
        when no capture backend is available, never fabricates success.
        """
        return await asyncio.to_thread(self._capture_photo_sync, save_dir)

    def _capture_photo_sync(self, save_dir: Optional[str] = None) -> Dict[str, Any]:
        if platform.system().lower() != "windows":
            return {
                "status": "failed",
                "error": "photo capture is only supported on Windows (dshow)",
            }

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {
                "status": "failed",
                "error": (
                    "Camera opened, but photo capture needs ffmpeg with dshow "
                    "support (install ffmpeg and a webcam driver, then retry)."
                ),
                "hint": "install ffmpeg: winget install ffmpeg",
            }

        save_path = self._photo_save_path(save_dir)
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "dshow",
                    "-i", "video=Camera",
                    "-frames:v", "1",
                    str(save_path),
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception as e:
            return {
                "status": "failed",
                "error": f"photo capture failed: {e}",
            }

        if not save_path.exists() or save_path.stat().st_size == 0:
            return {
                "status": "failed",
                "error": (
                    "Camera opened, but the capture produced no image. The "
                    "webcam may be in use or the device name differs."
                ),
            }

        return {
            "status": "success",
            "path": str(save_path),
            "bytes": save_path.stat().st_size,
        }

    def _photo_save_path(self, save_dir: Optional[str]) -> Path:
        base = (
            Path(save_dir)
            if save_dir
            else Path(os.environ.get("SCREEN_AI_DATA_DIR", "") or "").resolve()
            if os.environ.get("SCREEN_AI_DATA_DIR", "")
            else Path.home() / "Pictures"
        )
        base = base / "screen_ai_photos"
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return base / f"photo_{stamp}.jpg"

    async def open_settings(self, page: str = "ms-settings:") -> Dict[str, Any]:
        """Open a Windows Settings page."""
        try:
            if not page.startswith("ms-settings:"):
                page = "ms-settings:"
            subprocess.Popen(["explorer.exe", page])
            return {"status": "success", "page": page}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def shutdown(self, delay_seconds: int = 0) -> Dict[str, Any]:
        """Shut down the PC (Windows only). HIGH RISK - requires approval."""
        try:
            if platform.system().lower() != "windows":
                return {"status": "failed", "error": "shutdown is Windows only"}
            subprocess.Popen(
                ["shutdown", "/s", "/t", str(max(0, int(delay_seconds)))]
            )
            return {
                "status": "success",
                "action": "shutdown",
                "delay_seconds": int(delay_seconds),
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def restart(self, delay_seconds: int = 0) -> Dict[str, Any]:
        """Restart the PC (Windows only). HIGH RISK - requires approval."""
        try:
            if platform.system().lower() != "windows":
                return {"status": "failed", "error": "restart is Windows only"}
            subprocess.Popen(
                ["shutdown", "/r", "/t", str(max(0, int(delay_seconds)))]
            )
            return {
                "status": "success",
                "action": "restart",
                "delay_seconds": int(delay_seconds),
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def lock(self) -> Dict[str, Any]:
        """Lock the workstation (Windows only)."""
        try:
            if platform.system().lower() != "windows":
                return {"status": "failed", "error": "lock is Windows only"}
            ctypes.windll.user32.LockWorkStation()
            return {"status": "success", "action": "lock"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def keep_awake(self, minutes: int = 60) -> Dict[str, Any]:
        """Prevent system/display sleep for a bounded duration."""
        minutes = max(1, min(int(minutes), 120))
        if platform.system().lower() != "windows":
            return {
                "status": "failed",
                "error": "keep_awake is currently implemented for Windows only",
            }

        async def hold_awake() -> None:
            es_continuous = 0x80000000
            es_system_required = 0x00000001
            es_display_required = 0x00000002
            flags = es_continuous | es_system_required | es_display_required
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            try:
                await asyncio.sleep(minutes * 60)
            finally:
                ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)

        asyncio.create_task(hold_awake())
        return {
            "status": "success",
            "minutes": minutes,
            "method": "SetThreadExecutionState",
        }

    async def mouse_jiggle(
        self,
        minutes: int = 60,
        interval_seconds: int = 45,
    ) -> Dict[str, Any]:
        """Move the mouse slightly for a bounded duration when explicitly asked."""
        minutes = max(1, min(int(minutes), 120))
        interval_seconds = max(10, min(int(interval_seconds), 300))
        if platform.system().lower() != "windows":
            return {
                "status": "failed",
                "error": "mouse_jiggle is currently implemented for Windows only",
            }

        async def jiggle() -> None:
            point = ctypes.wintypes.POINT()
            end_at = time.monotonic() + (minutes * 60)
            direction = 1
            while time.monotonic() < end_at:
                ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
                ctypes.windll.user32.SetCursorPos(point.x + direction, point.y)
                await asyncio.sleep(0.05)
                ctypes.windll.user32.SetCursorPos(point.x, point.y)
                direction *= -1
                await asyncio.sleep(interval_seconds)

        asyncio.create_task(jiggle())
        return {
            "status": "success",
            "minutes": minutes,
            "interval_seconds": interval_seconds,
            "message": f"Mouse movement scheduled for {minutes} minute(s)",
        }

    async def run_command(self, command: str) -> Dict[str, Any]:
        """Run a shell command (HIGH RISK)."""
        try:
            args = shlex.split(command, posix=False)
            if not args:
                return {"status": "failed", "error": "Empty command"}
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "status": "success",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    def _resolve_app(self, name: str) -> str:
        """Resolve a natural app name to a safe executable name."""
        return self._resolve_app_match(name)["launch_value"]

    def _resolve_app_match(self, name: str) -> dict[str, Any]:
        """Resolve a natural app name to a launchable app match."""
        cleaned = re.sub(r"[^a-zA-Z0-9_. -]", "", name).strip().lower()
        if not cleaned:
            raise ValueError("App name is empty after sanitization")

        alias = self.APP_ALIASES.get(cleaned, cleaned.split()[0])

        found = shutil.which(alias)
        if found:
            return self._app_match(
                display_name=cleaned,
                launch_type="exe",
                launch_value=found,
                confidence=1.0,
                source="path",
            )

        for candidate in self.WINDOWS_APP_PATHS.get(alias, []):
            expanded = Path(os.path.expandvars(candidate))
            if expanded.exists():
                return self._app_match(
                    display_name=cleaned,
                    launch_type="exe",
                    launch_value=str(expanded),
                    confidence=1.0,
                    source="known-path",
                )

        if alias in self.WINDOWS_URI_APPS:
            return self._app_match(
                display_name=cleaned,
                launch_type="uri",
                launch_value=self.WINDOWS_URI_APPS[alias],
                confidence=1.0,
                source="windows-uri",
            )

        discovered = self._best_discovered_app_match(cleaned, alias)
        if discovered:
            return discovered

        if alias in self.APP_ALIASES.values():
            found = shutil.which(alias)
            if found:
                return self._app_match(cleaned, "exe", found, 0.95, "path")

        raise ValueError(f"Unknown or unavailable app: {name}")

    def _launch_app_match(self, match: dict[str, Any], target: str | None = None) -> None:
        """Launch a resolved app match with the safest available method."""
        launch_type = match["launch_type"]
        launch_value = match["launch_value"]
        if launch_type == "uri":
            os.startfile(launch_value)  # type: ignore[attr-defined]
            return
        if launch_type == "appx":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{launch_value}"])
            return
        if launch_type in {"shortcut", "url"}:
            os.startfile(launch_value)  # type: ignore[attr-defined]
            return
        args = [launch_value]
        if target:
            args.append(target)
        subprocess.Popen(args)

    def _best_discovered_app_match(self, cleaned: str, alias: str) -> dict[str, Any] | None:
        queries = {cleaned, alias, self._normalize_app_name(cleaned), self._normalize_app_name(alias)}
        queries = {query for query in queries if query}
        candidates = self._discover_apps()
        best: dict[str, Any] | None = None
        best_score = 0.0

        for candidate in candidates:
            names = {
                candidate["name"],
                candidate["normalized_name"],
                candidate["stem"],
                candidate["normalized_stem"],
            }
            score = max(self._score_app_match(query, option) for query in queries for option in names)
            if score > best_score:
                best = candidate
                best_score = score

        if not best or best_score < 0.91:
            return None

        return self._app_match(
            display_name=best["display_name"],
            launch_type=best["launch_type"],
            launch_value=best["launch_value"],
            confidence=round(best_score, 3),
            source=best["source"],
        )

    def _discover_apps(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if (
            self._app_index_cache is not None
            and now - self._app_index_cache_time < self._app_index_ttl_seconds
        ):
            return self._app_index_cache

        candidates: list[dict[str, Any]] = []
        candidates.extend(self._discover_shortcuts())
        candidates.extend(self._discover_appx())
        self._app_index_cache = candidates
        self._app_index_cache_time = now
        return candidates

    def _discover_shortcuts(self) -> list[dict[str, Any]]:
        apps: list[dict[str, Any]] = []
        shortcut_suffixes = {".lnk": "shortcut", ".appref-ms": "shortcut", ".url": "url"}
        exe_suffixes = {".exe": "exe"}
        for raw_dir in self.SHORTCUT_SEARCH_DIRS:
            root = Path(os.path.expandvars(raw_dir))
            if not root.exists():
                continue
            for path in self._iter_app_paths(root, shortcut_suffixes, max_depth=8, max_items=700):
                stem = path.stem
                apps.append(
                    {
                        "display_name": stem,
                        "name": stem.lower(),
                        "normalized_name": self._normalize_app_name(stem),
                        "stem": stem.lower(),
                        "normalized_stem": self._normalize_app_name(stem),
                        "launch_type": shortcut_suffixes[path.suffix.lower()],
                        "launch_value": str(path),
                        "source": "start-menu" if "start menu" in str(root).lower() else "filesystem",
                    }
                )
        for raw_dir in self.EXE_SEARCH_DIRS:
            root = Path(os.path.expandvars(raw_dir))
            if not root.exists():
                continue
            for path in self._iter_app_paths(root, exe_suffixes, max_depth=3, max_items=180):
                stem = path.stem
                apps.append(
                    {
                        "display_name": stem,
                        "name": stem.lower(),
                        "normalized_name": self._normalize_app_name(stem),
                        "stem": stem.lower(),
                        "normalized_stem": self._normalize_app_name(stem),
                        "launch_type": exe_suffixes[path.suffix.lower()],
                        "launch_value": str(path),
                        "source": "filesystem",
                    }
                )
        return apps

    def _iter_app_paths(
        self,
        root: Path,
        suffixes: dict[str, str],
        max_depth: int,
        max_items: int,
    ) -> list[Path]:
        found: list[Path] = []
        deadline = time.monotonic() + 1.25
        stack: list[tuple[Path, int]] = [(root, 0)]
        try:
            while stack and len(found) < max_items and time.monotonic() < deadline:
                current, depth = stack.pop()
                if depth > max_depth:
                    continue
                try:
                    entries = list(current.iterdir())
                except (OSError, PermissionError):
                    continue
                for path in entries:
                    if len(found) >= max_items or time.monotonic() >= deadline:
                        break
                    try:
                        if path.is_file() and path.suffix.lower() in suffixes:
                            found.append(path)
                        elif path.is_dir() and depth < max_depth:
                            stack.append((path, depth + 1))
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return found

    def _discover_appx(self) -> list[dict[str, Any]]:
        if platform.system().lower() != "windows":
            return []
        try:
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=4,
            ).strip()
        except Exception:
            return []
        if not output:
            return []
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return []
        rows = parsed if isinstance(parsed, list) else [parsed]
        apps: list[dict[str, Any]] = []
        for row in rows:
            name = str(row.get("Name", "")).strip()
            app_id = str(row.get("AppID", "")).strip()
            if not name or not app_id:
                continue
            apps.append(
                {
                    "display_name": name,
                    "name": name.lower(),
                    "normalized_name": self._normalize_app_name(name),
                    "stem": name.lower(),
                    "normalized_stem": self._normalize_app_name(name),
                    "launch_type": "appx",
                    "launch_value": app_id,
                    "source": "start-apps",
                }
            )
        return apps

    def _score_app_match(self, query: str, option: str) -> float:
        query = self._normalize_app_name(query)
        option = self._normalize_app_name(option)
        if not query or not option:
            return 0.0
        if query == option:
            return 1.0
        if query in option:
            return 0.92 if len(query) >= 3 else 0.82
        query_tokens = set(query.split())
        option_tokens = set(option.split())
        if query_tokens and query_tokens.issubset(option_tokens):
            return 0.9
        overlap = len(query_tokens & option_tokens) / max(1, len(query_tokens | option_tokens))
        ratio = difflib.SequenceMatcher(None, query, option).ratio()
        return max(ratio, overlap)

    def _normalize_app_name(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()
        tokens = [
            token
            for token in cleaned.split()
            if token and token not in self.APP_MATCH_STOPWORDS
        ]
        return " ".join(tokens)

    def _app_match(
        self,
        display_name: str,
        launch_type: str,
        launch_value: str,
        confidence: float,
        source: str,
    ) -> dict[str, Any]:
        return {
            "display_name": display_name,
            "launch_type": launch_type,
            "launch_value": launch_value,
            "confidence": confidence,
            "source": source,
        }
