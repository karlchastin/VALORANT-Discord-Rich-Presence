import requests
import time
from .ingame_presences.session import Game_Session
from .ingame_presences.range import Range_Session
from .menu_presences.away import presence as away
from ..presence_utilities import Utilities
from ...localization.localization import Localizer
from . import menu
from valclient.exceptions import PhaseError
from ...utilities.processes import Processes

def _run_replay_session(rpc, client, data, content_data, config) -> None:

    start_time = time.time()
    missing_ticks = 0
    presence_data = data
    while Processes.are_processes_running():
        if presence_data is None:
            try:
                presence_data = client.fetch_presence()
            except Exception:
                presence_data = None
        if presence_data is None:
            missing_ticks += 1
            if not Processes.are_processes_running() or missing_ticks >= 40:
                break
            time.sleep(0.3)
            continue
        missing_ticks = 0

        if not Utilities.is_replay_session(presence_data):
            break

        if presence_data.get("isIdle", False):
            away(rpc, client, presence_data, content_data, config)
        else:
            pp = presence_data.get("partyPresenceData") or {}
            mp = presence_data.get("matchPresenceData") or {}
            _, log_map = Utilities.detect_replay_from_log()
            map_path = (
                presence_data.get("MapID")
                or presence_data.get("matchMap")
                or mp.get("matchMap")
                or pp.get("partyOwnerMatchMap")
                or log_map
                or ""
            )
            map_name, map_loc = Utilities.fetch_map_data({"MapID": map_path}, content_data) if map_path else ("", "")
            replay_label = Localizer.get_localized_text("presences", "replay", "watching") or "Watching replay"
            if map_name:
                large_image = Utilities.get_map_splash_key(map_name)
                large_text = map_loc or map_name
                small_image = "mode_replay"
                small_text = replay_label
            else:
                account_level = Utilities.fetch_account_level(client, presence_data)
                large_image = "game_icon"
                large_text = f"{Localizer.get_localized_text('presences', 'leveling', 'level')} {account_level}"
                small_image = "mode_replay"
                small_text = replay_label

            party_state, party_size = Utilities.build_party_state(presence_data)
            party_id = presence_data.get("partyId") or pp.get("partyId") or None
            rpc.update(
                state=party_state,
                details=replay_label,
                start=start_time,
                large_image=large_image,
                large_text=large_text,
                small_image=small_image,
                small_text=small_text,
                party_size=party_size,
                party_id=party_id,
                instance=True,
            )

        time.sleep(min(0.4, float(Localizer.get_config_value("presence_refresh_interval") or 1.0)))
        presence_data = None

def presence(rpc, client=None, data=None, content_data=None, config=None):

    try:
        coregame = client.coregame_fetch_player()
        if not coregame or not coregame.get("MatchID"):
            if Utilities.is_replay_session(data):
                _run_replay_session(rpc, client, data, content_data, config)
            setattr(client, "_match_hint_until", time.monotonic() + 5.0)
            setattr(client, "_cached_detected_loop", "MENUS")
            if hasattr(rpc, "notify_state_transition"):
                rpc.notify_state_transition(18.0)
            if data is not None and Processes.are_processes_running():
                fresh = client.fetch_presence() or data
                menu.presence(rpc, client=client, data=fresh, content_data=content_data, config=config)
            return

        match_id = coregame["MatchID"]
        coregame_match = None
        try:
            coregame_match = client.coregame_fetch_match(match_id)
        except Exception:
            pass

        if Utilities.is_range(data, coregame_match):
            session = Range_Session(rpc, client, data, match_id, content_data, config)
            session.main_loop()
        else:
            session = Game_Session(rpc, client, data, match_id, content_data, config)
            session.main_loop()

        setattr(client, "_match_hint_until", time.monotonic() + 5.0)
        setattr(client, "_cached_detected_loop", "MENUS")
        if hasattr(rpc, "notify_state_transition"):
            rpc.notify_state_transition(18.0)
        if Processes.are_processes_running():
            try:
                fresh_presence = client.fetch_presence() or data
                menu.presence(rpc, client=client, data=fresh_presence, content_data=content_data, config=config)
            except Exception:
                pass

    except PhaseError:
        if Utilities.is_replay_session(data):
            _run_replay_session(rpc, client, data, content_data, config)
        setattr(client, "_match_hint_until", time.monotonic() + 5.0)
        setattr(client, "_cached_detected_loop", "MENUS")
        if hasattr(rpc, "notify_state_transition"):
            rpc.notify_state_transition(18.0)
        if data is not None and Processes.are_processes_running():
            try:
                fresh = client.fetch_presence() or data
                menu.presence(rpc, client=client, data=fresh, content_data=content_data, config=config)
            except Exception:
                pass
    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        if Processes.are_processes_running():
            import traceback
            print(f"[ERROR] ingame.presence failed: {e}")
            traceback.print_exc()
