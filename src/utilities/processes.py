import ctypes
import os
import time
import psutil

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_SINGLETON_MUTEX_HANDLE = None
_ERROR_ALREADY_EXISTS = 183

class Processes:

    @staticmethod
    def get_valorant_pid() -> int:
        fallback_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == "valorant-win64-shipping.exe":
                    return int(proc.info["pid"])
                if name == "riotclientservices.exe":
                    fallback_pid = int(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, ValueError):
                continue
        return fallback_pid

    @staticmethod
    def are_processes_running(required_processes=("VALORANT-Win64-Shipping.exe", "RiotClientServices.exe")) -> bool:
        required = {p.lower() for p in required_processes}
        found = set()
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in required:
                    found.add(name)
                    if len(found) == len(required):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False

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
