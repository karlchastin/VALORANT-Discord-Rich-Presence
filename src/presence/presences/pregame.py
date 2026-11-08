from ..presence_utilities import Utilities
from ...localization.localization import Localizer
from . import ingame, menu
from valclient.exceptions import PhaseError
import time

_PREGAME_TIMER_CACHE = {
    "match_id": None,
    "last_rem_ns": 0,
    "end_ts": None,
}

def _resolve_pregame_end_time(match_id: str, pregame_data: dict) -> int | None:

    rem_ns = pregame_data.get("PhaseTimeRemainingNS", 0) or 0
    if rem_ns <= 0:
        return None

    now = time.time()
    rem_s = rem_ns / 1_000_000_000.0
    candidate_end = int(round(now + rem_s))

    if _PREGAME_TIMER_CACHE["match_id"] != match_id or _PREGAME_TIMER_CACHE["end_ts"] is None:
        _PREGAME_TIMER_CACHE["match_id"] = match_id
        _PREGAME_TIMER_CACHE["last_rem_ns"] = rem_ns
        _PREGAME_TIMER_CACHE["end_ts"] = candidate_end
    elif rem_ns != _PREGAME_TIMER_CACHE["last_rem_ns"]:
        _PREGAME_TIMER_CACHE["last_rem_ns"] = rem_ns
        if abs(candidate_end - _PREGAME_TIMER_CACHE["end_ts"]) >= 2:
            _PREGAME_TIMER_CACHE["end_ts"] = candidate_end

    end_ts = _PREGAME_TIMER_CACHE["end_ts"]
    return end_ts if end_ts and end_ts > int(now) else None

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data:
        return
    party_state, party_size = Utilities.build_party_state(data)

    try:
        pregame = client.pregame_fetch_player()
        if not pregame or "MatchID" not in pregame:
            setattr(client, "_match_hint_until", time.monotonic() + 5.0)
            if hasattr(rpc, "notify_state_transition"):
                rpc.notify_state_transition(16.0)
            try:
                cg = client.coregame_fetch_player()
                if isinstance(cg, dict) and cg.get("MatchID"):
                    ingame.presence(rpc, client=client, data=data, content_data=content_data, config=config)
                    return
            except Exception:
                pass
            menu.presence(rpc, client=client, data=data, content_data=content_data, config=config)
            return
        match_id = pregame["MatchID"]
        pregame_data = client.pregame_fetch_match(match_id)
        if not pregame_data:
            return
        puuid = client.puuid

        pregame_player_data = {}
        ally_team = pregame_data.get("AllyTeam") or {}
        for player in ally_team.get("Players", []):
            if player.get("Subject") == puuid:
                pregame_player_data = player
                break

        pregame_end_time = _resolve_pregame_end_time(match_id, pregame_data)

        char_id = pregame_player_data.get("CharacterID", "")
        sel_state_raw = pregame_player_data.get("CharacterSelectionState", "")
        select_state = (
            Localizer.get_localized_text("presences", "pregame", "locked")
            if sel_state_raw == "locked"
            else Localizer.get_localized_text("presences", "pregame", "selecting")
        )
        if char_id:
            agent_image, agent_name = Utilities.fetch_agent_data(char_id, content_data, player_data=pregame_player_data)
            large_text = f"{select_state} - {agent_name}"
        else:
            agent_image = "game_icon"
            large_text = select_state

        small_image, mode_name = Utilities.fetch_mode_data(data, content_data)
        party_id = data.get("partyId") or (data.get("partyPresenceData") or {}).get("partyId") or None

        rpc.update(
            state=party_state,
            details=f"{Localizer.get_localized_text('presences','client_states','pregame')} - {mode_name}",
            end=pregame_end_time,
            large_image=agent_image,
            large_text=large_text,
            small_image=small_image,
            small_text=mode_name,
            party_size=party_size,
            party_id=party_id,
        )
    except PhaseError:
        setattr(client, "_match_hint_until", time.monotonic() + 5.0)
        if hasattr(rpc, "notify_state_transition"):
            rpc.notify_state_transition(16.0)
        try:
            cg = client.coregame_fetch_player()
            if isinstance(cg, dict) and cg.get("MatchID"):
                ingame.presence(rpc, client=client, data=data, content_data=content_data, config=config)
                return
        except Exception:
            pass
        menu.presence(rpc, client=client, data=data, content_data=content_data, config=config)
