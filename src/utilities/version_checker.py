import os
import sys
import time
import tempfile
import subprocess
import requests

from ..localization.localization import Localizer
from .filepath import Filepath
from .logging import Logger

GITHUB_REPO = "karlchastin/VALORANT-Discord-Rich-Presence"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REMOTE_SIGNAL_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.txt"
LATEST_RELEASE_WEB_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

_LAST_RELEASE_ETAG: str | None = None
_LAST_CHECK_TS: float = 0.0

class Checker:

    @staticmethod
    def _parse_ver(v: str) -> list[int]:
        return [int(x) for x in str(v).strip("vV").split(".") if x.isdigit()]

    @staticmethod
    def get_current_version() -> str:
        candidates = []
        try:
            cfg_ver = Localizer.get_config_value("version")
            if cfg_ver:
                candidates.append(str(cfg_ver))
        except Exception:
            pass
        if not candidates:
            try:
                from .config.app_config import default_config
                candidates.append(str(default_config.get("version") or "v0.0.0"))
            except Exception:
                candidates.append("v0.0.0")
        version_files = [
            os.path.join(Filepath.get_appdata_folder(), "version.txt"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "version.txt"),
        ]
        if getattr(sys, "frozen", False):
            version_files.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "version.txt"))

        for vf in version_files:
            try:
                if os.path.isfile(vf):
                    with open(vf, "r", encoding="utf-8") as f:
                        tag = f.read().strip()
                        if tag:
                            candidates.append(tag)
            except Exception:
                pass

        best = candidates[0]
        for c in candidates[1:]:
            if Checker._parse_ver(c) > Checker._parse_ver(best):
                best = c
        return best

    @staticmethod
    def check_remote_signal(config=None) -> bool:

        current_version = Checker.get_current_version()

        try:
            resp = requests.head(LATEST_RELEASE_WEB_URL, allow_redirects=False, timeout=3.5)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or ""
                if "/releases/tag/" in loc:
                    remote_ver = loc.rstrip("/").split("/")[-1].strip()
                    if remote_ver and Checker._parse_ver(remote_ver) > Checker._parse_ver(current_version):
                        Logger.debug(f"[updater] Remote update signal detected: {current_version} -> {remote_ver}")
                        return Checker.check_version(config, auto_apply=True, silent=False, force=True, target_tag=remote_ver)
        except Exception:
            pass

        try:
            sig_url = f"{REMOTE_SIGNAL_URL}?t={int(time.time() // 5)}"
            sig_resp = requests.get(sig_url, timeout=3.5, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            if sig_resp.status_code == 200:
                remote_ver = sig_resp.text.strip().splitlines()[0].strip() if sig_resp.text.strip() else ""
                if remote_ver and Checker._parse_ver(remote_ver) > Checker._parse_ver(current_version):
                    Logger.debug(f"[updater] Remote version.txt signal detected: {current_version} -> {remote_ver}")
                    return Checker.check_version(config, auto_apply=True, silent=False, force=True, target_tag=remote_ver)
        except Exception:
            pass

        if _LAST_CHECK_TS <= 0.0 or (time.monotonic() - _LAST_CHECK_TS) >= 60.0:
            return Checker.check_version(config, auto_apply=True, silent=True, use_etag=True)
        return False

    @staticmethod
    def check_version(
        config=None,
        auto_apply: bool = True,
        silent: bool = False,
        use_etag: bool = False,
        force: bool = False,
        target_tag: str | None = None,
    ) -> bool:
        global _LAST_RELEASE_ETAG, _LAST_CHECK_TS
        now = time.monotonic()
        if not force and not use_etag and _LAST_CHECK_TS > 0 and (now - _LAST_CHECK_TS) < 60.0:
            return False
        _LAST_CHECK_TS = now

        current_version = Checker.get_current_version()
        if target_tag and Checker._parse_ver(target_tag) > Checker._parse_ver(current_version):
            latest = target_tag
            release_data = {"tag_name": latest}
            try:
                headers = {}
                if use_etag and _LAST_RELEASE_ETAG:
                    headers["If-None-Match"] = _LAST_RELEASE_ETAG
                resp = requests.get(RELEASES_API_URL, headers=headers, timeout=3.5)
                if resp.status_code == 200:
                    if resp.headers.get("ETag"):
                        _LAST_RELEASE_ETAG = resp.headers.get("ETag")
                    api_data = resp.json()
                    if api_data.get("tag_name") == latest:
                        release_data = api_data
            except Exception:
                pass

            Logger.debug(f"[updater] Update available: {current_version} -> {latest}")
            if auto_apply:
                return Checker.perform_update(release_data, latest)
            return True

        try:
            headers = {}
            if use_etag and _LAST_RELEASE_ETAG:
                headers["If-None-Match"] = _LAST_RELEASE_ETAG

            resp = requests.get(RELEASES_API_URL, headers=headers, timeout=3.5)
            if resp.status_code == 304:
                return False
            if resp.status_code != 200:
                return False

            if resp.headers.get("ETag"):
                _LAST_RELEASE_ETAG = resp.headers.get("ETag")

            release_data = resp.json()
            latest = release_data.get("tag_name", "")
            if not latest:
                return False

            if Checker._parse_ver(latest) <= Checker._parse_ver(current_version):
                if not silent:
                    Logger.debug(f"[updater] Up to date ({current_version})")
                return False

            Logger.debug(f"[updater] Update available: {current_version} -> {latest}")

            if auto_apply:
                return Checker.perform_update(release_data, latest)
            return True
        except Exception as e:
            Logger.debug(f"[updater] check_version failed: {e}")
            return False

    @staticmethod
    def perform_update(release_data: dict, latest_tag: str) -> bool:

        if getattr(sys, "frozen", False):
            return Checker._update_frozen_executable(release_data, latest_tag)
        return Checker._update_git_source(latest_tag)

    @staticmethod
    def _update_frozen_executable(release_data: dict, latest_tag: str) -> bool:
        assets = release_data.get("assets") or []
        download_url = None
        is_installer_asset = True

        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name.endswith(".exe") and ("setup" in name or "install" in name):
                download_url = asset.get("browser_download_url")
                is_installer_asset = True
                break

        if not download_url:
            for asset in assets:
                name = (asset.get("name") or "").lower()
                if name.endswith(".exe"):
                    download_url = asset.get("browser_download_url")
                    is_installer_asset = ("setup" in name or "install" in name)
                    break

        if not download_url:
            download_url = f"https://github.com/{GITHUB_REPO}/releases/download/{latest_tag}/VALORANT-RPC-Setup.exe"
            is_installer_asset = True

        try:
            Logger.debug(f"[updater] Downloading {latest_tag} from {download_url}...")
            updates_dir = os.path.join(Filepath.get_appdata_folder(), "updates")
            os.makedirs(updates_dir, exist_ok=True)
            staged_exe = os.path.join(updates_dir, "VALORANT-RPC-Update.exe")

            with requests.get(download_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(staged_exe, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            if not os.path.exists(staged_exe) or os.path.getsize(staged_exe) < 1024 * 100:
                Logger.debug("[updater] Downloaded file is too small or invalid; aborting update.")
                return False

            target_exe = os.path.abspath(sys.executable)
            current_pid = os.getpid()
            update_args = [
                "--silent-update",
                target_exe,
                "--version-tag",
                latest_tag,
                "--wait-pid",
                str(current_pid),
            ]

            Logger.debug(f"[updater] Launching silent installer update for {latest_tag}...")
            try:
                subprocess.Popen(
                    [staged_exe, *update_args],
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except OSError:
                import ctypes
                arg_str = " ".join(f'"{a}"' for a in update_args)
                ctypes.windll.shell32.ShellExecuteW(None, "open", staged_exe, arg_str, updates_dir, 0)
            os._exit(0)
        except Exception as e:
            Logger.debug(f"[updater] Executable self-update failed: {e}")
            return False

    @staticmethod
    def _update_git_source(latest_tag: str) -> bool:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isdir(os.path.join(repo_root, ".git")):
            return False
        try:
            res = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if res.returncode == 0 and "Already up to date" not in (res.stdout or ""):
                clean_ver = str(latest_tag).strip().lstrip("vV")
                try:
                    with open(os.path.join(Filepath.get_appdata_folder(), "just_updated.txt"), "w", encoding="utf-8") as uf:
                        uf.write(clean_ver)
                except Exception:
                    pass
                Logger.debug(f"[updater] Updated git source to {latest_tag}, restarting...")
                os.execl(sys.executable, sys.executable, *sys.argv, f"--updated-to={clean_ver}")
        except Exception as e:
            Logger.debug(f"[updater] Git source update failed: {e}")
        return False
