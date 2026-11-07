\
\

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import winreg

APP_NAME = "VALORANT RPC"
APP_VERSION = "v4.0.3"
APP_VERSION_NUMERIC = "4.0.3"
APP_PUBLISHER = "karlchastin"
DEFAULT_INSTALL_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VALORANT RPC")
UNINSTALL_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VALORANT_RPC"
RUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

TERMS_TEXT = """VALORANT RPC - TERMS OF USE & DISCLAIMER

Please read this agreement carefully before installing or using VALORANT RPC. By installing or using this software, you agree to the terms below.

1. RIOT GAMES & ANTI-CHEAT DISCLAIMER
VALORANT RPC is a passive Discord Rich Presence integration. It only reads local Riot Client session/presence status and public game metadata to display your current mode, map, agent, rank, and match score on Discord. It does not read, hook, inject into, or modify VALORANT game memory, game files, or Riot Vanguard, and provides no gameplay advantage.

According to Riot Games Customer Support and Riot's Third-Party Application policy, passive external tools that do not interact with game memory or provide an unfair advantage are not bannable. However, because this is an unofficial community project not affiliated with or certified by Riot Games, this is not 100% guaranteed. You use this software at your own discretion and risk.

2. "AS IS" SOFTWARE & AUTOMATIC UPDATES
This software is provided "AS IS", without warranty of any kind, express or implied. In no event shall the authors or contributors be liable for any claim, damages, or account actions arising from the use of this software.

This software includes an automatic update system that checks official GitHub Releases and installs updates automatically to maintain compatibility with new VALORANT patches.

3. TRADEMARK NOTICE
VALORANT RPC is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and VALORANT are trademarks or registered trademarks of Riot Games, Inc."""

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _init_dpi_scaling() -> float:

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if dpi > 0:
            return max(1.0, dpi / 96.0)
    except Exception:
        pass
    return 1.0

DPI_SCALE = _init_dpi_scaling()

def px(val: int) -> int:
    return int(round(val * DPI_SCALE))

def elevate_if_needed() -> None:
    if is_admin():
        return
    params = " ".join(f'"{arg}"' for arg in sys.argv)
    if getattr(sys, "frozen", False):
        executable = sys.executable
        args = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    else:
        executable = sys.executable
        args = params
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, args, os.path.abspath("."), 1)
    if int(rc) <= 32:
        sys.exit(1)
    sys.exit(0)

def is_windows_dark_mode() -> bool:

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(val) == 0
    except Exception:
        return True

def apply_window_theme_titlebar(window: tk.Tk, dark: bool) -> None:

    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)

        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if res != 0:

            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )

        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
    except Exception:
        pass

def resource_path(rel_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)

def get_desktop_dirs() -> list[str]:

    dirs: list[str] = []
    try:
        for csidl in (0x0010, 0x0019):
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf) == 0 and buf.value:
                if os.path.isdir(buf.value) and buf.value not in dirs:
                    dirs.append(buf.value)
    except Exception:
        pass
    for fallback in (
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("ONEDRIVE", ""), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
    ):
        if fallback and os.path.isdir(fallback) and fallback not in dirs:
            dirs.append(fallback)
    return dirs

def create_shortcut(shortcut_path: str, target_exe: str, arguments: str, working_dir: str, description: str) -> None:
    ps_cmd = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path.replace(chr(39), chr(39)*2)}'); "
        f"$s.TargetPath = '{target_exe.replace(chr(39), chr(39)*2)}'; "
        f"$s.Arguments = '{arguments}'; "
        f"$s.WorkingDirectory = '{working_dir.replace(chr(39), chr(39)*2)}'; "
        f"$s.IconLocation = '{target_exe.replace(chr(39), chr(39)*2)},0'; "
        f"$s.Description = '{description}'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

def get_theme_palette(dark_mode: bool) -> dict[str, str]:
    if dark_mode:
        return {
            "BG_DARK": "#0F1923",
            "BG_PANEL": "#18232F",
            "BG_INPUT": "#0A1118",
            "BORDER_COLOR": "#263342",
            "BTN_SEC_BG": "#263342",
            "BTN_SEC_ACTIVE": "#34465A",
            "BTN_DISABLED_BG": "#25303C",
            "TEXT_LIGHT": "#ECE8E1",
            "TEXT_MUTED": "#9BA5B0",
            "ACCENT_RED": "#FF4655",
        }
    return {
        "BG_DARK": "#F5F6F7",
        "BG_PANEL": "#FFFFFF",
        "BG_INPUT": "#FFFFFF",
        "BORDER_COLOR": "#D0D7DE",
        "BTN_SEC_BG": "#E5E8EC",
        "BTN_SEC_ACTIVE": "#D4D9DF",
        "BTN_DISABLED_BG": "#D8DCE0",
        "TEXT_LIGHT": "#1F2328",
        "TEXT_MUTED": "#57606A",
        "ACCENT_RED": "#FF4655",
    }

