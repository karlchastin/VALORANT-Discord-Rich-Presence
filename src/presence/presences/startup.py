from ...localization.localization import Localizer

def presence(rpc, client=None, data=None, content_data=None, config=None):
    rpc.update(
        details=Localizer.get_localized_text("presences", "startup", "loading"),
        large_image="game_icon",
        large_text="VALORANT",
    )
