import time
import requests

from ..menu_presences.away import presence as away
from ...presence_utilities import Utilities
from ....localization.localization import Localizer
from ....utilities.processes import Processes

class Range_Session:

    def __init__(self, rpc, client, data, match_id, content_data, config):
        self.rpc = rpc
        self.client = client
        self.config = config
        self.content_data = content_data
        self.match_id = match_id
        self.puuid = self.client.puuid

        data["MapID"] = "/Game/Maps/Poveglia/Range"
        self.start_time = time.time()
        self.map_name, self.mode_name = Utilities.fetch_map_data(data, content_data)
        self.map_image = "splash_range"
        lp = Localizer.get_config_value("presences", "modes", "all", "large_image")
        self.large_pref = lp[0] if isinstance(lp, (list, tuple)) and lp else (lp or "map")
        sp = Localizer.get_config_value("presences", "modes", "all", "small_image")
        self.small_pref = sp[0] if isinstance(sp, (list, tuple)) and sp else (sp or "agent")
        (
            self.large_image,
            self.large_text,
            self.small_image,
            self.small_text,
        ) = self._resolve_display(data)

    def _resolve_display(self, presence):

        show_rank = Localizer.get_config_value("presences", "modes", "range", "show_rank_in_range")
        if show_rank:
            small_image, small_text = Utilities.fetch_rank_data(self.client, self.content_data)
            return self.map_image, self.map_name or "The Range", small_image, small_text

        char_id = Utilities.detect_range_agent_from_log(self.content_data)
        if not char_id and presence:
            pp = presence.get("partyPresenceData") or {}
            mp = presence.get("matchPresenceData") or {}
            pl = presence.get("playerPresenceData") or {}
            pr = presence.get("premierPresenceData") or {}
            char_id = (
                presence.get("CharacterID") or presence.get("characterId")
                or pp.get("CharacterID") or pp.get("characterId")
                or mp.get("CharacterID") or mp.get("characterId")
                or pl.get("CharacterID") or pl.get("characterId")
                or pr.get("CharacterID") or pr.get("characterId")
            )

        if not char_id:
            try:
                cg = self.client.coregame_fetch_match(self.match_id) or {}
                for p in cg.get("Players", []):
                    if p.get("Subject") == self.puuid:
                        char_id = p.get("CharacterID")
                        break
            except Exception:
                pass

        if not char_id:
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
                        char_id = item.get("CharacterID") if isinstance(item, dict) else getattr(item, "CharacterID", None)
                        if char_id:
                            break
            except Exception:
                pass

        player_data = {"CharacterID": char_id, "Subject": self.puuid} if char_id else {}
        coregame_data = {"MapID": "/Game/Maps/Poveglia/Range"}
        large_image, large_text = Utilities.get_content_preferences(
            self.client, self.large_pref, presence, player_data, coregame_data, self.content_data
        )
        small_image, small_text = Utilities.get_content_preferences(
            self.client, self.small_pref, presence, player_data, coregame_data, self.content_data
        )
        if not large_image or large_image == "game_icon":
            large_image = self.map_image
            large_text = self.map_name or "The Range"
        return large_image, large_text, small_image, small_text

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

            if not Utilities.is_range(presence):
                try:
                    cg_player = self.client.coregame_fetch_player()
                    if not cg_player or cg_player.get("MatchID") != self.match_id:
                        break
                except Exception:
                    break

            try:
                is_afk = presence.get("isIdle", False)
                if is_afk:
                    away(self.rpc, self.client, presence, self.content_data, self.config)
                else:
                    large_image, large_text, small_image, small_text = self._resolve_display(presence)
                    if large_image:
                        self.large_image, self.large_text = large_image, large_text
                    if small_image:
                        self.small_image, self.small_text = small_image, small_text

                    party_state, party_size = Utilities.build_party_state(presence)
                    small_text_final = self.small_text if self.small_text and len(self.small_text) >= 2 else None
                    small_image_final = self.small_image if small_text_final else None
                    party_id = presence.get("partyId") or (presence.get("partyPresenceData") or {}).get("partyId") or None

                    self.rpc.update(
                        state=party_state,
                        details=self.mode_name or "The Range",
                        start=self.start_time,
                        large_image=self.large_image,
                        large_text=self.large_text,
                        small_image=small_image_final,
                        small_text=small_text_final,
                        party_size=party_size,
                        party_id=party_id,
                    )

                time.sleep(Localizer.get_config_value("presence_refresh_interval"))
            except requests.exceptions.ConnectionError:
                break
            except Exception:
                return
