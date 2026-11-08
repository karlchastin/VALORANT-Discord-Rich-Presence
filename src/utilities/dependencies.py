import sys
import subprocess
import os

REQUIRED_PACKAGES = [
    'urllib3',
    'iso8601',
    'requests',
    'pypresence',
    'valclient',
    'pystray',
    'psutil',
    'PIL',
]

PACKAGE_MAPPING = {
    'PIL': 'Pillow',
}

def check_dependencies():

    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            __import__(package)
        except ImportError:
            pip_name = PACKAGE_MAPPING.get(package, package)
            missing.append(pip_name)

    return missing

def install_all_dependencies():

    requirements_path = get_requirements_path()
    if not os.path.exists(requirements_path):
        return False
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", requirements_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, Exception):
        return False

def _is_frozen():

    return getattr(sys, 'frozen', False)

def get_requirements_path():

    if _is_frozen():
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, "requirements.txt")

def install_package(pip_name):

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pip_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, Exception):
        return False

def verify_and_install():

    if _is_frozen():
        return True, []
    missing = check_dependencies()
    if missing:
        return False, missing
    return True, []
