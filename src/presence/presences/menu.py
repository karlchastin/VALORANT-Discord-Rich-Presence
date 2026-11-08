from .menu_presences import (default, queue, custom_setup)
from ..presence_utilities import Utilities
from ...localization.localization import Localizer

_MATCHMAKING_STATES = frozenset({
    "MATCHMAKING", "MATCHMADE_GAME_STARTING", "STARTING_MATCH", "QUEUED", "SEARCHING", "IN_QUEUE", "INQUEUE", "INPROGRESS",
})

_STATE_TYPES = {
    "DEFAULT": default,
    "MATCHMAKING": queue,
    "MATCHMADE_GAME_STARTING": queue,
    "STARTING_MATCH": queue,
    "IN_QUEUE": queue,
    "InQueue": queue,
    "INQUEUE": queue,
    "SEARCHING": queue,
    "CUSTOM_GAME_SETUP": custom_setup,
}

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data or Utilities.is_range(data):
        return

    pp = data.get("partyPresenceData") or {}
    mp = data.get("matchPresenceData") or {}
    party_state = data.get("partyState") or pp.get("partyState", "")
    queue_id = (data.get("queueId") or pp.get("queueId") or mp.get("queueId") or "").lower()
    prov_root = str(data.get("provisioningFlow") or "").upper()
    prov_match = str(mp.get("provisioningFlow") or "").upper()

    if (
        party_state == "CUSTOM_GAME_SETUP"
        or pp.get("partyState") == "CUSTOM_GAME_SETUP"
        or queue_id == "custom"
        or "CUSTOMGAME" in prov_root
        or "CUSTOMGAME" in prov_match
    ):
        custom_setup.presence(rpc, client=client, data=data, content_data=content_data, config=config)
        return

    queue_entry_time = data.get("queueEntryTime") or pp.get("queueEntryTime", "0001.01.01-00.00.00")
    matchmaking_state = data.get("matchmakingState") or pp.get("matchmakingState") or mp.get("matchmakingState") or ""
    is_matchmaking = bool(data.get("isMatchmakingGame") or pp.get("isMatchmakingGame"))

    if Utilities.is_replay_session(data):
        party_state_text, party_size = Utilities.build_party_state(data)
        _, log_map = Utilities.detect_replay_from_log()
        map_path = (
            data.get("MapID")
            or data.get("matchMap")
            or mp.get("matchMap")
            or pp.get("partyOwnerMatchMap")
            or log_map
            or ""
        )
        map_name, map_loc = Utilities.fetch_map_data({"MapID": map_path}, content_data) if map_path and content_data else ("", "")
        replay_label = Localizer.get_localized_text("presences", "replay", "watching") or "Watching replay"
        if map_name:
            large_image = Utilities.get_map_splash_key(map_name)
            large_text = map_loc or map_name
        else:
            account_level = Utilities.fetch_account_level(client, data)
            large_image = "game_icon"
            large_text = f"{Localizer.get_localized_text('presences','leveling','level')} {account_level}"
        party_id = data.get("partyId") or pp.get("partyId") or None
        rpc.update(
            state=party_state_text,
            details=replay_label,
            large_image=large_image,
            large_text=large_text,
            small_image="mode_replay",
            small_text=replay_label,
            party_size=party_size,
            party_id=party_id,
        )
        return

    if party_state and party_state in _STATE_TYPES:
        _STATE_TYPES[party_state].presence(rpc, client=client, data=data, content_data=content_data, config=config)
    elif queue_id:
        is_in_queue = (
            (queue_entry_time and queue_entry_time != "0001.01.01-00.00.00")
            or (matchmaking_state and str(matchmaking_state).upper() in _MATCHMAKING_STATES)
            or is_matchmaking
        )
        if is_in_queue:
            queue.presence(rpc, client=client, data=data, content_data=content_data, config=config)
        else:
            default.presence(rpc, client=client, data=data, content_data=content_data, config=config)
    else:
        default.presence(rpc, client=client, data=data, content_data=content_data, config=config)
