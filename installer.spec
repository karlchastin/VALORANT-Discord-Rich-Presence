import os
import zlib

block_cipher = None

datas = [
    ('favicon.ico', '.'),
    ('TERMS_AND_DISCLAIMER.txt', '.'),
]

_built_exe = os.path.join('dist', 'valorant-rpc.exe')
if os.path.exists(_built_exe):
    os.makedirs('build', exist_ok=True)
    _pkg_path = os.path.join('build', 'app_payload.pkg')
    with open(_built_exe, 'rb') as _src_f:
        _raw_bytes = _src_f.read()
    with open(_pkg_path, 'wb') as _dst_f:
        _dst_f.write(b'VRPCPKG1' + zlib.compress(_raw_bytes, level=6))
    datas.append((_pkg_path, '.'))

a = Analysis(
    ['installer_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox', 'winreg', 'zlib'],
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
    upx=False,
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
