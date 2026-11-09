import json
import os
import sys
from .filepath import Filepath

class Program_Data:

    installs_path = os.path.expandvars("%PROGRAMDATA%\\valorant-tools\\installs.json")

    @staticmethod
    def update_file_location():
        try:
            Program_Data.check_for_folder()
            if getattr(sys, "frozen", False):
                path = sys.executable
                installs = Program_Data.fetch_installs()
                installs["valorant-rpc"] = path
                Program_Data.modify_installs(installs)
        except Exception:
            pass

    @staticmethod
    def fetch_installs():
        try:
            with open(Program_Data.installs_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return Program_Data.create_installs_file()

    @staticmethod
    def modify_installs(payload):

        try:
            Program_Data.check_for_folder()
            dir_name = os.path.dirname(Program_Data.installs_path)
            tmp_path = os.path.join(dir_name, f"installs.tmp.{os.getpid()}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, Program_Data.installs_path)
        except Exception:
            pass
        return Program_Data.fetch_installs()

    modify_isntalls = modify_installs

    @staticmethod
    def create_installs_file():
        return Program_Data.modify_installs({})

    @staticmethod
    def check_for_folder():
        try:
            programdata_folder = Filepath.get_programdata_folder()
            if not os.path.isdir(programdata_folder):
                os.makedirs(programdata_folder, exist_ok=True)
        except Exception:
            pass
