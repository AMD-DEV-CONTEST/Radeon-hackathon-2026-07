from __future__ import annotations

import ctypes
import sys


ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


class SingleInstanceError(RuntimeError):
    pass


class SingleInstanceGuard:
    def __init__(self, name: str = "Local\\dev.lanzhijiang.xenix.gui") -> None:
        self._handle = None
        if _kernel32 is None:
            return
        handle = _kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            raise SingleInstanceError("Xenix is already running for this Windows user.")
        self._handle = handle

    def close(self) -> None:
        if self._handle is not None and _kernel32 is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()
