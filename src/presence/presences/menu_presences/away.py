from ....localization.localization import Localizer
from ...presence_utilities import Utilities

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data:
        return

    pp = data.get("partyPresenceData") or {}
    party_state, party_size = Utilities.build_party_state(data)
    small_image, mode_name = Utilities.fetch_mode_data(data, content_data)
    buttons = Utilities.get_join_state(client, config, data)
    small_text = mode_name

    queue_id = (data.get("queueId") or pp.get("queueId") or "").lower().strip()
    if queue_id.startswith("console_"):
        queue_id = queue_id[8:]
    if queue_id == "competitive" and Localizer.get_config_value("presences", "menu", "show_rank_in_comp_lobby"):
        small_image, small_text = Utilities.fetch_rank_data(client, content_data)

    account_level = Utilities.fetch_account_level(client, data)
    party_id = data.get("partyId") or pp.get("partyId") or None
    away_label = Localizer.get_localized_text("presences", "client_states", "away") or "Away"
    level_label = Localizer.get_localized_text("presences", "leveling", "level") or "Level"
    details = f"{away_label} - {mode_name}" if mode_name else away_label

    rpc.update(
        state=party_state,
        details=details,
        large_image="game_icon_yellow",
        large_text=f"{level_label} {account_level}",
        small_image=small_image,
        small_text=small_text,
        party_size=party_size,
        party_id=party_id,
        buttons=buttons,
    )
