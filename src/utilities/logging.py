import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
from .filepath import Filepath

_MAX_LOG_BYTES = 1_048_576

class Logger:

    @staticmethod
    def create_logger():

        appdata_dir = Filepath.get_appdata_folder()
        os.makedirs(appdata_dir, exist_ok=True)
        legacy_logs_dir = os.path.join(appdata_dir, "logs")
        if os.path.isdir(legacy_logs_dir):
            shutil.rmtree(legacy_logs_dir, ignore_errors=True)
        log_path = os.path.join(appdata_dir, "rpc.log")
        try:
            handler = RotatingFileHandler(
                log_path,
                maxBytes=_MAX_LOG_BYTES,
                backupCount=1,
                encoding="utf-8",
                delay=True,
            )
            logging.basicConfig(
                handlers=[handler],
                format="%(asctime)s.%(msecs)d %(name)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
                level=logging.DEBUG,
            )
        except Exception:
            logging.basicConfig(level=logging.WARNING)
        for name in ("urllib3.connectionpool", "asyncio", "PIL.Image"):
            logging.getLogger(name).setLevel(logging.WARNING)
        logger = logging.getLogger("rpc")
        logger.debug("created log")

    @staticmethod
    def debug(data):
        logger = logging.getLogger("rpc")
        logger.debug(data)