def show_themed_dialog(
    window_title: str,
    header_text: str,
    message_text: str,
    primary_text: str = "OK",
    secondary_text: str | None = None,
    parent: tk.Misc | None = None,
) -> bool:

    dark_mode = is_windows_dark_mode()
    pal = get_theme_palette(dark_mode)
    result = {"confirmed": False}

    owns_root = parent is None
    if owns_root:
        dlg = tk.Tk()
    else:
        dlg = tk.Toplevel(parent)
        dlg.transient(parent)

    dlg.title(window_title)
    width, height = px(470), px(235)
    dlg.update_idletasks()
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    dlg.geometry(f"{width}x{height}+{x}+{y}")
    dlg.resizable(False, False)
    dlg.configure(bg=pal["BG_DARK"])

    ico_path = resource_path("favicon.ico")
    if os.path.exists(ico_path):
        try:
            dlg.iconbitmap(ico_path)
        except Exception:
            pass

    apply_window_theme_titlebar(dlg, dark_mode)

    header = tk.Frame(dlg, bg=pal["BG_PANEL"], height=px(52))
    header.pack(fill=tk.X, side=tk.TOP)
    header.pack_propagate(False)

    tk.Label(
        header,
        text=header_text,
        font=("Segoe UI", 11, "bold"),
        fg=pal["TEXT_LIGHT"],
        bg=pal["BG_PANEL"],
        anchor="w",
    ).pack(fill=tk.X, padx=px(20), pady=(px(14), 0))

    tk.Frame(dlg, bg=pal["ACCENT_RED"], height=max(2, px(2))).pack(fill=tk.X, side=tk.TOP)

    footer = tk.Frame(dlg, bg=pal["BG_PANEL"], height=px(50))
    footer.pack(fill=tk.X, side=tk.BOTTOM)
    footer.pack_propagate(False)

    tk.Frame(dlg, bg=pal["BORDER_COLOR"], height=max(1, px(1))).pack(fill=tk.X, side=tk.BOTTOM)

    body = tk.Frame(dlg, bg=pal["BG_DARK"], padx=px(22), pady=px(18))
    body.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        body,
        text=message_text,
        font=("Segoe UI", 9),
        fg=pal["TEXT_LIGHT"],
        bg=pal["BG_DARK"],
        justify=tk.LEFT,
        anchor="nw",
        wraplength=px(424),
    ).pack(fill=tk.BOTH, expand=True)

    def _on_primary() -> None:
        result["confirmed"] = True
        dlg.destroy()

    def _on_secondary() -> None:
        result["confirmed"] = False
        dlg.destroy()

    dlg.protocol("WM_DELETE_WINDOW", _on_secondary)

    if secondary_text:
        btn_sec = tk.Button(
            footer,
            text=secondary_text,
            font=("Segoe UI", 9),
            bg=pal["BTN_SEC_BG"],
            fg=pal["TEXT_LIGHT"],
            activebackground=pal["BTN_SEC_ACTIVE"],
            activeforeground=pal["TEXT_LIGHT"],
            relief=tk.FLAT,
            width=10,
            command=_on_secondary,
        )
        btn_sec.pack(side=tk.RIGHT, padx=(8, 18), pady=10)
        primary_padx = (0, 0)
    else:
        primary_padx = (0, 18)

    btn_pri = tk.Button(
        footer,
        text=primary_text,
        font=("Segoe UI", 9, "bold"),
        bg=pal["ACCENT_RED"],
        fg="#FFFFFF",
        activebackground="#E03846",
        activeforeground="#FFFFFF",
        relief=tk.FLAT,
        width=10,
        command=_on_primary,
    )
    btn_pri.pack(side=tk.RIGHT, padx=primary_padx, pady=10)

    dlg.grab_set()
    dlg.focus_force()
    if owns_root:
        dlg.mainloop()
    else:
        dlg.wait_window()

    return result["confirmed"]

