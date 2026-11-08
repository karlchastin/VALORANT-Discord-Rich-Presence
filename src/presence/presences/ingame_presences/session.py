import os
import threading
import time

from ...presence_utilities import Utilities
from ..menu_presences.away import presence as away
from ....localization.localization import Localizer
from ....utilities.logging import Logger
from ....utilities.processes import Processes
from valclient.exceptions import PhaseError
import requests
debug = Logger.debug

class Game_Session:

    def __init__(self,rpc,client,data,match_id,content_data,config):
        self.rpc = rpc
        self.client = client
        self.config = config
        self.content_data = content_data
        self.match_id = match_id
        self.puuid = self.client.puuid

        self.start_time = time.time()
        self.large_text = ""
        self.large_image = ""
        self.small_text = ""
        self.small_image = ""
        self.mode_name = ""

        lp = Localizer.get_config_value("presences", "modes", "all", "large_image")
        self.large_pref = lp[0] if isinstance(lp, (list, tuple)) and lp else (lp or "map")
        sp = Localizer.get_config_value("presences", "modes", "all", "small_image")
        self.small_pref = sp[0] if isinstance(sp, (list, tuple)) and sp else (sp or "agent")
        self.initial_queue_id = (
            (data.get("queueId") if data else None)
            or ((data.get("matchPresenceData") or {}).get("queueId") if data else None)
            or ""
        ).lower().strip()
        self._logged_presence_keys = False
        self._last_logged_cid = None
        self._best_my_score = 0
        self._best_other_score = 0
        self._best_team_hp = 100
        self._last_party_id = ""
        self._cached_coregame_data = None
        self._last_cg_poll_ts = 0.0
        self.build_static_states()

    def _resolve_display(self, presence, coregame_data):
        coregame_player_data = {}
        for player in coregame_data.get("Players", []):
            if player.get("Subject") == self.puuid:
                coregame_player_data = dict(player)
                break

        queue_id = (
            presence.get("queueId")
            or (presence.get("matchPresenceData") or {}).get("queueId")
            or (presence.get("partyPresenceData") or {}).get("queueId")
            or ""
        )
        clean_qid = queue_id.lower().strip()
        if clean_qid.startswith("console_"):
            clean_qid = clean_qid[8:]

        if clean_qid == "ggteam" or not coregame_player_data.get("CharacterID"):
            try:
                loadouts_data = self.client.coregame_fetch_match_loadouts(self.match_id) or {}
                loadouts_list = loadouts_data.get("Loadouts", [])
                if isinstance(loadouts_list, dict):
                    loadouts_list = list(loadouts_list.values())
                elif not isinstance(loadouts_list, list):
                    loadouts_list = []
                for item in loadouts_list:
                    loadout = item.get("Loadout", {}) if isinstance(item, dict) else {}
                    subject = loadout.get("Subject") if isinstance(loadout, dict) else getattr(getattr(item, "Loadout", None), "Subject", None)
                    if subject == self.puuid:
                        cid = item.get("CharacterID") if isinstance(item, dict) else getattr(item, "CharacterID", None)
                        if cid:
                            if coregame_player_data:
                                coregame_player_data["CharacterID"] = cid
                            else:
                                coregame_player_data = {"CharacterID": cid, "Subject": self.puuid}
                        break
            except Exception:
                pass

        if Utilities.is_basic_training(presence, coregame_data) or Utilities.is_range(presence, coregame_data):
            log_agent = Utilities.detect_range_agent_from_log(self.content_data)
            if log_agent:
                if coregame_player_data:
                    coregame_player_data["CharacterID"] = log_agent
                else:
                    coregame_player_data = {"CharacterID": log_agent, "Subject": self.puuid}

        large_image, large_text = Utilities.get_content_preferences(
            self.client, self.large_pref, presence, coregame_player_data, coregame_data, self.content_data
        )
        small_image, small_text = Utilities.get_content_preferences(
            self.client, self.small_pref, presence, coregame_player_data, coregame_data, self.content_data
        )
        mode_image, mode_name = Utilities.fetch_mode_data(presence, self.content_data)

        if clean_qid in ("valaram", "onesite", "aros", "allrandomonesite"):
            if self.large_pref == "agent":
                large_image, large_text = mode_image, mode_name
            if self.small_pref == "agent":
                small_image, small_text = mode_image, mode_name

        return large_image, large_text, small_image, small_text, mode_name

    def build_static_states(self):
        presence = self.client.fetch_presence() or {}
        try:
            coregame_data = self.client.coregame_fetch_match(self.match_id)
        except PhaseError:
            raise
        if coregame_data:
            self._cached_coregame_data = coregame_data
            self._last_cg_poll_ts = time.monotonic()
            (
                self.large_image,
                self.large_text,
                self.small_image,
                self.small_text,
                self.mode_name,
            ) = self._resolve_display(presence, coregame_data)

    def main_loop(self):

        missing_ticks = 0
        while Processes.are_processes_running():
            try:
                presence = self.client.fetch_presence()
            except requests.exceptions.ConnectionError:
                if not Processes.are_processes_running():
                    break
                try:
                    self.client.activate()
                except Exception:
                    pass
                presence = None
            except Exception:
                presence = None

            if presence is None:
                missing_ticks += 1
                if not Processes.are_processes_running() or missing_ticks >= 40:
                    break
                time.sleep(0.3)
                continue
            missing_ticks = 0

            pp = presence.get("partyPresenceData") or {}
            mp = presence.get("matchPresenceData") or {}
            session_state = str(
                presence.get("sessionLoopState")
                or mp.get("sessionLoopState")
                or ""
            ).strip().upper()

            if session_state and session_state != "INGAME":
                debug(f"[session] sessionLoopState={session_state!r}; exiting Game_Session for match {self.match_id}")
                break

            curr_queue = str(presence.get("queueId") or "").strip().lower()
            prov = str(presence.get("provisioningFlow") or mp.get("provisioningFlow") or "").strip().lower()
            match_map = mp.get("matchMap") or presence.get("matchMap") or ""
            if prov == "invalid" or (self.initial_queue_id and curr_queue and curr_queue != self.initial_queue_id and not match_map):
                debug(f"[session] Player returned to lobby (queue={curr_queue!r}, prov={prov!r}); exiting Game_Session.")
                break

            now_mono = time.monotonic()
            hint_active = now_mono < getattr(self.client, "_match_hint_until", 0.0)
            dynamic_mode = (
                any(k in curr_queue for k in ("ggteam", "abilitydraft", "draftarena", "gauntlet"))
                or Utilities.is_basic_training(presence, self._cached_coregame_data)
            )
            if hint_active or self._cached_coregame_data is None or (now_mono - self._last_cg_poll_ts) >= 0.6:
                self._last_cg_poll_ts = now_mono
                try:
                    player_cg = self.client.coregame_fetch_player()
                    if not player_cg or player_cg.get("MatchID") != self.match_id:
                        debug(f"[session] Player disassociated from match {self.match_id}; exiting Game_Session.")
                        break
                except PhaseError:
                    debug(f"[session] coregame_fetch_player ended for match {self.match_id}; exiting Game_Session.")
                    break
                except requests.exceptions.ConnectionError:
                    if not Processes.are_processes_running():
                        break
                except Exception:
                    pass

                if self._cached_coregame_data is None or dynamic_mode or hint_active:
                    try:
                        cg_fresh = self.client.coregame_fetch_match(self.match_id)
                        if not cg_fresh:
                            break
                        self._cached_coregame_data = cg_fresh
                    except PhaseError:
                        break
                    except requests.exceptions.ConnectionError:
                        if not Processes.are_processes_running():
                            break
                    except Exception:
                        pass

            coregame_data = self._cached_coregame_data
            if coregame_data is not None and not any(
                p.get("Subject") == self.puuid for p in coregame_data.get("Players", [])
            ):
                debug(f"[session] Player {self.puuid} no longer in coregame Players; exiting Game_Session.")
                break

            is_afk = presence.get("isIdle", False)
            if is_afk:
                away(self.rpc, self.client, presence, self.content_data, self.config)
            else:
                if not self._logged_presence_keys:
                    self._logged_presence_keys = True
                    keys = list(presence.keys())
                    debug(f"[session] presence keys={keys}")

                if coregame_data is not None:
                    large_image, large_text, small_image, small_text, mode_name = self._resolve_display(presence, coregame_data)
                    if large_text != self.large_text or small_text != self.small_text:
                        cid = presence.get("CharacterID") or (presence.get("matchPresenceData") or {}).get("CharacterID") or ""
                        if cid != self._last_logged_cid:
                            self._last_logged_cid = cid
                            debug(f"[session] display updated -> large_text={large_text!r} small_text={small_text!r} cid={cid!r}")
                    self.large_image, self.large_text = large_image, large_text
                    self.small_image, self.small_text = small_image, small_text
                    self.mode_name = mode_name

                party_state, party_size = Utilities.build_party_state(presence)
                if Utilities.is_replay_session(presence, coregame_data):
                    details = Localizer.get_localized_text("presences", "replay", "watching") or "Watching replay"
                elif Utilities.is_basic_training(presence, coregame_data):
                    details = self.mode_name or Localizer.get_localized_text("presences", "modes", "basictraining") or "Basic Training"
                elif Utilities.is_range(presence, coregame_data):
                    details = self.mode_name or "The Range"
                else:
                    pp = presence.get("partyPresenceData") or {}
                    mp = presence.get("matchPresenceData") or {}
                    my_score = (
                        presence.get("partyOwnerMatchScoreAllyTeam")
                        if presence.get("partyOwnerMatchScoreAllyTeam") is not None
                        else pp.get("partyOwnerMatchScoreAllyTeam")
                        if pp.get("partyOwnerMatchScoreAllyTeam") is not None
                        else mp.get("partyOwnerMatchScoreAllyTeam")
                    )
                    other_score = (
                        presence.get("partyOwnerMatchScoreEnemyTeam")
                        if presence.get("partyOwnerMatchScoreEnemyTeam") is not None
                        else pp.get("partyOwnerMatchScoreEnemyTeam")
                        if pp.get("partyOwnerMatchScoreEnemyTeam") is not None
                        else mp.get("partyOwnerMatchScoreEnemyTeam")
                    )
                    if my_score is None:
                        my_score = 0
                    if other_score is None:
                        other_score = 0
                    my_score = int(my_score)
                    other_score = int(other_score)

                    cur_party_id = str(presence.get("partyId") or pp.get("partyId") or "")
                    if cur_party_id:
                        self._last_party_id = cur_party_id

                    game_score_type = str(mp.get("gameScoreType") or presence.get("gameScoreType") or "").strip().lower()
                    raw_qid = str(presence.get("queueId") or mp.get("queueId") or pp.get("queueId") or "").strip().lower()
                    clean_qid = raw_qid[8:] if raw_qid.startswith("console_") else raw_qid
                    if game_score_type == "teamlife" or clean_qid in ("abilitydraftarena", "draftarena", "gauntlet"):
                        raw_hp = 100 if (other_score == 0 and my_score == 0) else other_score
                        if 0 < raw_hp < self._best_team_hp:
                            self._best_team_hp = raw_hp
                        team_hp = self._best_team_hp if (other_score == 0 and my_score == 0 and self._best_team_hp < 100) else raw_hp
                        details = f"{self.mode_name} • {team_hp} HP"
                    else:
                        if my_score > self._best_my_score:
                            self._best_my_score = my_score
                        if other_score > self._best_other_score:
                            self._best_other_score = other_score
                        if my_score == 0 and other_score == 0 and (self._best_my_score > 0 or self._best_other_score > 0):
                            my_score, other_score = self._best_my_score, self._best_other_score
                        else:
                            my_score = max(my_score, self._best_my_score)
                            other_score = max(other_score, self._best_other_score)
                        details = f"{self.mode_name} • {my_score} - {other_score}"

                small_text_final = self.small_text if self.small_text and len(self.small_text) >= 2 else None
                small_image_final = self.small_image if small_text_final else None
                party_id = presence.get("partyId") or (presence.get("partyPresenceData") or {}).get("partyId") or None

                self.rpc.update(
                    state=party_state,
                    details=details,
                    start=self.start_time,
                    large_image=self.large_image,
                    large_text=self.large_text,
                    small_image=small_image_final,
                    small_text=small_text_final,
                    party_size=party_size,
                    party_id=party_id,
                    instance=True,
                )

            time.sleep(min(0.3, float(Localizer.get_config_value("presence_refresh_interval") or 1.0)))
