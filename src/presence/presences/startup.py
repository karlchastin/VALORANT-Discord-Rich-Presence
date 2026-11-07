from ...localization.localization import Localizer

def presence(rpc, client=None, data=None, content_data=None, config=None):
    rpc.update(
        details=Localizer.get_localized_text("presences", "startup", "loading"),
        large_image="game_icon",
        large_text="VALORANT",
        buttons=[{
            "label": Localizer.get_localized_text("presences", "startup", "view_github"),
            "url": "https://github.com/karlchastin/valorant-rpc",
        }] if Localizer.get_config_value("startup", "show_github_link") else None,
    )
