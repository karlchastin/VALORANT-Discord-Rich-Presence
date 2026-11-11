import base64, glob, json, os, psutil, re, requests, subprocess, sys, threading, time, valclient, winreg
from requests.adapters import HTTPAdapter

from .utilities.killable_thread import Thread
from .utilities.config.app_config import Config
from .utilities.processes import Processes
from .utilities.rcs import Riot_Client_Services
from .utilities.systray import Systray
from .utilities.version_checker import Checker
from .utilities.logging import Logger
from .utilities.program_data import Program_Data

from .localization.localization import Localizer
from .presence.presence import Presence
from .content.content_loader import Loader

_RUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_CACHED_CLIENT_VERSION: str | None = None
_CACHED_REGION: str | None = None
_ORIG_GET_CURRENT_VERSION = getattr(valclient.Client, "_Client__get_current_version", None)
_ORIG_SESSION_REQUEST = requests.Session.request
_THREAD_LOCAL_HTTP = threading.local()

def _bounded_session_request(self, method, url, **kwargs):

    if kwargs.get("timeout") is None:
        kwargs["timeout"] = 3.0
    return _ORIG_SESSION_REQUEST(self, method, url, **kwargs)

def _pooled_api_request(method, url, **kwargs):

    sess = getattr(_THREAD_LOCAL_HTTP, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        _THREAD_LOCAL_HTTP.session = sess
    return sess.request(method=method, url=url, **kwargs)

requests.Session.request = _bounded_session_request
requests.api.request = _pooled_api_request
requests.request = _pooled_api_request
requests.get = lambda url, params=None, **kw: _pooled_api_request("get", url, params=params, **kw)
requests.post = lambda url, data=None, json=None, **kw: _pooled_api_request("post", url, data=data, json=json, **kw)
requests.put = lambda url, data=None, **kw: _pooled_api_request("put", url, data=data, **kw)
requests.delete = lambda url, **kw: _pooled_api_request("delete", url, **kw)
requests.head = lambda url, **kw: _pooled_api_request("head", url, **kw)

def _fast_get_current_version(self) -> str:

    global _CACHED_CLIENT_VERSION
    if _CACHED_CLIENT_VERSION:
        return _CACHED_CLIENT_VERSION
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        sg_log = os.path.join(local_appdata, "VALORANT", "Saved", "Logs", "ShooterGame.log")
        try:
            if os.path.exists(sg_log):
                with open(sg_log, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(32768)
                m = re.search(r"CI server version:\s*([^\r\n]+)", head)
                if m:
                    _CACHED_CLIENT_VERSION = m.group(1).strip()
                    return _CACHED_CLIENT_VERSION
        except Exception:
            pass
    if _ORIG_GET_CURRENT_VERSION is not None:
        _CACHED_CLIENT_VERSION = _ORIG_GET_CURRENT_VERSION(self)
        return _CACHED_CLIENT_VERSION
    return ""

if _ORIG_GET_CURRENT_VERSION is not None:
    valclient.Client._Client__get_current_version = _fast_get_current_version

def _poll_client_log_hints(self) -> tuple[bool, bool]:

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return False, False
    party_changed = False
    match_changed = False
    sg_log = os.path.join(local_appdata, "VALORANT", "Saved", "Logs", "ShooterGame.log")
    try:
        if os.path.isfile(sg_log):
            size = os.path.getsize(sg_log)
            last_pos = getattr(self, "_sg_hint_pos", -1)
            if last_pos < 0 or size < last_pos:
                self._sg_hint_pos = size
            elif size > last_pos:
                read_from = max(last_pos, size - 65536)
                with open(sg_log, "rb") as f:
                    f.seek(read_from)
                    chunk = f.read(size - read_from).decode("utf-8", errors="ignore")
                    self._sg_hint_pos = f.tell()
                if any(k in chunk for k in ("Party_", "ares-parties/parties/v1/")):
                    party_changed = True
                if any(
                    k in chunk
                    for k in (
                        "Pregame_",
                        "CoreGame_",
                        "ares-pregame/",
                        "ares-core-game/",
                        "TransitionToPreGame",
                        "TransitionToInGame",
                        "TransitionToMainMenu",
                        "Match Ended",
                    )
                ):
                    party_changed = True
                    match_changed = True
                    for line in chunk.splitlines():
                        if "TransitionToInGame" in line or "Current state InGame" in line:
                            setattr(self, "_game_flow_state", "INGAME")
                        elif "TransitionToPreGame" in line or "Current state PreGame" in line:
                            setattr(self, "_game_flow_state", "PREGAME")
                        elif "TransitionToMainMenu" in line or "Current state MainMenu" in line or "Match Ended" in line:
                            setattr(self, "_game_flow_state", "MENUS")
    except Exception:
        pass

    rc_log = getattr(self, "_rc_hint_path", "")
    try:
        if not rc_log or not os.path.isfile(rc_log):
            rc_dir = os.path.join(local_appdata, "Riot Games", "Riot Client", "Logs", "Riot Client Logs")
            logs = glob.glob(os.path.join(rc_dir, "*_Riot Client.log"))
            if logs:
                rc_log = max(logs, key=os.path.getmtime)
                self._rc_hint_path = rc_log
                self._rc_hint_pos = os.path.getsize(rc_log)
        elif os.path.isfile(rc_log):
            size = os.path.getsize(rc_log)
            last_pos = getattr(self, "_rc_hint_pos", -1)
            if last_pos < 0 or size < last_pos:
                self._rc_hint_pos = size
            elif size > last_pos:
                read_from = max(last_pos, size - 65536)
                with open(rc_log, "rb") as f:
                    f.seek(read_from)
                    chunk = f.read(size - read_from).decode("utf-8", errors="ignore")
                    self._rc_hint_pos = f.tell()
                if any(k in chunk for k in ("ares-parties/parties/v1/", "activitygateway/activities/v1/")):
                    party_changed = True
                if any(
                    k in chunk
                    for k in (
                        "ares-pregame/pregame/v1/",
                        "ares-core-game/core-game/v1/",
                        "ares-session/v1/sessions/",
                    )
                ):
                    party_changed = True
                    match_changed = True
    except Exception:
        pass
    return party_changed, match_changed

def _patched_fetch_presence(self, puuid: str = "") -> dict | None:

    target_puuid = puuid or getattr(self, "puuid", "")
    if not target_puuid:
        return None

    data = None
    try:
        data = self.fetch_all_friend_presences()
    except requests.exceptions.ConnectionError:
        if not Processes.are_processes_running():
            raise
        try:
            self.activate()
            data = self.fetch_all_friend_presences()
        except Exception:
            data = None
    except Exception:
        data = None

    if isinstance(data, dict):
        presences_list = data.get("presences") or []
        self_decoded = None
        for presence in presences_list:
            if not isinstance(presence, dict) or presence.get("puuid") != target_puuid:
                continue
            if presence.get("product") not in (None, "", "valorant"):
                continue
            private_b64 = presence.get("private")
            if not private_b64 or not isinstance(private_b64, str):
                continue
            try:
                decoded = json.loads(base64.b64decode(private_b64))
                if isinstance(decoded, dict) and decoded:
                    self_decoded = decoded
                    break
            except Exception:
                continue

        if self_decoded is not None:

            pp = self_decoded.get("partyPresenceData") if isinstance(self_decoded.get("partyPresenceData"), dict) else {}
            mp = self_decoded.get("matchPresenceData") if isinstance(self_decoded.get("matchPresenceData"), dict) else {}
            party_id = self_decoded.get("partyId") or pp.get("partyId") or ""
            if target_puuid == getattr(self, "puuid", ""):
                now_mono = time.monotonic()
                party_hint, match_hint = _poll_client_log_hints(self)
                if match_hint:
                    flow = getattr(self, "_game_flow_state", "")
                    dur = 60.0 if flow in ("INGAME", "PREGAME") else 15.0
                    self._match_hint_until = max(getattr(self, "_match_hint_until", 0.0), now_mono + dur)

                ags_queue = None
                try:
                    lf_path = getattr(self, "_riot_lockfile_path", None)
                    if lf_path is None:
                        lf_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
                        self._riot_lockfile_path = lf_path
                    if os.path.isfile(lf_path):
                        with open(lf_path, "r", encoding="utf-8") as lf_file:
                            parts = lf_file.read().strip().split(":")
                        if len(parts) >= 4:
                            port, pw = parts[2], parts[3]
                            auth = base64.b64encode(f"riot:{pw}".encode("utf-8")).decode("ascii")
                            sess = getattr(_THREAD_LOCAL_HTTP, "ags_session", None)
                            if sess is None:
                                sess = requests.Session()
                                _THREAD_LOCAL_HTTP.ags_session = sess
                            r_ags = sess.get(
                                f"https://127.0.0.1:{port}/activity-gateway/v1/activities",
                                headers={"Authorization": f"Basic {auth}"},
                                verify=False,
                                timeout=0.15,
                            )
                            if r_ags.status_code == 200:
                                ags_json = r_ags.json() or {}
                                for act in ((ags_json.get("activities") or {}) if isinstance(ags_json, dict) else {}).values():
                                    if isinstance(act, dict) and act.get("product") == "valorant" and act.get("isMember") and act.get("type") == "party":
                                        gm = str(act.get("gameMode") or "").strip().lower()
                                        if gm.startswith("social_mode_"):
                                            ags_queue = gm[12:]
                                        elif gm:
                                            ags_queue = gm
                                        break
                except Exception:
                    pass

                cached_ags_queue = getattr(self, "_last_detected_ags_queue", "")
                if ags_queue and ags_queue != cached_ags_queue:
                    self._last_detected_ags_queue = ags_queue
                    party_hint = True
                    self._live_party_cache = (0.0, None)

                cache_ts, live_party = getattr(self, "_live_party_cache", (0.0, None))
                if party_hint or (now_mono - cache_ts) >= 0.45 or not isinstance(live_party, dict):
                    try:
                        live_party = self.fetch_party() or {}
                    except Exception:
                        live_party = None
                    self._live_party_cache = (now_mono, live_party)
                if isinstance(live_party, dict) and live_party.get("ID"):
                    live_pid = str(live_party.get("ID") or "")
                    members = live_party.get("Members") or []
                    live_size = max(1, len(members))
                    live_access = str(
                        live_party.get("Accessibility")
                        or pp.get("partyAccessibility")
                        or self_decoded.get("partyAccessibility")
                        or "CLOSED"
                    ).upper()
                    party_id = live_pid
                    self_decoded["partyId"] = live_pid
                    self_decoded["partySize"] = live_size
                    self_decoded["partyAccessibility"] = live_access
                    pp["partyId"] = live_pid
                    pp["partySize"] = live_size
                    pp["partyAccessibility"] = live_access
                    for m in members:
                        if isinstance(m, dict) and m.get("Subject") == target_puuid and "IsOwner" in m:
                            is_owner = bool(m.get("IsOwner"))
                            self_decoded["isPartyOwner"] = is_owner
                            pp["isPartyOwner"] = is_owner
                            break

                    raw_pstate = str(live_party.get("State") or "").strip().upper()
                    prev_pstate = getattr(self, "_last_raw_party_state", "")
                    self._last_raw_party_state = raw_pstate
                    if raw_pstate == "MATCHMADE_GAME_STARTING" or (
                        prev_pstate in ("MATCHMAKING", "STARTING_MATCHMAKING")
                        and raw_pstate in ("MATCHMADE_GAME_STARTING", "DEFAULT")
                    ):
                        self._match_hint_until = max(getattr(self, "_match_hint_until", 0.0), now_mono + 5.0)

                    if raw_pstate in ("MATCHMAKING", "STARTING_MATCHMAKING", "MATCHMADE_GAME_STARTING"):
                        live_pstate = "MATCHMAKING"
                    elif raw_pstate == "LEAVING_MATCHMAKING":
                        live_pstate = "DEFAULT"
                    else:
                        live_pstate = raw_pstate

                    if live_pstate:
                        self_decoded["partyState"] = live_pstate
                        pp["partyState"] = live_pstate

                    mm_data = live_party.get("MatchmakingData") if isinstance(live_party.get("MatchmakingData"), dict) else {}
                    custom_data = live_party.get("CustomGameData") if isinstance(live_party.get("CustomGameData"), dict) else {}
                    cur_loop = str(self_decoded.get("sessionLoopState") or mp.get("sessionLoopState") or "").upper()
                    if live_pstate == "CUSTOM_GAME_SETUP":
                        live_qid = "custom"
                        live_max_size = int(custom_data.get("MaxPartySize") or self_decoded.get("maxPartySize") or 10)
                        live_map = str(((custom_data.get("Settings") or {}).get("Map")) or "")
                        if live_map and cur_loop == "MENUS":
                            self_decoded["matchMap"] = live_map
                            pp["matchMap"] = live_map
                            mp["matchMap"] = live_map
                    else:
                        live_qid = str(mm_data.get("QueueID") or "") if "QueueID" in mm_data else ""
                        if not live_qid and ags_queue:
                            live_qid = ags_queue
                        elif ags_queue and ags_queue != getattr(self, "_last_known_live_qid", "") and cur_loop == "MENUS":
                            live_qid = ags_queue
                        self._last_known_live_qid = live_qid
                        clean_qid = live_qid.lower().strip()
                        if clean_qid.startswith("console_"):
                            clean_qid = clean_qid[8:]
                        if clean_qid in ("skirmish", "skirmish2v2", "2v2", "2v2skirmish", "skirmishascension", "skirmishascension2v2"):
                            live_max_size = 2
                        elif clean_qid in ("skirmishascension1v1",):
                            live_max_size = 1
                        elif clean_qid in ("abilitydraftarena", "gauntlet", "draftarena"):

                            raw_max = self_decoded.get("maxPartySize") or pp.get("maxPartySize")
                            live_max_size = max(5, int(raw_max)) if raw_max and int(raw_max) in (1, 2, 3, 5, 10) else 5
                        else:
                            raw_max = self_decoded.get("maxPartySize") or pp.get("maxPartySize")
                            live_max_size = int(raw_max) if raw_max and int(raw_max) in (1, 2, 3, 5, 10) else 5

                    self_decoded["maxPartySize"] = live_max_size
                    pp["maxPartySize"] = live_max_size
                    if live_qid or ("QueueID" in mm_data and cur_loop == "MENUS"):
                        self_decoded["queueId"] = live_qid
                        pp["queueId"] = live_qid
                        if cur_loop == "MENUS":
                            mp["queueId"] = live_qid

                    live_qtime = str(live_party.get("QueueEntryTime") or "")
                    if live_pstate == "MATCHMAKING" and live_qtime and not live_qtime.startswith(("0001-01-01", "0001.01.01")):
                        self_decoded["queueEntryTime"] = live_qtime
                        pp["queueEntryTime"] = live_qtime
                    else:
                        self_decoded.pop("queueEntryTime", None)
                        pp.pop("queueEntryTime", None)

                    flow = getattr(self, "_game_flow_state", "")
                    if flow in ("INGAME", "PREGAME") or now_mono < getattr(self, "_match_hint_until", 0.0) or raw_pstate == "MATCHMADE_GAME_STARTING":
                        if (now_mono - getattr(self, "_last_match_probe_ts", 0.0)) >= 0.25:
                            self._last_match_probe_ts = now_mono
                            detected_loop = ""
                            try:
                                pg = self.pregame_fetch_player()
                                if isinstance(pg, dict) and pg.get("MatchID"):
                                    detected_loop = "PREGAME"
                            except Exception:
                                pass
                            if not detected_loop:
                                try:
                                    cg = self.coregame_fetch_player()
                                    if isinstance(cg, dict) and cg.get("MatchID"):
                                        detected_loop = "INGAME"
                                except Exception:
                                    pass
                            if not detected_loop and cur_loop in ("PREGAME", "INGAME"):
                                detected_loop = "MENUS"
                                setattr(self, "_game_flow_state", "MENUS")
                            self._cached_detected_loop = detected_loop
                        else:
                            detected_loop = getattr(self, "_cached_detected_loop", "")
                        if detected_loop:
                            self_decoded["sessionLoopState"] = detected_loop
                            pp["partyOwnerSessionLoopState"] = detected_loop
                            mp["sessionLoopState"] = detected_loop
                            if detected_loop == "INGAME":
                                self._match_hint_until = max(getattr(self, "_match_hint_until", 0.0), now_mono + 30.0)
                            elif detected_loop == "MENUS" and raw_pstate == "MATCHMADE_GAME_STARTING":
                                self_decoded["partyState"] = "DEFAULT"
                                pp["partyState"] = "DEFAULT"

                    self_decoded["partyPresenceData"] = pp
                    self_decoded["matchPresenceData"] = mp
            loop_state = str(self_decoded.get("sessionLoopState") or pp.get("partyOwnerSessionLoopState") or "").upper()
            if loop_state == "MENUS":

                self_decoded["matchPresenceData"] = {}
                self_decoded.pop("partyOwnerMatchScoreAllyTeam", None)
                self_decoded.pop("partyOwnerMatchScoreEnemyTeam", None)
                self_decoded.pop("partyOwnerProvisioningFlow", None)
                self_decoded.pop("provisioningFlow", None)
                if self_decoded.get("partyState") != "CUSTOM_GAME_SETUP":
                    self_decoded.pop("matchMap", None)
                    pp.pop("matchMap", None)
                    pp.pop("partyOwnerMatchMap", None)
                pp.pop("partyOwnerMatchScoreAllyTeam", None)
                pp.pop("partyOwnerMatchScoreEnemyTeam", None)
                pp.pop("partyOwnerProvisioningFlow", None)
                mp = self_decoded["matchPresenceData"]
            match_map = mp.get("matchMap") or self_decoded.get("matchMap") or ""
            if party_id and loop_state == "INGAME":
                score_type = str(mp.get("gameScoreType") or self_decoded.get("gameScoreType") or "").lower()
                qid = str(self_decoded.get("queueId") or mp.get("queueId") or pp.get("queueId") or "").lower()
                is_teamlife = score_type == "teamlife" or any(k in qid for k in ("abilitydraft", "draftarena", "gauntlet"))
                my_ally = int(self_decoded.get("partyOwnerMatchScoreAllyTeam") or pp.get("partyOwnerMatchScoreAllyTeam") or 0)
                my_enemy = int(self_decoded.get("partyOwnerMatchScoreEnemyTeam") or pp.get("partyOwnerMatchScoreEnemyTeam") or 0)
                for presence in presences_list:
                    if not isinstance(presence, dict) or presence.get("puuid") == target_puuid:
                        continue
                    if presence.get("product") not in (None, "", "valorant"):
                        continue
                    priv_b64 = presence.get("private")
                    if not priv_b64 or not isinstance(priv_b64, str):
                        continue
                    try:
                        peer = json.loads(base64.b64decode(priv_b64))
                        if not isinstance(peer, dict):
                            continue
                        peer_pp = peer.get("partyPresenceData") or {}
                        peer_mp = peer.get("matchPresenceData") or {}
                        peer_pid = peer.get("partyId") or peer_pp.get("partyId") or ""
                        peer_state = str(peer.get("sessionLoopState") or peer_mp.get("sessionLoopState") or "").upper()
                        peer_map = peer_mp.get("matchMap") or peer.get("matchMap") or ""
                        if peer_pid != party_id or peer_state != "INGAME" or (match_map and peer_map and peer_map != match_map):
                            continue
                        p_ally = int(peer.get("partyOwnerMatchScoreAllyTeam") or peer_pp.get("partyOwnerMatchScoreAllyTeam") or 0)
                        p_enemy = int(peer.get("partyOwnerMatchScoreEnemyTeam") or peer_pp.get("partyOwnerMatchScoreEnemyTeam") or 0)
                        if is_teamlife:
                            cur_hp = 100 if (my_ally == 0 and my_enemy == 0) else my_enemy
                            peer_hp = 100 if (p_ally == 0 and p_enemy == 0) else p_enemy
                            if 0 < peer_hp < cur_hp:
                                my_enemy = peer_hp
                                self_decoded["partyOwnerMatchScoreEnemyTeam"] = peer_hp
                                if isinstance(self_decoded.get("partyPresenceData"), dict):
                                    self_decoded["partyPresenceData"]["partyOwnerMatchScoreEnemyTeam"] = peer_hp
                        else:
                            if (p_ally + p_enemy) > (my_ally + my_enemy):
                                my_ally, my_enemy = p_ally, p_enemy
                                self_decoded["partyOwnerMatchScoreAllyTeam"] = p_ally
                                self_decoded["partyOwnerMatchScoreEnemyTeam"] = p_enemy
                                if isinstance(self_decoded.get("partyPresenceData"), dict):
                                    self_decoded["partyPresenceData"]["partyOwnerMatchScoreAllyTeam"] = p_ally
                                    self_decoded["partyPresenceData"]["partyOwnerMatchScoreEnemyTeam"] = p_enemy
                    except Exception:
                        continue
            return self_decoded

    if target_puuid == getattr(self, "puuid", "") and Processes.are_processes_running():
        try:
            session = self.session_fetch() or {}
            cxn_state = str(session.get("cxnState") or "").strip().upper()
            loop_state = str(session.get("loopState") or "").strip().upper()
            if cxn_state == "CONNECTED" and loop_state in ("MENUS", "PREGAME", "INGAME"):
                party = {}
                try:
                    party = self.fetch_party() or {}
                except Exception:
                    party = {}
                party_id = str(party.get("ID") or "")
                raw_state = str(party.get("State") or "DEFAULT").strip().upper()
                party_state = "MATCHMAKING" if raw_state in ("MATCHMAKING", "STARTING_MATCHMAKING") else raw_state
                mm_data = party.get("MatchmakingData") or {}
                queue_id = str(mm_data.get("QueueID") or "")
                clean_qid = queue_id.lower().strip()
                if clean_qid.startswith("console_"):
                    clean_qid = clean_qid[8:]
                custom_data = party.get("CustomGameData") or {}
                match_map = str((custom_data.get("Settings") or {}).get("Map") or "")
                accessibility = str(party.get("Accessibility") or "CLOSED").upper()
                members = party.get("Members") or []
                party_size = max(1, len(members))
                if clean_qid in ("skirmish", "skirmish2v2", "2v2", "2v2skirmish", "skirmishascension", "skirmishascension2v2"):
                    max_party_size = 2
                elif clean_qid in ("skirmishascension1v1",):
                    max_party_size = 1
                elif clean_qid in ("abilitydraftarena", "gauntlet", "draftarena"):

                    max_party_size = max(5, int(custom_data.get("MaxPartySize") or 5))
                else:
                    max_party_size = int(custom_data.get("MaxPartySize") or 5)
                account_level = 0
                comp_tier = 0
                for m in members:
                    if isinstance(m, dict) and m.get("Subject") == target_puuid:
                        account_level = int((m.get("PlayerIdentity") or {}).get("AccountLevel") or 0)
                        comp_tier = int(m.get("CompetitiveTier") or 0)
                        break
                return {
                    "isValid": True,
                    "isIdle": False,
                    "sessionLoopState": loop_state,
                    "partyId": party_id,
                    "partyState": party_state,
                    "partyAccessibility": accessibility,
                    "partySize": party_size,
                    "maxPartySize": max_party_size,
                    "queueId": queue_id,
                    "matchMap": match_map,
                    "accountLevel": account_level,
                    "competitiveTier": comp_tier,
                    "partyPresenceData": {
                        "partyId": party_id,
                        "partyState": party_state,
                        "partyAccessibility": accessibility,
                        "partySize": party_size,
                        "maxPartySize": max_party_size,
                        "queueId": queue_id,
                        "matchMap": match_map,
                        "partyOwnerSessionLoopState": loop_state,
                    },
                    "matchPresenceData": {
                        "sessionLoopState": loop_state,
                        "queueId": queue_id,
                        "matchMap": match_map,
                    } if loop_state != "MENUS" else {},
                }
        except Exception:
            pass

        try:
            lf = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
            if os.path.isfile(lf):
                with open(lf, "r", encoding="utf-8") as f:
                    parts = f.read().strip().split(":")
                if len(parts) >= 4:
                    port, pw = parts[2], parts[3]
                    auth = base64.b64encode(f"riot:{pw}".encode("utf-8")).decode("ascii")
                    resp = requests.get(
                        f"https://127.0.0.1:{port}/activity-gateway/v1/activities",
                        headers={"Authorization": f"Basic {auth}"},
                        verify=False,
                        timeout=0.5,
                    )
                    if resp.status_code == 200:
                        acts = (resp.json() or {}).get("activities") or {}
                        for act in acts.values():
                            if isinstance(act, dict) and act.get("product") == "valorant" and act.get("isMember"):
                                pid = str(act.get("id") or "")
                                raw_mode = str(act.get("gameMode") or "").lower().strip()
                                qid = raw_mode[12:] if raw_mode.startswith("social_mode_") else raw_mode
                                players = act.get("players") if isinstance(act.get("players"), dict) else {}
                                act_type = str(act.get("type") or "").lower()
                                psize = max(1, int(players.get("current") or 1)) if act_type == "party" else 1
                                max_psize = max(psize, int(players.get("max") or 5))
                                return {
                                    "isValid": True,
                                    "isIdle": False,
                                    "sessionLoopState": "MENUS",
                                    "partyId": pid,
                                    "partyState": "DEFAULT",
                                    "partyAccessibility": "CLOSED",
                                    "partySize": psize,
                                    "maxPartySize": max_psize,
                                    "queueId": qid,
                                    "matchMap": "",
                                    "partyPresenceData": {
                                        "partyId": pid,
                                        "partyState": "DEFAULT",
                                        "partyAccessibility": "CLOSED",
                                        "partySize": psize,
                                        "maxPartySize": max_psize,
                                        "queueId": qid,
                                        "partyOwnerSessionLoopState": "MENUS",
                                    },
                                    "matchPresenceData": {},
                                }
        except Exception:
            pass

    return None

valclient.Client.fetch_presence = _patched_fetch_presence

class Startup:
    def __init__(self):
        if Processes.is_program_already_running():
            return

        Processes.set_background_priority()
        Logger.create_logger()
        Program_Data.update_file_location()
        Startup._ensure_persistent_autostart()

        self.config = Config.fetch_config()
        detected_region = Startup.detect_region_fast()
        if detected_region and "region" in self.config and isinstance(self.config["region"], list):
            self.config["region"][0] = detected_region

        self.installs = Program_Data.fetch_installs()
        Localizer.set_locale(self.config)
        self.config = Config.check_config()
        Localizer.config = self.config

        Logger.debug(self.config)
        self.client = None
        self.presence = Presence(self.config)
        self.systray = Systray(self.client, self.config, presence=self.presence)
        self.presence.rpc.set_systray(self.systray)
        self.run()

    @staticmethod
    def detect_region_fast() -> str:

        global _CACHED_REGION
        if _CACHED_REGION:
            return _CACHED_REGION

        valid_regions = set(valclient.Client.fetch_regions())
        local_appdata = os.environ.get("LOCALAPPDATA", "")

        if local_appdata:
            rcs_yaml = os.path.join(local_appdata, "Riot Games", "Riot Client", "Config", "RiotClientSettings.yaml")
            try:
                if os.path.exists(rcs_yaml):
                    with open(rcs_yaml, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(16384)
                    m = re.search(r"valorant:\s+live:\s*[\"']?([a-zA-Z]+)[\"']?", content)
                    if m:
                        reg = m.group(1).strip().lower()
                        if reg in valid_regions:
                            _CACHED_REGION = reg
                            return reg
            except Exception:
                pass

            sg_log = os.path.join(local_appdata, "VALORANT", "Saved", "Logs", "ShooterGame.log")
            try:
                if os.path.exists(sg_log):
                    with open(sg_log, "r", encoding="utf-8", errors="ignore") as f:
                        head = f.read(65536)
                    m = re.search(r"https://(?:glz-[a-z0-9-]+|pd|shared)\.([a-z]+)\.a\.pvp\.net", head)
                    if m:
                        reg = m.group(1).strip().lower()
                        if reg in valid_regions:
                            _CACHED_REGION = reg
                            return reg
            except Exception:
                pass

            lockfile = os.path.join(local_appdata, "Riot Games", "Riot Client", "Config", "lockfile")
            try:
                if os.path.exists(lockfile):
                    with open(lockfile, "r", encoding="utf-8", errors="ignore") as f:
                        parts = f.read().strip().split(":")
                    if len(parts) >= 4:
                        port, pw = parts[2], parts[3]
                        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
                        resp = requests.get(
                            f"https://127.0.0.1:{port}/product-session/v1/external-sessions",
                            headers={"Authorization": f"Basic {auth}"},
                            verify=False,
                            timeout=1.0,
                        )
                        if resp.status_code == 200:
                            for _, session in (resp.json() or {}).items():
                                if session.get("productId") == "valorant":
                                    args = (session.get("launchConfiguration") or {}).get("arguments") or []
                                    for arg in args:
                                        if "-ares-deployment=" in arg:
                                            reg = arg.replace("-ares-deployment=", "").strip().lower()
                                            if reg in valid_regions:
                                                _CACHED_REGION = reg
                                                return reg
            except Exception:
                pass

        return ""

    def _resolve_region(self) -> str:
        region = Localizer.get_config_value("region", 0)
        if region:
            return region
        detected = Startup.detect_region_fast()
        if detected:
            try:
                self.config[Localizer.get_config_key("region")][0] = detected
            except Exception:
                pass
            return detected
        return ""

    @staticmethod
    def _ensure_persistent_autostart() -> None:
        if not getattr(sys, "frozen", False):
            return
        try:
            exe_path = os.path.abspath(sys.executable)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "VALORANT RPC", 0, winreg.REG_SZ, f'"{exe_path}" --startup')
        except Exception:
            pass

    def run(self):
        self.dispatch_systray()

        auto_launch = False
        try:
            auto_launch = bool(Localizer.get_config_value("startup", "auto_launch_valorant"))
        except Exception:
            pass

        if (auto_launch or "--launch-valorant" in sys.argv[1:]) and not Processes.are_processes_running():
            self.start_game()

        self.presence_thread = Thread(target=self.standby_watchdog_loop, daemon=True)
        self.presence_thread.start()

        self.systray_thread.join()
        self.presence.disconnect_rpc()
        self.presence_thread.stop()

    def _prewarm_caches(self) -> None:
        global _CACHED_CLIENT_VERSION
        try:
            if not _CACHED_CLIENT_VERSION:
                data = requests.get("https://valorant-api.com/v1/version", timeout=4).json().get("data") or {}
                if data:
                    _CACHED_CLIENT_VERSION = f"{data['branch']}-shipping-{data['buildVersion']}-{data['version'].split('.')[3]}"
        except Exception:
            pass
        Loader.preload_static_content()
        Processes.trim_working_set()

    def _try_instant_ready(self) -> bool:
        self._initial_presence = None
        region = self._resolve_region()
        if not region:
            return False
        for attempt in range(3):
            try:
                client = valclient.Client(region=region)
                client.activate()
                self.client = client
                self.presence.client = client
                self._suppress_native_discord_rpc(client)
                pres = client.fetch_presence()
                if pres is not None:
                    self._initial_presence = pres
                    return True
            except Exception:
                pass
            if attempt < 2 and Processes.are_processes_running():
                time.sleep(0.15)
        return False

    def standby_watchdog_loop(self):

        logged_standby = False
        last_standby_check_ts = time.monotonic()

        if Processes.are_processes_running():
            Thread(target=self._prewarm_caches, daemon=True).start()
            Thread(target=lambda: Checker.check_version(self.config, auto_apply=True, silent=True), daemon=True).start()
        else:
            Logger.debug("[startup] Performing initial Windows startup update check...")
            Checker.check_version(self.config, auto_apply=True, silent=True)
            Processes.trim_working_set()

        while not getattr(self, "presence_thread", None) or not self.presence_thread.stopped():
            if not Processes.are_processes_running():
                self.presence.disconnect_rpc()
                self.client = None
                self.presence.client = None
                self.systray.set_status("Standby (Waiting for VALORANT)")

                if not logged_standby:
                    logged_standby = True
                    Logger.debug("[standby] Waiting for VALORANT in background (RPC off).")
                    Processes.trim_working_set()

                now_mono = time.monotonic()
                if (now_mono - last_standby_check_ts) >= 1800.0:
                    last_standby_check_ts = now_mono
                    Thread(target=lambda: Checker.check_remote_signal(self.config), daemon=True).start()

                time.sleep(1.5)
                continue

            if logged_standby:
                logged_standby = False
                Logger.debug("[warmup] VALORANT detected; checking for updates in background...")
                Thread(target=lambda: Checker.check_version(self.config, auto_apply=True, silent=True, force=True), daemon=True).start()

            if not Processes.are_processes_running():
                self.presence.disconnect_rpc()
                continue

            Thread(target=self._prewarm_caches, daemon=True).start()

            if not self._try_instant_ready():
                Logger.debug("[warmup] VALORANT still loading; publishing Loading RPC...")
                self.systray.set_status("Loading VALORANT...")
                self.presence.update_presence("STARTUP")

                if not self.setup_client():
                    self.presence.disconnect_rpc()
                    time.sleep(1)
                    continue

                if not self.wait_for_presence():
                    self.presence.disconnect_rpc()
                    time.sleep(1)
                    continue

            self.systray.client = self.client
            self.systray.set_status("Active (VALORANT Running)")
            self.check_run_cli()
            Logger.debug("[active] VALORANT Rich Presence running.")

            self.presence.run_active_session(initial_presence=getattr(self, "_initial_presence", None))

            self.presence.disconnect_rpc()
            Processes.trim_working_set()
            Logger.debug("[standby] VALORANT session ended; RPC cleared.")

    def dispatch_systray(self):
        self.systray_thread = Thread(target=self.systray.run)
        self.systray_thread.start()

    def setup_client(self) -> bool:
        if self.client is not None and getattr(self.client, "puuid", None):
            return True
        region = self._resolve_region()
        if not region:
            return self.check_region()

        client = valclient.Client(region=region)
        retries = 0
        while retries < 60 and Processes.are_processes_running():
            try:
                client.activate()
                self.client = client
                self.presence.client = client
                self._suppress_native_discord_rpc(client)
                return True
            except Exception:
                time.sleep(0.35)
                retries += 1

        if not Processes.are_processes_running():
            return False
        return self.check_region()

    @staticmethod
    def _suppress_native_discord_rpc(client) -> None:

        Startup._suppress_external_competitor_rpc()

    @staticmethod
    def _suppress_external_competitor_rpc() -> None:

        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return
        medal_dir = os.path.join(appdata, "Medal")
        if not os.path.isdir(medal_dir):
            return
        try:
            import sqlite3
            for db_path in glob.glob(os.path.join(medal_dir, "medal-*.db")):
                if "-wal" in db_path or "-shm" in db_path:
                    continue
                try:
                    conn = sqlite3.connect(db_path, timeout=1.0)
                    c = conn.cursor()
                    c.execute("INSERT OR REPLACE INTO key_values (key, value) VALUES ('DiscordRpcEnabled', X'00');")
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
        except Exception:
            pass

    def wait_for_presence(self) -> bool:
        presence_timeout = Localizer.get_config_value("startup", "presence_timeout")
        max_ticks = int(presence_timeout * 6.5)
        presence_timer = 0
        while Processes.are_processes_running():
            try:
                pres = self.client.fetch_presence()
                if pres is not None:
                    self._initial_presence = pres
                    return True
            except Exception:
                pass
            presence_timer += 1
            if presence_timer >= max_ticks:
                return False
            time.sleep(0.15)
        return False

    def start_game(self):
        path = Riot_Client_Services.get_rcs_path()
        if not path:
            return
        launch_timeout = Localizer.get_config_value("startup", "game_launch_timeout")
        launch_timer = 0

        psutil.subprocess.Popen([path, "--launch-product=valorant", "--launch-patchline=live"])
        while not Processes.are_processes_running() and launch_timer < launch_timeout:
            launch_timer += 1
            time.sleep(1)

    def check_run_cli(self):
        if Localizer.get_config_value("startup", "auto_launch_skincli"):
            skincli_path = self.installs.get("valorant-skin-cli")
            if skincli_path is not None:
                subprocess.Popen(f"start {skincli_path}", shell=True)

    def check_region(self) -> bool:
        Logger.debug("[startup] Autodetecting VALORANT region...")
        fast_region = Startup.detect_region_fast()
        if fast_region:
            try:
                self.config[Localizer.get_config_key("region")][0] = fast_region
            except Exception:
                pass
            try:
                self.client = valclient.Client(region=fast_region)
                self.client.activate()
                self.presence.client = self.client
                self._suppress_native_discord_rpc(self.client)
                return True
            except Exception:
                pass

        client = valclient.Client(region=fast_region or "na")
        retries = 0
        while retries < 30 and Processes.are_processes_running():
            try:
                client.activate()
                break
            except Exception:
                time.sleep(0.5)
                retries += 1
        if not Processes.are_processes_running():
            return False
        try:
            sessions = client.riotclient_session_fetch_sessions() or {}
            for _, session in sessions.items():
                if session.get("productId") == "valorant":
                    launch_args = (session.get("launchConfiguration") or {}).get("arguments") or []
                    for arg in launch_args:
                        if "-ares-deployment=" in arg:
                            region = arg.replace("-ares-deployment=", "").strip()
                            self.config[Localizer.get_config_key("region")][0] = region
                            Logger.debug(f"[startup] Autodetected region: {region}")
                            self.client = valclient.Client(region=region)
                            self.client.activate()
                            self.presence.client = self.client
                            self._suppress_native_discord_rpc(self.client)
                            return True
        except Exception:
            pass
        self.client = client
        self.presence.client = client
        return True
