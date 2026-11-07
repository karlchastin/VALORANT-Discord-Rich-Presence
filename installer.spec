import os

block_cipher = None

datas = [
    ('favicon.ico', '.'),
    ('TERMS_AND_DISCLAIMER.txt', '.'),
]

if os.path.exists(os.path.join('dist', 'valorant-rpc.exe')):
    datas.append((os.path.join('dist', 'valorant-rpc.exe'), '.'))

a = Analysis(
    ['installer_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox', 'winreg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest', 'pydoc', 'doctest', 'pdb', 'sqlite3', 'xmlrpc', 'ftplib',
        'imaplib', 'smtplib', 'telnetlib', 'turtle', 'turtledemo', 'venv',
        'ensurepip', 'lib2to3', 'distutils', 'setuptools', 'pkg_resources',
        'pip', 'wheel', 'test', 'curses', 'multiprocessing', 'asyncio',
        'ssl', '_ssl', 'decimal', '_decimal', 'requests', 'urllib3', 'psutil',
        'valclient', 'pypresence', 'pystray', 'PIL', 'iso8601', 'colr',
        'InquirerPy', 'prompt_toolkit', 'pygments', 'wcwidth',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VALORANT-RPC-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    version='version_info.txt',
    icon='favicon.ico',
)
