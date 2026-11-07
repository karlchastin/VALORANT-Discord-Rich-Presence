import os, sys, json
from .filepath import Filepath

class Program_Data:

    installs_path = os.path.expandvars("%PROGRAMDATA%\\valorant-tools\\installs.json")

    @staticmethod
    def update_file_location():
        try:
            Program_Data.check_for_folder()
            if getattr(sys, 'frozen', False):
                path = sys.executable
                installs = Program_Data.fetch_installs()
                installs["valorant-rpc"] = path
                Program_Data.modify_isntalls(installs)
        except Exception:
            pass

    @staticmethod
    def fetch_installs():
        try:
            with open(Program_Data.installs_path) as f:
                return json.load(f)
        except Exception:
            return Program_Data.create_installs_file()

    @staticmethod
    def modify_isntalls(payload):
        try:
            with open(Program_Data.installs_path, "w") as f:
                json.dump(payload, f)
        except Exception:
            pass
        return Program_Data.fetch_installs()

    @staticmethod
    def create_installs_file():
        try:
            with open(Program_Data.installs_path, "w") as f:
                json.dump({}, f)
        except Exception:
            return {}
        return Program_Data.fetch_installs()

    @staticmethod
    def check_for_folder():
        try:
            programdata_folder = Filepath.get_programdata_folder()
            if not os.path.isdir(programdata_folder):
                os.makedirs(programdata_folder, exist_ok=True)
        except Exception:
            pass
