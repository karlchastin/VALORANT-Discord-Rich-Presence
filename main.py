import os
import sys
import socket
import traceback
import requests
import urllib3
import urllib3.util.connection

urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

_SHARED_HTTP_SESSION = requests.Session()
_HTTP_ADAPTER = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=32)
_SHARED_HTTP_SESSION.mount("https://", _HTTP_ADAPTER)
_SHARED_HTTP_SESSION.mount("http://", _HTTP_ADAPTER)

original_request = requests.Session.request
def patched_request(*args, **kwargs):
    kwargs["verify"] = False
    kwargs.setdefault("timeout", 5)
    return original_request(*args, **kwargs)
requests.Session.request = patched_request

def _pooled_api_request(method, url, **kwargs):
    return _SHARED_HTTP_SESSION.request(method=method, url=url, **kwargs)

requests.api.request = _pooled_api_request
requests.request = _pooled_api_request
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import importlib.metadata
_original_version = importlib.metadata.version
def _patched_version(pkg_name):
    try:
        return _original_version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return "99.99.99"
importlib.metadata.version = _patched_version

if not getattr(sys, "frozen", False):
    try:
        from src.utilities.dependencies import (
            verify_and_install,
            install_all_dependencies,
        )
        deps_ok, missing_deps = verify_and_install()
        if not deps_ok and missing_deps:
            install_all_dependencies()
    except Exception:
        pass

from src.startup import Startup
from src.utilities.logging import Logger

VERSION = "v4.0.4"

if __name__ == "__main__":
    try:
        app = Startup()
    except Exception as e:
        try:
            Logger.create_logger()
            Logger.debug(f"[fatal] Unhandled startup exception: {e}\n{traceback.format_exc()}")
        except Exception:
            pass
        os._exit(1)
