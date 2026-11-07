from .locales import Locales

class Localizer:

    locale = "en-US"
    config = None

    @staticmethod
    def get_localized_text(*keys):
        def _resolve(root, path):
            node = root
            for key in path:
                if not isinstance(node, dict):
                    return None
                node = node.get(key)
                if node is None:
                    return None
            return node

        res = _resolve(Locales.get(Localizer.locale, {}), keys)
        if res is not None:
            return res
        return _resolve(Locales.get("en-US", {}), keys)

    @staticmethod
    def get_config_key(key):
        try:
            for k,value in Locales[Localizer.locale]["config"].items():

                if k == key:
                    return value
            return key
        except:
            return key

    @staticmethod
    def unlocalize_key(key):
        for k,value in Locales[Localizer.locale]["config"].items():

            if value == key:
                return k
        return key

    @staticmethod
    def get_config_value(*keys):
        if not Localizer.config:
            return None
        localized_keys = [Localizer.get_config_key(key) for key in keys]
        result = Localizer.config
        for key in localized_keys:
            if not isinstance(result, dict) or key not in result:
                return None
            result = result[key]
        return result

    @staticmethod
    def set_locale(config):
        Localizer.locale = "en-US"

    @staticmethod
    def prompt_locale(config):
        if "locale" in config:
            config["locale"][0] = "en-US"
            config["locale"][1] = ["en-US"]
        return config