class SetupWizard(tk.Tk):

    def __init__(self, repair_mode: bool = False, existing_dir: str | None = None):
        super().__init__()
        self.repair_mode = repair_mode
        self.dark_mode = is_windows_dark_mode()
        pal = get_theme_palette(self.dark_mode)
        self.BG_DARK = pal["BG_DARK"]
        self.BG_PANEL = pal["BG_PANEL"]
        self.BG_INPUT = pal["BG_INPUT"]
        self.BORDER_COLOR = pal["BORDER_COLOR"]
        self.BTN_SEC_BG = pal["BTN_SEC_BG"]
        self.BTN_SEC_ACTIVE = pal["BTN_SEC_ACTIVE"]
        self.BTN_DISABLED_BG = pal["BTN_DISABLED_BG"]
        self.TEXT_LIGHT = pal["TEXT_LIGHT"]
        self.TEXT_MUTED = pal["TEXT_MUTED"]
        self.ACCENT_RED = pal["ACCENT_RED"]

        self.title(f"Setup - {APP_NAME}")
        w, h = px(600), px(430)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
        self.resizable(False, False)
        self.configure(bg=self.BG_DARK)

        ico_path = resource_path("favicon.ico")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        apply_window_theme_titlebar(self, self.dark_mode)

        self.current_step = 0
        self.accepted_terms = tk.IntVar(value=0)
        self.install_dir = tk.StringVar(value=existing_dir or DEFAULT_INSTALL_DIR)
        self.opt_desktop = tk.BooleanVar(value=True)
        self.opt_launch_now = tk.BooleanVar(value=True)
        self.installing = False

        self._build_layout()
        self._show_step(3 if self.repair_mode else 0)

    def _build_layout(self) -> None:
        self.header = tk.Frame(self, bg=self.BG_PANEL, height=px(64))
        self.header.pack(fill=tk.X, side=tk.TOP)
        self.header.pack_propagate(False)

        self.accent_bar = tk.Frame(self, bg=self.ACCENT_RED, height=max(2, px(2)))
        self.accent_bar.pack(fill=tk.X, side=tk.TOP)

        self.header_title = tk.Label(
            self.header,
            text="",
            font=("Segoe UI", 12, "bold"),
            fg=self.TEXT_LIGHT,
            bg=self.BG_PANEL,
            anchor="w",
        )
        self.header_title.pack(fill=tk.X, padx=px(22), pady=(px(11), px(1)))

        self.header_subtitle = tk.Label(
            self.header,
            text="",
            font=("Segoe UI", 9),
            fg=self.TEXT_MUTED,
            bg=self.BG_PANEL,
            anchor="w",
        )
        self.header_subtitle.pack(fill=tk.X, padx=px(22))

        self.footer = tk.Frame(self, bg=self.BG_PANEL, height=px(52))
        self.footer.pack(fill=tk.X, side=tk.BOTTOM)
        self.footer.pack_propagate(False)

        tk.Frame(self, bg=self.BORDER_COLOR, height=max(1, px(1))).pack(fill=tk.X, side=tk.BOTTOM)

        self.btn_cancel = tk.Button(
            self.footer,
            text="Cancel",
            font=("Segoe UI", 9),
            bg=self.BTN_SEC_BG,
            fg=self.TEXT_LIGHT,
            activebackground=self.BTN_SEC_ACTIVE,
            activeforeground=self.TEXT_LIGHT,
            relief=tk.FLAT,
            width=10,
            command=self._on_cancel,
        )
        self.btn_cancel.pack(side=tk.RIGHT, padx=(px(8), px(18)), pady=px(11))

        self.btn_next = tk.Button(
            self.footer,
            text="Next >",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_RED,
            fg="#FFFFFF",
            activebackground="#E03846",
            activeforeground="#FFFFFF",
            disabledforeground="#8C959F",
            relief=tk.FLAT,
            width=10,
            command=self._on_next,
        )
        self.btn_next.pack(side=tk.RIGHT, padx=px(4), pady=px(11))

        self.btn_back = tk.Button(
            self.footer,
            text="< Back",
            font=("Segoe UI", 9),
            bg=self.BTN_SEC_BG,
            fg=self.TEXT_LIGHT,
            activebackground=self.BTN_SEC_ACTIVE,
            activeforeground=self.TEXT_LIGHT,
            disabledforeground="#8C959F",
            relief=tk.FLAT,
            width=10,
            command=self._on_back,
        )
        self.btn_back.pack(side=tk.RIGHT, padx=px(4), pady=px(11))

        self.content = tk.Frame(self, bg=self.BG_DARK)
        self.content.pack(fill=tk.BOTH, expand=True)

    def _clear_content(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()

    def _show_step(self, step: int) -> None:
        self.current_step = step
        self._clear_content()

        if step == 0:
            self._build_step_welcome()
        elif step == 1:
            self._build_step_terms()
        elif step == 2:
            self._build_step_options()
        elif step == 3:
            self._build_step_installing()
        elif step == 4:
            self._build_step_finished()

    def _build_step_welcome(self) -> None:
        self.header_title.config(text=f"Welcome to the {APP_NAME} Setup Wizard")
        self.header_subtitle.config(text=f"This will install {APP_NAME} {APP_VERSION} on your computer.")

        frame = tk.Frame(self.content, bg=self.BG_DARK, padx=26, pady=24)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text=(
                f"Setup will guide you through the installation of {APP_NAME}.\n\n"
                "Click Next to continue, or Cancel to exit Setup."
            ),
            font=("Segoe UI", 10),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X)

        self.btn_back.config(state=tk.DISABLED)
        self.btn_next.config(text="Next >", state=tk.NORMAL, bg=self.ACCENT_RED)

    def _build_step_terms(self) -> None:
        self.header_title.config(text="License Agreement")
        self.header_subtitle.config(text="Please read the following important information before continuing.")

        frame = tk.Frame(self.content, bg=self.BG_DARK, padx=22, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        radio_frame = tk.Frame(frame, bg=self.BG_DARK)
        radio_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        def _toggle_accept():
            if self.accepted_terms.get() == 1:
                self.btn_next.config(state=tk.NORMAL, bg=self.ACCENT_RED)
            else:
                self.btn_next.config(state=tk.DISABLED, bg=self.BTN_DISABLED_BG)

        tk.Radiobutton(
            radio_frame,
            text="I accept the agreement",
            variable=self.accepted_terms,
            value=1,
            command=_toggle_accept,
            font=("Segoe UI", 9, "bold"),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            selectcolor=self.BG_PANEL,
            activebackground=self.BG_DARK,
            activeforeground=self.TEXT_LIGHT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 2))

        tk.Radiobutton(
            radio_frame,
            text="I do not accept the agreement",
            variable=self.accepted_terms,
            value=0,
            command=_toggle_accept,
            font=("Segoe UI", 9),
            fg=self.TEXT_MUTED,
            bg=self.BG_DARK,
            selectcolor=self.BG_PANEL,
            activebackground=self.BG_DARK,
            activeforeground=self.TEXT_LIGHT,
            anchor="w",
        ).pack(fill=tk.X)

        text_frame = tk.Frame(frame, bg=self.BORDER_COLOR, bd=1, relief=tk.FLAT)
        text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        txt = tk.Text(
            text_frame,
            height=9,
            font=("Segoe UI", 9),
            bg=self.BG_INPUT,
            fg=self.TEXT_LIGHT,
            yscrollcommand=scrollbar.set,
            wrap=tk.WORD,
            padx=10,
            pady=8,
            relief=tk.FLAT,
        )
        txt.insert(tk.END, TERMS_TEXT)
        txt.config(state=tk.DISABLED)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)

        self.btn_back.config(state=tk.NORMAL)
        self.btn_next.config(text="Next >")
        _toggle_accept()

    def _build_step_options(self) -> None:
        self.header_title.config(text="Select Destination Location")
        self.header_subtitle.config(text=f"Where should {APP_NAME} be installed?")

        frame = tk.Frame(self.content, bg=self.BG_DARK, padx=26, pady=18)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="Destination folder:",
            font=("Segoe UI", 9),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))

        dir_row = tk.Frame(frame, bg=self.BG_DARK)
        dir_row.pack(fill=tk.X, pady=(0, 18))

        entry_border = tk.Frame(dir_row, bg=self.BORDER_COLOR, bd=1)
        entry_border.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        entry = tk.Entry(
            entry_border,
            textvariable=self.install_dir,
            font=("Segoe UI", 9),
            bg=self.BG_INPUT,
            fg=self.TEXT_LIGHT,
            insertbackground=self.TEXT_LIGHT,
            relief=tk.FLAT,
        )
        entry.pack(fill=tk.X, ipady=5, padx=4)

        def _browse():
            chosen = filedialog.askdirectory(initialdir=self.install_dir.get(), title="Select Destination Folder")
            if chosen:
                self.install_dir.set(os.path.normpath(chosen))

        tk.Button(
            dir_row,
            text="Browse...",
            font=("Segoe UI", 9),
            bg=self.BTN_SEC_BG,
            fg=self.TEXT_LIGHT,
            activebackground=self.BTN_SEC_ACTIVE,
            activeforeground=self.TEXT_LIGHT,
            relief=tk.FLAT,
            width=10,
            command=_browse,
        ).pack(side=tk.RIGHT)

        tk.Checkbutton(
            frame,
            text="Create a desktop shortcut",
            variable=self.opt_desktop,
            font=("Segoe UI", 9),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            selectcolor=self.BG_PANEL,
            activebackground=self.BG_DARK,
            activeforeground=self.TEXT_LIGHT,
            anchor="w",
        ).pack(fill=tk.X, pady=2)

        self.btn_back.config(state=tk.NORMAL)
        self.btn_next.config(text="Install", state=tk.NORMAL, bg=self.ACCENT_RED)

    def _build_step_installing(self) -> None:
        action = "Repairing" if self.repair_mode else "Installing"
        verb = "repairs" if self.repair_mode else "installs"
        self.header_title.config(text=action)
        self.header_subtitle.config(text=f"Please wait while Setup {verb} {APP_NAME} on your computer.")

        self.btn_back.config(state=tk.DISABLED)
        self.btn_next.config(state=tk.DISABLED, bg=self.BTN_DISABLED_BG)
        self.btn_cancel.config(state=tk.DISABLED)

        frame = tk.Frame(self.content, bg=self.BG_DARK, padx=26, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.lbl_status = tk.Label(
            frame,
            text="Extracting files...",
            font=("Segoe UI", 9),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            anchor="w",
        )
        self.lbl_status.pack(fill=tk.X, pady=(0, 8))

        self.progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X)

        self.installing = True
        threading.Thread(target=self._run_install_worker, daemon=True).start()

    def _append_log(self, msg: str, pct: int | None = None) -> None:
        def _ui():
            self.lbl_status.config(text=msg)
            if pct is not None:
                self.progress["value"] = pct

        self.after(0, _ui)

    def _run_install_worker(self) -> None:
        try:
            target_dir = os.path.abspath(self.install_dir.get())
            exe_source = resource_path(os.path.join("dist", "valorant-rpc.exe"))
            bundled_exe = resource_path("valorant-rpc.exe")

            if os.path.exists(bundled_exe) and os.path.abspath(bundled_exe) != os.path.abspath(sys.executable):
                exe_source = bundled_exe

            if not os.path.exists(exe_source):
                self._append_log("Building valorant-rpc.exe...", 15)
                spec_path = resource_path("valorant-rpc.spec")
                res = subprocess.run(
                    [sys.executable, "-m", "PyInstaller", spec_path, "--noconfirm"],
                    cwd=os.path.dirname(spec_path),
                    capture_output=True,
                    text=True,
                )
                if res.returncode != 0 or not os.path.exists(exe_source):
                    raise RuntimeError(f"PyInstaller build failed:\n{res.stderr or res.stdout}")

            self._append_log("Stopping existing processes...", 35)
            subprocess.run(
                ["taskkill", "/F", "/IM", "valorant-rpc.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )

            self._append_log("Copying files...", 60)
            os.makedirs(target_dir, exist_ok=True)
            try:
                subprocess.run(
                    ["icacls", target_dir, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T", "/C", "/Q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except Exception:
                pass

            target_exe = os.path.join(target_dir, "valorant-rpc.exe")
            shutil.copy2(exe_source, target_exe)

            ico_src = resource_path("favicon.ico")
            if os.path.exists(ico_src):
                shutil.copy2(ico_src, os.path.join(target_dir, "favicon.ico"))

            terms_path = os.path.join(target_dir, "TERMS_AND_DISCLAIMER.txt")
            with open(terms_path, "w", encoding="utf-8") as f:
                f.write(TERMS_TEXT)

            unins_exe = os.path.join(target_dir, "unins000.exe")
            if getattr(sys, "frozen", False):
                shutil.copy2(sys.executable, unins_exe)
            else:
                shutil.copy2(os.path.abspath(__file__), os.path.join(target_dir, "installer_gui.py"))

            appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "valorant-rpc")
            os.makedirs(appdata_dir, exist_ok=True)
            for ver_path in (os.path.join(target_dir, "version.txt"), os.path.join(appdata_dir, "version.txt")):
                try:
                    with open(ver_path, "w", encoding="utf-8") as vf:
                        vf.write(APP_VERSION)
                except Exception:
                    pass

            self._append_log("Registering persistent Windows startup & Task Scheduler...", 85)
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{target_exe}" --startup')
            except Exception:
                pass

            try:
                subprocess.run(
                    [
                        "schtasks",
                        "/Create",
                        "/TN",
                        APP_NAME,
                        "/TR",
                        f'"{target_exe}" --startup',
                        "/SC",
                        "ONLOGON",
                        "/RL",
                        "HIGHEST",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except Exception:
                pass

            try:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY, 0, winreg.KEY_WRITE) as ukey:
                    winreg.SetValueEx(ukey, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
                    winreg.SetValueEx(ukey, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION_NUMERIC)
                    winreg.SetValueEx(ukey, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
                    winreg.SetValueEx(ukey, "DisplayIcon", 0, winreg.REG_SZ, target_exe)
                    winreg.SetValueEx(ukey, "InstallLocation", 0, winreg.REG_SZ, target_dir)
                    unins_cmd = (
                        f'"{unins_exe}" --uninstall'
                        if os.path.exists(unins_exe)
                        else f'"{sys.executable}" "{os.path.join(target_dir, "installer_gui.py")}" --uninstall'
                    )
                    winreg.SetValueEx(ukey, "UninstallString", 0, winreg.REG_SZ, unins_cmd)
                    winreg.SetValueEx(ukey, "HelpLink", 0, winreg.REG_SZ, "https://karlchastin.dev/")
                    winreg.SetValueEx(ukey, "URLInfoAbout", 0, winreg.REG_SZ, "https://karlchastin.dev/")
                    winreg.SetValueEx(ukey, "URLUpdateInfo", 0, winreg.REG_SZ, "https://github.com/karlchastin/VALORANT-Discord-Rich-Presence")
                    winreg.SetValueEx(ukey, "NoModify", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(ukey, "NoRepair", 0, winreg.REG_DWORD, 1)
            except Exception:
                pass

            try:
                app_paths_key = r"Software\Microsoft\Windows\CurrentVersion\App Paths\valorant-rpc.exe"
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, app_paths_key, 0, winreg.KEY_WRITE) as ap_key:
                    winreg.SetValueEx(ap_key, "", 0, winreg.REG_SZ, target_exe)
                    winreg.SetValueEx(ap_key, "Path", 0, winreg.REG_SZ, target_dir)
            except Exception:
                pass

            for sm_base in (
                os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                os.environ.get("APPDATA", ""),
            ):
                if not sm_base:
                    continue
                sm_dir = os.path.join(sm_base, r"Microsoft\Windows\Start Menu\Programs")
                if os.path.isdir(sm_dir):
                    sm_lnk = os.path.join(sm_dir, "VALORANT RPC.lnk")
                    create_shortcut(sm_lnk, target_exe, "--startup", target_dir, "VALORANT Rich Presence")

            if self.opt_desktop.get():
                desktop_dirs = get_desktop_dirs()
                if desktop_dirs:
                    dt_lnk = os.path.join(desktop_dirs[0], "VALORANT RPC.lnk")
                    create_shortcut(dt_lnk, target_exe, "--startup", target_dir, "VALORANT Rich Presence")

            self._append_log("Completed", 100)
            self.installing = False
            self.after(300, lambda: self._show_step(4))
        except Exception as e:
            self.installing = False
            self._append_log(f"Error: {e}")
            self.after(0, lambda: messagebox.showerror("Setup Error", str(e)))
            self.after(0, lambda: self.btn_cancel.config(state=tk.NORMAL))

    def _build_step_finished(self) -> None:
        done_verb = "repairing" if self.repair_mode else "installing"
        self.header_title.config(text=f"Completing the {APP_NAME} Setup Wizard")
        self.header_subtitle.config(text=f"Setup has finished {done_verb} {APP_NAME} on your computer.")

        frame = tk.Frame(self.content, bg=self.BG_DARK, padx=26, pady=24)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="Click Finish to exit Setup.",
            font=("Segoe UI", 10),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 18))

        tk.Checkbutton(
            frame,
            text=f"Launch {APP_NAME}",
            variable=self.opt_launch_now,
            font=("Segoe UI", 9),
            fg=self.TEXT_LIGHT,
            bg=self.BG_DARK,
            selectcolor=self.BG_PANEL,
            activebackground=self.BG_DARK,
            activeforeground=self.TEXT_LIGHT,
            anchor="w",
        ).pack(fill=tk.X)

        self.btn_back.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.DISABLED)
        self.btn_next.config(text="Finish", state=tk.NORMAL, bg=self.ACCENT_RED)

    def _on_back(self) -> None:
        if self.current_step > 0 and not self.installing:
            self._show_step(self.current_step - 1)

    def _on_next(self) -> None:
        if self.current_step == 0:
            self._show_step(1)
        elif self.current_step == 1:
            if self.accepted_terms.get() == 1:
                self._show_step(2)
        elif self.current_step == 2:
            self._show_step(3)
        elif self.current_step == 4:
            if self.opt_launch_now.get():
                target_exe = os.path.join(os.path.abspath(self.install_dir.get()), "valorant-rpc.exe")
                if os.path.exists(target_exe):
                    subprocess.Popen([target_exe, "--startup"], cwd=os.path.dirname(target_exe))
            self.destroy()

    def _on_cancel(self) -> None:
        if self.installing:
            return
        if show_themed_dialog(
            window_title=f"Exit {APP_NAME} Setup",
            header_text=f"Exit {APP_NAME} Setup?",
            message_text=f"Setup is not complete. If you exit now, {APP_NAME} will not be installed.\n\nAre you sure you want to exit Setup?",
            primary_text="Yes",
            secondary_text="No",
            parent=self,
        ):
            self.destroy()

def run_gui_uninstaller() -> None:
    if not show_themed_dialog(
        window_title=f"Uninstall {APP_NAME}",
        header_text=f"Uninstall {APP_NAME}",
        message_text=f"Are you sure you want to completely remove {APP_NAME} and all of its components from your computer?",
        primary_text="Uninstall",
        secondary_text="Cancel",
    ):
        return

    subprocess.run(
        ["taskkill", "/F", "/IM", "valorant-rpc.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    install_dir = DEFAULT_INSTALL_DIR
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY, 0, winreg.KEY_READ) as ukey:
            val, _ = winreg.QueryValueEx(ukey, "InstallLocation")
            if val:
                install_dir = val
    except Exception:
        pass

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except Exception:
        pass

    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", APP_NAME, "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception:
        pass

    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY)
    except Exception:
        pass

    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\valorant-rpc.exe")
    except Exception:
        pass

    shortcut_candidates = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs\VALORANT RPC.lnk"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\VALORANT RPC.lnk"),
    ] + [os.path.join(d, "VALORANT RPC.lnk") for d in get_desktop_dirs()]
    for lnk in shortcut_candidates:
        if os.path.exists(lnk):
            try:
                os.remove(lnk)
            except Exception:
                pass

    if os.path.isdir(install_dir):
        try:
            for item in os.listdir(install_dir):
                if item.lower().startswith("unins"):
                    continue
                item_path = os.path.join(install_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        os.remove(item_path)
                except Exception:
                    pass
        except Exception:
            pass

        current_pid = os.getpid()
        clean_dir = install_dir.replace("'", "''")
        cmd = (
            f"$targetPid = {current_pid}; "
            f"for ($i = 0; $i -lt 60; $i++) {{ "
            f"  if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) {{ break }}; "
            f"  Start-Sleep -Milliseconds 500 "
            f"}}; "
            f"Start-Sleep -Milliseconds 500; "
            f"Remove-Item -Path '{clean_dir}' -Recurse -Force -ErrorAction SilentlyContinue"
        )
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", cmd],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

    show_themed_dialog(
        window_title=f"Uninstall {APP_NAME}",
        header_text="Uninstallation Complete",
        message_text=f"{APP_NAME} has been successfully removed from your computer.",
        primary_text="OK",
    )

def run_silent_update() -> None:

    import time

    args = sys.argv[1:]
    target_exe = os.path.join(DEFAULT_INSTALL_DIR, "valorant-rpc.exe")
    version_tag = APP_VERSION

    for i, arg in enumerate(args):
        if arg == "--silent-update" and i + 1 < len(args) and not args[i + 1].startswith("--"):
            target_exe = os.path.abspath(args[i + 1])
        elif arg == "--version-tag" and i + 1 < len(args):
            version_tag = args[i + 1].strip()

    target_dir = os.path.dirname(target_exe)
    exe_source = resource_path("valorant-rpc.exe")
    if not os.path.exists(exe_source) or os.path.abspath(exe_source) == os.path.abspath(sys.executable):
        exe_source = resource_path(os.path.join("dist", "valorant-rpc.exe"))

    if not os.path.exists(exe_source):
        sys.exit(1)

    subprocess.run(
        ["taskkill", "/F", "/IM", "valorant-rpc.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    os.makedirs(target_dir, exist_ok=True)
    replaced = False
    for _ in range(15):
        try:
            shutil.copy2(exe_source, target_exe)
            replaced = True
            break
        except PermissionError:
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)

    if not replaced:
        elevate_if_needed()
        return

    try:
        if getattr(sys, "frozen", False):
            shutil.copy2(sys.executable, os.path.join(target_dir, "unins000.exe"))
    except Exception:
        pass

    clean_ver = str(version_tag).strip().lstrip("vV") or APP_VERSION_NUMERIC
    normalized_tag = f"v{clean_ver}"

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY, 0, winreg.KEY_SET_VALUE) as ukey:
            winreg.SetValueEx(ukey, "DisplayVersion", 0, winreg.REG_SZ, clean_ver)
    except Exception:
        pass

    appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "valorant-rpc")
    os.makedirs(appdata_dir, exist_ok=True)
    for ver_path in (os.path.join(target_dir, "version.txt"), os.path.join(appdata_dir, "version.txt")):
        try:
            with open(ver_path, "w", encoding="utf-8") as vf:
                vf.write(normalized_tag)
        except Exception:
            pass

    try:
        with open(os.path.join(appdata_dir, "just_updated.txt"), "w", encoding="utf-8") as uf:
            uf.write(clean_ver)
    except Exception:
        pass

    subprocess.Popen(
        [target_exe, "--startup", f"--updated-to={clean_ver}"],
        cwd=target_dir,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    sys.exit(0)

def _parse_ver(v: str) -> list[int]:
    return [int(x) for x in str(v).strip("vV").split(".") if x.isdigit()]

def detect_existing_installation() -> tuple[str | None, str | None]:

    install_dir = DEFAULT_INSTALL_DIR
    reg_version = None
    has_reg = False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY, 0, winreg.KEY_READ) as ukey:
            has_reg = True
            val, _ = winreg.QueryValueEx(ukey, "InstallLocation")
            if val:
                install_dir = val
            try:
                ver_val, _ = winreg.QueryValueEx(ukey, "DisplayVersion")
                if ver_val:
                    reg_version = f"v{ver_val}" if not str(ver_val).lower().startswith("v") else str(ver_val)
            except Exception:
                pass
    except Exception:
        pass

    target_exe = os.path.join(install_dir, "valorant-rpc.exe")
    if not os.path.isfile(target_exe) or not has_reg:
        return None, None

    candidates = [reg_version or APP_VERSION]
    appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "valorant-rpc")
    for vf in (os.path.join(install_dir, "version.txt"), os.path.join(appdata_dir, "version.txt")):
        try:
            if os.path.isfile(vf):
                with open(vf, "r", encoding="utf-8") as f:
                    tag = f.read().strip()
                    if tag:
                        candidates.append(tag)
        except Exception:
            pass

    best_ver = candidates[0]
    for c in candidates[1:]:
        if _parse_ver(c) > _parse_ver(best_ver):
            best_ver = c

    return install_dir, best_ver

