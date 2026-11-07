from PIL import Image
from pystray import Icon as icon, Menu as menu, MenuItem as item
import os, shutil, sys, time, urllib.request, webbrowser

from .filepath import Filepath
from .version_checker import GITHUB_REPO

class Systray:

    def __init__(self, client, config, presence=None):
        self.client = client
        self.config = config
        self.presence = presence
        self.systray = None
        self.status_text = "Standby (Waiting for VALORANT)"
        self.version = self._resolve_version()

    def _resolve_version(self) -> str:

        try:
            from .version_checker import Checker
            ver = Checker.get_current_version()
            if ver:
                return ver if ver.startswith("v") else f"v{ver}"
        except Exception:
            pass
        return "v4.0.2"

    def _consume_updated_version(self) -> str | None:

        updated_ver = None
        marker_path = os.path.join(Filepath.get_appdata_folder(), "just_updated.txt")
        if os.path.isfile(marker_path):
            try:
                with open(marker_path, "r", encoding="utf-8") as mf:
                    updated_ver = mf.read().strip().lstrip("vV")
            except Exception:
                pass
            try:
                os.remove(marker_path)
            except Exception:
                pass

        for arg in sys.argv[1:]:
            if arg.startswith("--updated-to="):
                val = arg.split("=", 1)[1].strip().lstrip("vV")
                if val:
                    updated_ver = val

        current_clean = self.version.strip().lstrip("vV")
        if updated_ver and updated_ver == current_clean:
            return updated_ver
        return None

    def _on_tray_ready(self, tray_icon) -> None:
        tray_icon.visible = True
        updated_ver = self._consume_updated_version()
        if updated_ver:
            time.sleep(0.5)
            try:
                tray_icon.notify(f"Updated to {updated_ver}!", "VALORANT RPC")
            except Exception:
                pass

    def set_status(self, status: str) -> None:
        self.status_text = status
        if self.systray is not None:
            try:
                self.systray.title = f"VALORANT RPC ({self.version}) - {status}"
            except Exception:
                pass

    def run(self):
        icon_path = Systray.generate_icon()
        systray_image = (
            Image.open(icon_path)
            if icon_path and os.path.exists(icon_path)
            else Image.new("RGBA", (64, 64), (255, 70, 85, 255))
        )
        systray_menu = menu(
            item(f"VALORANT RPC {self.version}", None, enabled=False),
            item('View on GitHub', self.view_github),
            item('Uninstall', self.uninstall),
            item('Exit', self.exit),
        )
        self.systray = icon(
            "VALORANT RPC",
            systray_image,
            f"VALORANT RPC ({self.version}) - {self.status_text}",
            systray_menu,
        )
        self.systray.run(setup=self._on_tray_ready)

    def view_github(self, *_):
        webbrowser.open(f"https://github.com/{GITHUB_REPO}")

    def uninstall(self, *_):

        import subprocess, sys
        unins_candidates = []
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(os.path.abspath(sys.executable))
            unins_candidates.append(os.path.join(base_dir, "unins000.exe"))
            unins_candidates.append(os.path.join(base_dir, "VALORANT-RPC-Setup.exe"))

        unins_candidates.append(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VALORANT RPC", "unins000.exe"))

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VALORANT_RPC", 0, winreg.KEY_READ) as ukey:
                val, _ = winreg.QueryValueEx(ukey, "InstallLocation")
                if val:
                    unins_candidates.append(os.path.join(val, "unins000.exe"))
        except Exception:
            pass

        target_unins = None
        for cand in unins_candidates:
            if cand and os.path.isfile(cand):
                target_unins = cand
                break

        if target_unins:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(target_unins)
                else:
                    subprocess.Popen([target_unins, "--uninstall"])
                return
            except Exception:
                pass

        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        inst_script = os.path.join(root_dir, "installer_gui.py")
        if os.path.isfile(inst_script):
            subprocess.Popen([sys.executable, inst_script, "--uninstall"])

    def exit(self, *_):
        if self.presence is not None:
            self.presence.disconnect_rpc()
        if self.systray is not None:
            self.systray.visible = False
            self.systray.stop()
        try:
            os._exit(0)
        except Exception:
            pass

    @staticmethod
    def generate_icon() -> str:
        appdata_dir = Filepath.get_appdata_folder()
        os.makedirs(appdata_dir, exist_ok=True)
        target = os.path.join(appdata_dir, 'favicon.ico')
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return target
        local_ico = Filepath.get_path(os.path.join('assets', 'game_icon_white.ico'))
        if os.path.exists(local_ico):
            try:
                shutil.copyfile(local_ico, target)
                return target
            except Exception:
                return local_ico
        try:
            urllib.request.urlretrieve(
                'https://raw.githubusercontent.com/colinhartigan/valorant-rpc/v2/favicon.ico',
                target,
            )
        except Exception:
            pass
        return target
