import ctypes
import gc
import os
import time
import psutil

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)

_KERNEL32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
_KERNEL32.OpenProcess.restype = ctypes.c_void_p
_KERNEL32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_KERNEL32.WaitForSingleObject.restype = ctypes.c_uint32
_KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
_KERNEL32.CloseHandle.restype = ctypes.c_int
_KERNEL32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_KERNEL32.GetExitCodeProcess.restype = ctypes.c_int
_KERNEL32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_KERNEL32.SetPriorityClass.restype = ctypes.c_int
_KERNEL32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
_KERNEL32.SetProcessWorkingSetSize.restype = ctypes.c_int
_PSAPI.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
_PSAPI.EmptyWorkingSet.restype = ctypes.c_int

_CURRENT_PROCESS = ctypes.c_void_p(-1)
_SINGLETON_MUTEX_HANDLE = None
_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_TIMEOUT = 0x00000102
_STILL_ACTIVE = 259
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

_CACHED_HANDLES: dict[str, int] = {}
_CACHED_PIDS: dict[str, int] = {}
_LAST_SCAN_TS: float = 0.0

class Processes:

    @staticmethod
    def set_background_priority() -> None:

        try:
            _KERNEL32.SetPriorityClass(_CURRENT_PROCESS, _BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass

    @staticmethod
    def trim_working_set() -> None:

        try:
            gc.collect()
            _PSAPI.EmptyWorkingSet(_CURRENT_PROCESS)
            _KERNEL32.SetProcessWorkingSetSize(_CURRENT_PROCESS, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
        except Exception:
            pass

    @staticmethod
    def _is_handle_alive(name: str) -> bool:
        handle = _CACHED_HANDLES.get(name)
        if not handle:
            return False
        h_ptr = ctypes.c_void_p(handle)
        if _KERNEL32.WaitForSingleObject(h_ptr, 0) == _WAIT_TIMEOUT:
            return True
        exit_code = ctypes.c_uint32(0)
        if _KERNEL32.GetExitCodeProcess(h_ptr, ctypes.byref(exit_code)) and exit_code.value == _STILL_ACTIVE:
            return True
        try:
            _KERNEL32.CloseHandle(h_ptr)
        except Exception:
            pass
        _CACHED_HANDLES.pop(name, None)
        _CACHED_PIDS.pop(name, None)
        return False

    @staticmethod
    def _cache_process(name: str, pid: int) -> None:
        _CACHED_PIDS[name] = pid
        if name not in _CACHED_HANDLES:
            try:
                handle = _KERNEL32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    _CACHED_HANDLES[name] = int(handle)
            except Exception:
                pass

    @staticmethod
    def get_valorant_pid() -> int:

        if Processes._is_handle_alive("valorant-win64-shipping.exe"):
            pid = _CACHED_PIDS.get("valorant-win64-shipping.exe")
            if pid:
                return pid
        Processes.are_processes_running()
        return (
            _CACHED_PIDS.get("valorant-win64-shipping.exe")
            or _CACHED_PIDS.get("riotclientservices.exe")
            or os.getpid()
        )

    @staticmethod
    def are_processes_running(required_processes=("VALORANT-Win64-Shipping.exe", "RiotClientServices.exe")) -> bool:

        global _LAST_SCAN_TS
        required = {p.lower() for p in required_processes}
        if required and all(Processes._is_handle_alive(req) for req in required):
            return True

        now = time.monotonic()
        if (now - _LAST_SCAN_TS) < 0.15:
            return bool(required and all(req in _CACHED_PIDS for req in required))
        _LAST_SCAN_TS = now

        found = set()
        tracked = required | {"valorant-win64-shipping.exe", "riotclientservices.exe"}
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in tracked:
                    pid = int(proc.info["pid"])
                    Processes._cache_process(name, pid)
                    if name in required:
                        found.add(name)
                        if len(found) == len(required) and "valorant-win64-shipping.exe" in _CACHED_PIDS:
                            return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, ValueError):
                continue
        for dead in list(_CACHED_PIDS.keys()):
            if dead in required and dead not in found:
                Processes._is_handle_alive(dead)
                _CACHED_PIDS.pop(dead, None)
        return len(found) == len(required)

    @staticmethod
    def is_program_already_running() -> bool:

        global _SINGLETON_MUTEX_HANDLE
        if _SINGLETON_MUTEX_HANDLE is not None:
            return False
        my_pid = os.getpid()
        my_ppid = os.getppid()
        for proc in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                if (proc.info.get("name") or "").lower() == "valorant-rpc.exe":
                    pid = int(proc.info["pid"])
                    ppid = int(proc.info.get("ppid") or 0)
                    if pid not in (my_pid, my_ppid) and ppid != my_pid:
                        proc.kill()
            except Exception:
                continue
        for _ in range(15):
            try:
                handle = _KERNEL32.CreateMutexW(None, False, "Local\\VALORANT_RPC_SINGLETON_MUTEX_V4")
                if handle:
                    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
                        _KERNEL32.CloseHandle(handle)
                        time.sleep(0.1)
                        continue
                    _SINGLETON_MUTEX_HANDLE = handle
                    return False
            except Exception:
                pass
            break
        return True
