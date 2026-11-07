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

_LAST_RELEASE_ETAG: str | None = None
_LAST_CHECK_TS: float = 0.0

class Checker:

    @staticmethod
    def _parse_ver(v: str) -> list[int]:
        return [int(x) for x in str(v).strip("vV").split(".") if x.isdigit()]

    @staticmethod
    def get_current_version() -> str:
        candidates = [str(Localizer.get_config_value("version") or "v0.0.0")]
        version_files = [
            os.path.join(Filepath.get_appdata_folder(), "version.txt"),
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

        try:
            current_version = Checker.get_current_version()
            sig_resp = requests.get(REMOTE_SIGNAL_URL, timeout=3.5, headers={"Cache-Control": "no-cache"})
            if sig_resp.status_code == 200:
                remote_ver = sig_resp.text.strip().splitlines()[0].strip() if sig_resp.text.strip() else ""
                if remote_ver and Checker._parse_ver(remote_ver) > Checker._parse_ver(current_version):
                    Logger.debug(f"[updater] Remote update signal detected: {current_version} -> {remote_ver}")
                    return Checker.check_version(config, auto_apply=True, silent=False, force=True)
        except Exception:
            pass
        return Checker.check_version(config, auto_apply=True, silent=True, use_etag=True)

    @staticmethod
    def check_version(
        config=None,
        auto_apply: bool = True,
        silent: bool = False,
        use_etag: bool = False,
        force: bool = False,
    ) -> bool:
        global _LAST_RELEASE_ETAG, _LAST_CHECK_TS
        now = time.monotonic()
        if not force and not use_etag and _LAST_CHECK_TS > 0 and (now - _LAST_CHECK_TS) < 60.0:
            return False
        _LAST_CHECK_TS = now

        try:
            current_version = Checker.get_current_version()
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
            temp_dir = tempfile.gettempdir()
            staged_exe = os.path.join(temp_dir, "VALORANT-RPC-Update.exe")

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
            appdata_ver_file = os.path.join(Filepath.get_appdata_folder(), "version.txt")

            if is_installer_asset:
                Logger.debug(f"[updater] Launching silent installer update for {latest_tag}...")
                subprocess.Popen(
                    [
                        staged_exe,
                        "--silent-update",
                        target_exe,
                        "--version-tag",
                        latest_tag,
                        "--wait-pid",
                        str(current_pid),
                    ],
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
                os._exit(0)

            clean_ver = str(latest_tag).strip().lstrip("vV")
            just_updated_file = os.path.join(Filepath.get_appdata_folder(), "just_updated.txt")
            updater_ps1 = os.path.join(temp_dir, "valorant_rpc_updater.ps1")
            ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$targetPid = {current_pid}
$staged = '{staged_exe.replace("'", "''")}'
$target = '{target_exe.replace("'", "''")}'
$verFile = '{appdata_ver_file.replace("'", "''")}'
$updFile = '{just_updated_file.replace("'", "''")}'
$verTag = '{latest_tag.replace("'", "''")}'
$verClean = '{clean_ver.replace("'", "''")}'

for ($i = 0; $i -lt 30; $i++) {{
    if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 500
}}

Copy-Item -Path $staged -Destination $target -Force
if ($?) {{
    Set-Content -Path $verFile -Value $verTag -Encoding UTF8 -Force
    Set-Content -Path $updFile -Value $verClean -Encoding UTF8 -Force
    Remove-Item -Path $staged -Force
    Start-Process -FilePath $target -ArgumentList '--startup', "--updated-to=$verClean"
}} else {{
    $cmd = "Copy-Item -Path '$staged' -Destination '$target' -Force; if (`$?) {{ Set-Content -Path '$verFile' -Value '$verTag' -Encoding UTF8 -Force; Set-Content -Path '$updFile' -Value '$verClean' -Encoding UTF8 -Force; Remove-Item -Path '$staged' -Force; Start-Process -FilePath '$target' -ArgumentList '--startup','--updated-to=$verClean' }}"
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command $cmd" -Verb RunAs
}}
"""
            with open(updater_ps1, "w", encoding="utf-8") as f:
                f.write(ps_script)

            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    updater_ps1,
                ],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
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
