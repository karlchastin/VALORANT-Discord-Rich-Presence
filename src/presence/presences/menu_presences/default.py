from ...presence_utilities import Utilities
from ....localization.localization import Localizer

from .away import presence as away

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data:
        return

    is_afk = data.get("isIdle", False)
    if is_afk:
        away(rpc, client, data, content_data, config)
    else:
        pp = data.get("partyPresenceData") or {}
        party_state, party_size = Utilities.build_party_state(data)
        small_image, mode_name = Utilities.fetch_mode_data(data, content_data)
        small_text = mode_name
        buttons = Utilities.get_join_state(client, config, data)

        queue_id = (data.get("queueId") or pp.get("queueId") or "").lower().strip()
        if queue_id.startswith("console_"):
            queue_id = queue_id[8:]
        if queue_id == "competitive" and Localizer.get_config_value("presences", "menu", "show_rank_in_comp_lobby"):
            small_image, small_text = Utilities.fetch_rank_data(client, content_data)

        account_level = Utilities.fetch_account_level(client, data)
        party_id = data.get("partyId") or pp.get("partyId") or None
        menu_label = Localizer.get_localized_text("presences", "client_states", "menu") or "In Lobby"
        level_label = Localizer.get_localized_text("presences", "leveling", "level") or "Level"
        details = f"{menu_label} - {mode_name}" if mode_name else menu_label

        rpc.update(
            state=party_state,
            details=details,
            large_image="game_icon",
            large_text=f"{level_label} {account_level}",
            small_image=small_image,
            small_text=small_text,
            party_size=party_size,
            party_id=party_id,
            buttons=buttons,
        )
