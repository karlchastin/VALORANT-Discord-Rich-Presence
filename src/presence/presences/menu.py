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
    party_state = data.get("partyState") or pp.get("partyState", "")
    queue_id = (data.get("queueId") or pp.get("queueId") or "").lower()
    prov_root = str(data.get("provisioningFlow") or "").upper()

    if (
        party_state == "CUSTOM_GAME_SETUP"
        or pp.get("partyState") == "CUSTOM_GAME_SETUP"
        or queue_id == "custom"
        or "CUSTOMGAME" in prov_root
    ):
        custom_setup.presence(rpc, client=client, data=data, content_data=content_data, config=config)
        return

    queue_entry_time = data.get("queueEntryTime") or pp.get("queueEntryTime", "0001.01.01-00.00.00")
    matchmaking_state = data.get("matchmakingState") or pp.get("matchmakingState") or ""
    is_matchmaking = bool(data.get("isMatchmakingGame") or pp.get("isMatchmakingGame"))

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
