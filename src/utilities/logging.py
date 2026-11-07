import logging, os
from .filepath import Filepath

class Logger:

    @staticmethod
    def create_logger():
        appdata_dir = Filepath.get_appdata_folder()
        os.makedirs(appdata_dir, exist_ok=True)
        log_path = os.path.join(appdata_dir, "rpc.log")
        try:
            logging.basicConfig(
                filename=log_path,
                filemode="a",
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
        logger = logging.getLogger('rpc')
        logger.debug(data)
