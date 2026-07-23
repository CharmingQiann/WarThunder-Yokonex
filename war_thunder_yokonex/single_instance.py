from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path


class SingleInstance:
    """阻止 GameHub 重载期间出现两个采集进程，避免同一事件发送两次。"""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str) -> None:
        self.acquired = False
        self._handle = None
        self._lock_path: Path | None = None
        if os.name == "nt":
            self._acquire_windows(name)
        else:
            self._acquire_file(name)

    def _acquire_windows(self, name: str) -> None:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, True, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return
        self._handle = handle
        self.acquired = True

    def _acquire_file(self, name: str) -> None:
        safe_name = "".join(char if char.isalnum() else "_" for char in name)
        path = Path(tempfile.gettempdir()) / f"{safe_name}.lock"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return
        os.close(descriptor)
        self._lock_path = path
        self.acquired = True

    def close(self) -> None:
        if self._handle is not None:
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._lock_path is not None:
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass
            self._lock_path = None
        self.acquired = False