if __name__ == "__main__":
    if "--silent-update" in sys.argv[1:]:
        run_silent_update()
    elevate_if_needed()
    exe_basename = os.path.basename(sys.executable).lower() if getattr(sys, "frozen", False) else ""
    if "--uninstall" in sys.argv[1:] or exe_basename.startswith("unins"):
        run_gui_uninstaller()
    else:
        existing_dir, existing_ver = detect_existing_installation()
        if existing_dir and existing_ver:
            installer_parsed = _parse_ver(APP_VERSION)
            installed_parsed = _parse_ver(existing_ver)

            if installer_parsed < installed_parsed:
                show_themed_dialog(
                    window_title=f"{APP_NAME} Setup",
                    header_text="Newer Version Already Installed",
                    message_text=(
                        f"Cannot install {APP_NAME} {APP_VERSION}.\n\n"
                        f"A newer version ({existing_ver}) is already installed on your computer. "
                        f"Downgrading to an older version is not permitted."
                    ),
                    primary_text="OK",
                )
                sys.exit(1)
            elif installer_parsed > installed_parsed:
                show_themed_dialog(
                    window_title=f"{APP_NAME} Setup",
                    header_text="Automatic Updates Enabled",
                    message_text=(
                        f"{APP_NAME} ({existing_ver}) is already installed on your computer.\n\n"
                        f"Running a newer installer manually is disabled because {APP_NAME} updates itself "
                        f"automatically on Windows startup and when VALORANT launches."
                    ),
                    primary_text="OK",
                )
                sys.exit(0)
            else:
                wants_repair = show_themed_dialog(
                    window_title=f"Repair {APP_NAME}",
                    header_text=f"Repair {APP_NAME} ({existing_ver})",
                    message_text=(
                        f"{APP_NAME} ({existing_ver}) is already installed on your computer.\n\n"
                        f"Would you like to repair your existing {APP_NAME} installation instead?"
                    ),
                    primary_text="Yes",
                    secondary_text="No",
                )
                if not wants_repair:
                    sys.exit(0)
                app = SetupWizard(repair_mode=True, existing_dir=existing_dir)
                app.mainloop()
        else:
            app = SetupWizard()
            app.mainloop()
