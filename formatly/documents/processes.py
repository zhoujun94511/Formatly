"""Own Python worker descendants until their bounded operation finishes."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
# contextvars is in the standard library from Python 3.7. The project also
# keeps an older compatibility view, which otherwise asks for a PyPI backport.
# noinspection PyPackageRequirements
from contextvars import ContextVar
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import BinaryIO


_managed_scope: ContextVar[bool] = ContextVar("formatly_managed_worker", default=False)


@contextmanager
def managed_worker_scope() -> Iterator[None]:
    """Let workers launched by our entry point share their owner's POSIX group."""
    token = _managed_scope.set(True)
    try:
        yield
    finally:
        _managed_scope.reset(token)


class _BasicLimit(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "read_operations", "write_operations", "other_operations", "read_bytes", "write_bytes", "other_bytes")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("basic", _BasicLimit), ("io", _IoCounters), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("user_time", "kernel_time", "period_user_time", "period_kernel_time")] + [
        (name, wintypes.DWORD) for name in ("page_faults", "total_processes", "active_processes", "terminated_processes")]


class _WindowsJob:
    def __init__(self) -> None:
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimit()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, pid: int) -> None:
        # Assign before the stdin handshake permits the worker to run any code.
        handle = self.api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            try:
                if not self.api.TerminateJobObject(handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                deadline = time.monotonic() + 5
                while True:
                    accounting = _Accounting()
                    if not self.api.QueryInformationJobObject(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if accounting.active_processes == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Worker descendants did not exit within 5 seconds")
                    time.sleep(.01)
            finally:
                if not self.api.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def managed_windows_process(pid: int) -> Iterator[None]:
    """Contain a caller-proven, newly created native process until scope exit."""
    if os.name != "nt" or type(pid) is not int or pid <= 0:
        raise ValueError("Native process containment requires a Windows process ID")
    job = _WindowsJob()
    try:
        job.assign(pid)
        yield
    finally:
        job.close()


@contextmanager
def managed_python_worker(command: list[str], *, cwd: Path,
                          env: Mapping[str, str] | None = None,
                          stdout: int | BinaryIO = subprocess.DEVNULL,
                          stderr: int | BinaryIO = subprocess.DEVNULL) -> Iterator[subprocess.Popen[bytes]]:
    """Start a Python module/script after containment, then reclaim its tree.

    Windows retains a kill-on-close Job Object even when the direct worker has
    exited. POSIX nested workers share the explicitly managed entry's group;
    only its outer owner terminates that group. No environment flag grants
    ownership of an existing process group.
    """
    if len(command) < 2:
        raise ValueError("Python worker command is incomplete")
    entry = Path(__file__).with_name("worker_entry.py")
    bootstrap = [command[0], "-B", str(entry), json.dumps(command[1:], ensure_ascii=True)]
    job = _WindowsJob() if os.name == "nt" else None
    owns_group = os.name != "nt" and not _managed_scope.get()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(bootstrap, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                   start_new_session=owns_group)
        if job is not None:
            job.assign(process.pid)
        if process.stdin is None:
            raise RuntimeError("Worker handshake pipe is unavailable")
        try:
            process.stdin.write(b"FORMATLY-WORKER\n")
            process.stdin.flush()
        finally:
            process.stdin.close()
        yield process
    finally:
        try:
            if process is not None and process.stdin is not None:
                process.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            try:
                if job is not None:
                    job.close()
                elif os.name != "nt" and process is not None and owns_group:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
