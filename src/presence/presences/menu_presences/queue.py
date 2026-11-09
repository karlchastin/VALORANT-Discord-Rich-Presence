from ...presence_utilities import Utilities
from ....localization.localization import Localizer

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data:
        return

    party_data = data.get("partyPresenceData") or {}
    party_state, party_size = Utilities.build_party_state(data)
    queue_entry_time = data.get("queueEntryTime") or party_data.get("queueEntryTime", "0001.01.01-00.00.00")
    start_time = Utilities.iso8601_to_epoch(queue_entry_time)
    small_image, mode_name = Utilities.fetch_mode_data(data, content_data)
    small_text = mode_name

    account_level = Utilities.fetch_account_level(client, data)
    party_id = data.get("partyId") or party_data.get("partyId") or None
    queue_label = Localizer.get_localized_text("presences", "client_states", "queue") or "In Queue"
    level_label = Localizer.get_localized_text("presences", "leveling", "level") or "Level"
    details = f"{queue_label} - {mode_name}" if mode_name else queue_label

    rpc.update(
        state=party_state,
        details=details,
        start=start_time,
        large_image="game_icon_white",
        large_text=f"{level_label} {account_level}",
        small_image=small_image,
        small_text=small_text,
        party_size=party_size,
        party_id=party_id,
    )
