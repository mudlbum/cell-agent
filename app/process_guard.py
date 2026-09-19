"""Windows Job Object lifetime/resource guard; fails closed if unavailable.

Not a permissions sandbox. Other services, remote calls and preexisting processes
are outside the job. Never claim this revokes completed effects.
"""
import ctypes
from ctypes import wintypes
import os


class ProcessGuard:
    def __init__(self, memory_mb=1024, cpu_percent=50):
        if os.name != "nt":
            raise RuntimeError("Dashboard process supervision currently requires Windows")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self.api
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        k.QueryInformationJobObject.restype = wintypes.BOOL

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        class CPU(ctypes.Structure):
            _fields_ = [("flags", wintypes.DWORD), ("rate", wintypes.DWORD)]
        self.extended = Extended
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000 | 0x200 | 0x8  # kill-on-close, job memory, process count
        limits.basic.active_limit = 32
        limits.job_memory = int(memory_mb) * 1024 * 1024
        try:
            self._check(k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            cpu = CPU(1 | 4, int(cpu_percent) * 100)
            self._check(k.SetInformationJobObject(self.handle, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def attach(self, process):
        self._check(self.api.AssignProcessToJobObject(self.handle, int(process._handle)))

    def peak_bytes(self):
        if not self.handle:
            return 0
        info = self.extended()
        self._check(self.api.QueryInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.peak_job

    def kill(self):
        if self.handle:
            self._check(self.api.TerminateJobObject(self.handle, 137))

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
