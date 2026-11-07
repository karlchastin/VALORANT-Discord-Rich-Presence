import requests
import time
from .ingame_presences.session import Game_Session
from .ingame_presences.range import Range_Session
from . import menu
from valclient.exceptions import PhaseError
from ...utilities.processes import Processes

def presence(rpc, client=None, data=None, content_data=None, config=None):

    try:
        coregame = client.coregame_fetch_player()
        if not coregame or not coregame.get("MatchID"):
            setattr(client, "_match_hint_until", time.monotonic() + 5.0)
            setattr(client, "_cached_detected_loop", "MENUS")
            if hasattr(rpc, "notify_state_transition"):
                rpc.notify_state_transition(18.0)
            if data is not None:
                menu.presence(rpc, client=client, data=data, content_data=content_data, config=config)
            return

        match_id = coregame["MatchID"]
        provisioning = data.get("provisioningFlow", "") if data else ""

        if provisioning != "ShootingRange":
            session = Game_Session(rpc, client, data, match_id, content_data, config)
            session.main_loop()
        else:
            session = Range_Session(rpc, client, data, match_id, content_data, config)
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
        setattr(client, "_match_hint_until", time.monotonic() + 5.0)
        setattr(client, "_cached_detected_loop", "MENUS")
        if hasattr(rpc, "notify_state_transition"):
            rpc.notify_state_transition(18.0)
        if data is not None and Processes.are_processes_running():
            try:
                menu.presence(rpc, client=client, data=data, content_data=content_data, config=config)
            except Exception:
                pass
    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        if Processes.are_processes_running():
            import traceback
            print(f"[ERROR] ingame.presence failed: {e}")
            traceback.print_exc()
