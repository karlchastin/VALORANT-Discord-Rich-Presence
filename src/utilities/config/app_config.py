import copy, os
from valclient.client import Client

from ..filepath import Filepath

from ...localization.locales import Locales
from ...localization.localization import Localizer

default_config = {
    "version": "v4.0.6",
    "region": ["",Client.fetch_regions()],
    "client_id": 1567969518280773853,
    "presence_refresh_interval": 1,
    "locale": ["en-US", ["en-US"]],
    "presences": {
        "menu": {
            "show_rank_in_comp_lobby": True,
        },
        "modes": {
            "all": {
                "small_image": ["agent",["rank","agent","map"]],
                "large_image": ["map",["rank","agent","map"]],
            },
            "range": {
                "show_rank_in_range": False,
            }
        }
    },
    "startup": {
        "game_launch_timeout": 50,
        "presence_timeout": 60,
        "auto_launch_skincli": False,
        "auto_launch_valorant": False,
        "auto_update": True,
    },
}

class Config:

    _runtime_config: dict | None = None

    @staticmethod
    def cleanup_legacy_config_file() -> None:
        try:
            appdata_dir = Filepath.get_appdata_folder()
            legacy_cfg = Filepath.get_path(os.path.join(appdata_dir, "config.json"))
            if os.path.exists(legacy_cfg):
                os.remove(legacy_cfg)
        except Exception:
            pass

    @staticmethod
    def fetch_config() -> dict:
        Config.cleanup_legacy_config_file()
        if Config._runtime_config is None:
            Config._runtime_config = copy.deepcopy(default_config)
        return Config._runtime_config

    @staticmethod
    def modify_config(new_config: dict) -> dict:
        Config.cleanup_legacy_config_file()
        Config._runtime_config = new_config
        return Config._runtime_config

    @staticmethod
    def check_config() -> dict:
        config = Config.fetch_config()
        unlocalized_config = Config.localize_config(config, True)

        def check_for_new_vars(blank, current):
            for key, value in blank.items():
                if key not in current.keys():
                    current[key] = copy.deepcopy(value)
                if type(value) != type(current[key]):
                    current[key] = copy.deepcopy(value)
                if key == "version":
                    current[key] = value
                if key == "region":
                    current[key][1] = Client.fetch_regions()
                if isinstance(value, list):
                    current[key][1] = blank[key][1]
                    if current[key][0] not in blank[key][1]:
                        current[key][0] = blank[key][0]
                if isinstance(value, dict):
                    check_for_new_vars(value, current[key])
            return current

        def remove_unused_vars(blank, current):
            def check(bl, cur):
                for key, value in list(cur.items()):
                    if key not in bl.keys():
                        del cur[key]
                    if isinstance(value, dict) and key in list(cur.keys()):
                        check(bl[key], value)

            check(blank, current)
            return current

        unlocalized_config = check_for_new_vars(default_config, unlocalized_config)
        unlocalized_config = remove_unused_vars(default_config, unlocalized_config)
        config = Config.localize_config(unlocalized_config)
        Config.modify_config(config)
        return config

    @staticmethod
    def localize_config(config, unlocalize=False):
        def check(blank, current):
            for key, value in list(blank.items() if not unlocalize else current.items()):
                new_key = Localizer.get_config_key(key) if not unlocalize else Localizer.unlocalize_key(key)
                if new_key != key:
                    current[new_key] = current[key]
                    del current[key]

                if isinstance(value, list):
                    if not unlocalize:
                        new_options = [Localizer.get_config_key(x) for x in value[1]]
                        current[new_key][0] = Localizer.get_config_key(current[new_key][0])
                        current[new_key][1] = new_options
                    else:
                        new_options = [Localizer.unlocalize_key(x) for x in value[1]]
                        unlocalized = Localizer.unlocalize_key(current[new_key][0])
                        value[0] = unlocalized
                        value[1] = new_options

                if isinstance(value, dict):
                    check(value, current[new_key])

        check(default_config, config)
        return config

    @staticmethod
    def create_default_config() -> dict:
        Config.cleanup_legacy_config_file()
        Config._runtime_config = copy.deepcopy(default_config)
        return Config._runtime_config
