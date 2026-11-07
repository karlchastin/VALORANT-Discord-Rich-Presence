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
    if not data:
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

    session_loop_state = data.get("sessionLoopState") or pp.get("partyOwnerSessionLoopState") or mp.get("sessionLoopState") or ""
    if session_loop_state and "REPLAY" in str(session_loop_state).upper():
        party_state_text, party_size = Utilities.build_party_state(data)
        account_level = Utilities.fetch_account_level(client, data)
        party_id = data.get("partyId") or pp.get("partyId") or None
        rpc.update(
            state=party_state_text,
            details=Localizer.get_localized_text("presences", "replay", "watching"),
            large_image="game_icon",
            large_text=f"{Localizer.get_localized_text('presences','leveling','level')} {account_level}",
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
