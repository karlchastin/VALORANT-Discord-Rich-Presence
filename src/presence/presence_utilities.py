import os
import re
import time
import iso8601
from ..utilities.logging import Logger
from ..localization.localization import Localizer
debug = Logger.debug

_account_level_cache = None
_rank_cache = {"key": None, "timestamp": 0.0, "value": ("rank_0", "Unranked")}
_RANK_CACHE_TTL_SECONDS = 120.0
_gauntlet_log_cache = {}
_replay_log_cache = {"ts": 0.0, "is_replay": False, "map_path": ""}
_npe_submap_cache = {"ts": 0.0, "map_path": "/Game/Maps/Poveglia/Range"}
_ABILITY_DRAFT_AGENT_UUID = "773f0c78-4486-752b-68ef-4585d7f4b848"
_GAUNTLET_TEAM_NUMBER_COLORS = {
    1: "purple",
    2: "blue",
    3: "cyan",
    4: "green",
    5: "yellow",
    6: "orange",
    7: "pink",
    8: "red",
}

_RANK_NAME_TO_ASSET = {
    "UNRANKED": "rank_0",
    "IRON 1": "rank_3",
    "IRON 2": "rank_4",
    "IRON 3": "rank_5",
    "BRONZE 1": "rank_6",
    "BRONZE 2": "rank_7",
    "BRONZE 3": "rank_8",
    "SILVER 1": "rank_9",
    "SILVER 2": "rank_10",
    "SILVER 3": "rank_11",
    "GOLD 1": "rank_12",
    "GOLD 2": "rank_13",
    "GOLD 3": "rank_14",
    "PLATINUM 1": "rank_15",
    "PLATINUM 2": "rank_16",
    "PLATINUM 3": "rank_17",
    "DIAMOND 1": "rank_18",
    "DIAMOND 2": "rank_19",
    "DIAMOND 3": "rank_20",
    "ASCENDANT 1": "rank_25",
    "ASCENDANT 2": "rank_26",
    "ASCENDANT 3": "rank_27",
    "IMMORTAL 1": "rank_21",
    "IMMORTAL 2": "rank_22",
    "IMMORTAL 3": "rank_23",
    "RADIANT": "rank_24",
}
_COMP_TIER_TO_ASSET = {
    0: "rank_0",
    3: "rank_3",
    4: "rank_4",
    5: "rank_5",
    6: "rank_6",
    7: "rank_7",
    8: "rank_8",
    9: "rank_9",
    10: "rank_10",
    11: "rank_11",
    12: "rank_12",
    13: "rank_13",
    14: "rank_14",
    15: "rank_15",
    16: "rank_16",
    17: "rank_17",
    18: "rank_18",
    19: "rank_19",
    20: "rank_20",
    21: "rank_25",
    22: "rank_26",
    23: "rank_27",
    24: "rank_21",
    25: "rank_22",
    26: "rank_23",
    27: "rank_24",
}
_COMP_TIER_TO_NAME = {
    0: "Unranked",
    3: "Iron 1",
    4: "Iron 2",
    5: "Iron 3",
    6: "Bronze 1",
    7: "Bronze 2",
    8: "Bronze 3",
    9: "Silver 1",
    10: "Silver 2",
    11: "Silver 3",
    12: "Gold 1",
    13: "Gold 2",
    14: "Gold 3",
    15: "Platinum 1",
    16: "Platinum 2",
    17: "Platinum 3",
    18: "Diamond 1",
    19: "Diamond 2",
    20: "Diamond 3",
    21: "Ascendant 1",
    22: "Ascendant 2",
    23: "Ascendant 3",
    24: "Immortal 1",
    25: "Immortal 2",
    26: "Immortal 3",
    27: "Radiant",
}
_AGENT_UUID_FALLBACK = {
    "41fb69c1-4189-7b37-f117-bcaf1e96f1bf": ("agent_astra", "Astra"),
    "5f8d3a7f-467b-97f3-062c-13acf203c006": ("agent_breach", "Breach"),
    "9f0d8ba9-4140-b941-57d3-a7ad57c6b417": ("agent_brimstone", "Brimstone"),
    "22697a3d-45bf-8dd7-4fec-84a9e28c69d7": ("agent_chamber", "Chamber"),
    "1dbf2edd-4729-0984-3115-daa5eed44993": ("agent_clove", "Clove"),
    "117ed9e3-49f3-6512-3ccf-0cada7e3823b": ("agent_cypher", "Cypher"),
    "cc8b64c8-4b25-4ff9-6e7f-37b4da43d235": ("agent_deadlock", "Deadlock"),
    "dade69b4-4f5a-8528-247b-219e5a1facd6": ("agent_fade", "Fade"),
    "e370fa57-4757-3604-3648-499e1f642d3f": ("agent_gekko", "Gekko"),
    "95b78ed7-4637-86d9-7e41-71ba8c293152": ("agent_harbor", "Harbor"),
    "ddd5a15c-4fbe-42fa-3789-11a55ca5ee04": ("agent_hush", "Hush"),
    "0e38b510-41a8-5780-5e8f-568b2a4f2d6c": ("agent_iso", "Iso"),
    "add6443a-41bd-e414-f6ad-e58d267f4e95": ("agent_jett", "Jett"),
    "601dbbe7-43ce-be57-2a40-4abd24953621": ("agent_kayo", "KAY/O"),
    "1e58de9c-4950-5125-93e9-a0aee9f98746": ("agent_killjoy", "Killjoy"),
    "7c8a4701-4de6-9355-b254-e09bc2a34b72": ("agent_miks", "Miks"),
    "bb2a4828-46eb-8cd1-e765-15848195d751": ("agent_neon", "Neon"),
    "8e253930-4c05-31dd-1b6c-968525494517": ("agent_omen", "Omen"),
    "eb93336a-449b-9c1b-0a54-a891f7921d69": ("agent_phoenix", "Phoenix"),
    "f94c3b30-42be-e959-889c-5aa313dba261": ("agent_raze", "Raze"),
    "a3bfb853-43b2-7238-a4f1-ad90e9e46bcc": ("agent_reyna", "Reyna"),
    "569fdd95-4d10-43ab-ca70-79becc718b46": ("agent_sage", "Sage"),
    "6f2a04ca-43e0-be17-7f36-b3908627744d": ("agent_skye", "Skye"),
    "320b2a48-4d9b-a075-30f1-1f93a9b638fa": ("agent_sova", "Sova"),
    "b444168c-4e35-8076-db47-ef9bf368f384": ("agent_tejo", "Tejo"),
    "92eeef5d-43b5-1d4a-8d03-b3927a09034b": ("agent_veto", "Veto"),
    "707eab51-4836-f488-046a-cda6bf494859": ("agent_viper", "Viper"),
    "efba5359-4016-a1e5-7626-b1ae76895940": ("agent_vyse", "Vyse"),
    "df1cb487-4902-002e-5c17-d28e83e78588": ("agent_waylay", "Waylay"),
    "7f94d92c-4234-0a36-9646-3a87eb8b5c89": ("agent_yoru", "Yoru"),
}

class Utilities:

    @staticmethod
    def build_party_state(data):
        if not data:
            return Localizer.get_localized_text("presences", "party_states", "solo"), None

        pp = data.get("partyPresenceData") or {}
        party_state = Localizer.get_localized_text("presences","party_states","solo")
        party_accessibility = data.get("partyAccessibility") or pp.get("partyAccessibility", "CLOSED")
        party_size_val = data.get("partySize") if data.get("partySize") is not None else pp.get("partySize", 1)

        if party_size_val > 1:
            party_state = Localizer.get_localized_text("presences","party_states","in_party")
        elif party_accessibility == "OPEN":
            party_state = Localizer.get_localized_text("presences","party_states","open")

        max_party_size = data.get("maxPartySize") if data.get("maxPartySize") is not None else pp.get("maxPartySize", 5)
        party_size = [party_size_val, max_party_size] if party_size_val > 1 or party_accessibility == "OPEN" else None
        if party_size is not None:
            if party_size[0] == 0:
                party_size[0] = 1
            if party_size[1] < 1:
                party_size[1] = 1
        return party_state, party_size

    @staticmethod
    def iso8601_to_epoch(time_str):
        if not time_str or str(time_str).startswith(("0001.01.01", "0001-01-01")):
            return None
        s = str(time_str).strip()
        try:
            if "T" in s:
                return iso8601.parse_date(s).timestamp()
            split = s.split("-")
            if len(split) < 2:
                return None
            split[0] = split[0].replace(".", "-")
            split[1] = split[1].replace(".", ":")
            iso_str = "T".join(split)
            return iso8601.parse_date(iso_str).timestamp()
        except Exception:
            return None

    @staticmethod
    def fetch_rank_data(client, content_data):

        season_uuid = (content_data.get("season") or {}).get("season_uuid", "")
        cache_key = (getattr(client, "puuid", ""), season_uuid)
        now = time.monotonic()
        if season_uuid and _rank_cache["key"] == cache_key and (now - _rank_cache["timestamp"]) < _RANK_CACHE_TTL_SECONDS:
            return _rank_cache["value"]

        try:
            mmr_resp = client.fetch_mmr() or {}
            comp_skills = (mmr_resp.get("QueueSkills") or {}).get("competitive") or {}
            seasonal_info = comp_skills.get("SeasonalInfoBySeasonID") or {}
            target_season = season_uuid or (mmr_resp.get("LatestCompetitiveUpdate") or {}).get("SeasonID", "")
            mmr = seasonal_info.get(target_season) if target_season else None
            if not mmr:
                result = ("rank_0", "Unranked")
                if season_uuid:
                    _rank_cache.update({"key": cache_key, "timestamp": now, "value": result})
                return result
        except Exception:
            return "rank_0", "Rank not found"

        comp_tier_id = int(mmr.get("CompetitiveTier") or 0)
        if comp_tier_id < 3:
            result = ("rank_0", "Unranked")
            if season_uuid:
                _rank_cache.update({"key": cache_key, "timestamp": now, "value": result})
            return result

        rank_data = None
        for tier in content_data.get("comp_tiers", []):
            if tier.get("id") == comp_tier_id:
                rank_data = tier
                break

        disp_en = str((rank_data or {}).get("display_name") or _COMP_TIER_TO_NAME.get(comp_tier_id, "")).strip().upper()
        disp_loc = (rank_data or {}).get("display_name_localized") or _COMP_TIER_TO_NAME.get(comp_tier_id, "Unranked")
        rank_image = _RANK_NAME_TO_ASSET.get(disp_en) or _COMP_TIER_TO_ASSET.get(comp_tier_id, "rank_0")

        rr = mmr.get("RankedRating", 0)
        lb = mmr.get("LeaderboardRank", 0)
        rr_label = Localizer.get_localized_text("presences", "leveling", "ranked_rating")
        rank_text = f"{disp_loc} - {rr}{rr_label}" + (f" // #{lb}" if lb else "")

        result = (rank_image, rank_text)
        if season_uuid:
            _rank_cache.update({"key": cache_key, "timestamp": now, "value": result})
        return result

    @staticmethod
    def fetch_map_data(coregame_data, content_data):
        if not coregame_data:
            return "", ""
        mp = coregame_data.get("matchPresenceData") if isinstance(coregame_data.get("matchPresenceData"), dict) else {}
        pp = coregame_data.get("partyPresenceData") if isinstance(coregame_data.get("partyPresenceData"), dict) else {}
        map_id = (
            coregame_data.get("MapID")
            or coregame_data.get("matchMap")
            or mp.get("matchMap")
            or pp.get("partyOwnerMatchMap")
            or ""
        )
        if not map_id and Utilities.is_basic_training(coregame_data):
            map_id = "/Game/Maps/NPEV2/NPEV2"
        if not map_id:
            return "", ""
        map_id_lower = str(map_id).lower().strip()
        if "npev2" in map_id_lower:
            map_id_lower = Utilities.detect_npe_submap_from_log().lower()
        for gmap in content_data.get("maps", []):
            gpath = (gmap.get("path") or "").lower()
            if gpath == map_id_lower or (gmap.get("internal_name") and gmap["internal_name"].lower() == map_id_lower.split("/")[-1]):
                return gmap["display_name"], gmap["display_name_localized"]
        if "triad" in map_id_lower:
            return "Haven", "Haven"
        if "poveglia" in map_id_lower or "range" in map_id_lower or "npev2" in map_id_lower:
            return "The Range", "The Range"
        return "", ""

    @staticmethod
    def detect_npe_submap_from_log() -> str:

        now = time.monotonic()
        if (now - _npe_submap_cache["ts"]) < 1.0:
            return _npe_submap_cache["map_path"]

        log_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VALORANT", "Saved", "Logs", "ShooterGame.log")
        if not os.path.isfile(log_path):
            _npe_submap_cache.update({"ts": now, "map_path": "/Game/Maps/Poveglia/Range"})
            return "/Game/Maps/Poveglia/Range"

        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 524288), os.SEEK_SET)
                tail = f.read().decode("utf-8", errors="ignore")
        except Exception:
            return _npe_submap_cache["map_path"]

        start_idx = tail.rfind("Map Name: NPEV2 | Changed: TRUE")
        if start_idx >= 0:
            tail = tail[start_idx:]

        last_m1_active = tail.rfind("'/Game/Maps/NPEV2/Modules/NPE_Module_1_PC")
        last_haven = max(
            tail.rfind("No world was found for object (/Game/Maps/NPEV2/Modules/NPE_Module_1_PC"),
            tail.rfind("SAV_CMain3"),
            tail.rfind("/Game/Maps/NPEV2/Modules/Module2_"),
            tail.rfind("WBP_Screen_PreRoundShopContainer_C"),
            tail.rfind("BombInteractionBuff_C"),
        )
        if last_haven > last_m1_active:
            resolved = "/Game/Maps/Triad/Triad"
        elif last_m1_active >= 0 or start_idx >= 0:
            resolved = "/Game/Maps/Poveglia/Range"
        else:
            resolved = _npe_submap_cache["map_path"]

        _npe_submap_cache.update({"ts": now, "map_path": resolved})
        return resolved

    @staticmethod
    def is_basic_training(presence: dict | None, coregame_data: dict | None = None) -> bool:

        p = presence or {}
        pp = p.get("partyPresenceData") if isinstance(p.get("partyPresenceData"), dict) else {}
        loop_state = str(
            p.get("sessionLoopState")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        ).strip().upper()
        if loop_state == "MENUS":
            return False
        mp = p.get("matchPresenceData") if isinstance(p.get("matchPresenceData"), dict) else {}
        cg = coregame_data or {}
        prov = str(
            p.get("provisioningFlow")
            or mp.get("provisioningFlow")
            or pp.get("partyOwnerProvisioningFlow")
            or ""
        ).strip().lower()
        map_id = str(
            cg.get("MapID")
            or p.get("matchMap")
            or mp.get("matchMap")
            or pp.get("partyOwnerMatchMap")
            or ""
        ).strip().lower()
        mode_id = str(cg.get("ModeID") or "").strip().lower()
        qid = str(p.get("queueId") or mp.get("queueId") or pp.get("queueId") or "").strip().lower()
        return (
            prov in ("newplayerexperience", "replaynewplayerexperience")
            or "npev2" in map_id
            or "npev2" in mode_id
            or qid == "basictraining"
        )

    @staticmethod
    def is_range(presence: dict | None = None, coregame_data: dict | None = None) -> bool:

        p = presence or {}
        pp = p.get("partyPresenceData") if isinstance(p.get("partyPresenceData"), dict) else {}
        loop_state = str(
            p.get("sessionLoopState")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        ).strip().upper()
        if loop_state == "MENUS":
            return False
        if Utilities.is_basic_training(presence, coregame_data):
            return False
        mp = p.get("matchPresenceData") if isinstance(p.get("matchPresenceData"), dict) else {}
        cg = coregame_data or {}
        cg_mp = cg.get("matchPresenceData") if isinstance(cg.get("matchPresenceData"), dict) else {}
        cg_pp = cg.get("partyPresenceData") if isinstance(cg.get("partyPresenceData"), dict) else {}
        prov = str(
            cg.get("ProvisioningFlow")
            or cg.get("provisioningFlow")
            or p.get("provisioningFlow")
            or mp.get("provisioningFlow")
            or pp.get("partyOwnerProvisioningFlow")
            or cg_mp.get("provisioningFlow")
            or cg_pp.get("partyOwnerProvisioningFlow")
            or ""
        ).strip().lower()
        map_id = str(
            cg.get("MapID")
            or cg.get("matchMap")
            or p.get("matchMap")
            or mp.get("matchMap")
            or pp.get("partyOwnerMatchMap")
            or cg_mp.get("matchMap")
            or cg_pp.get("partyOwnerMatchMap")
            or ""
        ).strip().lower()
        mode_id = str(cg.get("ModeID") or "").strip().lower()
        qid = str(p.get("queueId") or mp.get("queueId") or pp.get("queueId") or "").strip().lower()
        return (
            prov == "shootingrange"
            or "shootingrange" in mode_id
            or "poveglia" in map_id
            or ("range" in map_id and "npev2" not in map_id)
            or qid == "range"
        )

    @staticmethod
    def detect_replay_from_log() -> tuple[bool, str]:

        now = time.monotonic()
        if (now - _replay_log_cache["ts"]) < 1.5:
            return _replay_log_cache["is_replay"], _replay_log_cache["map_path"]

        log_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VALORANT", "Saved", "Logs", "ShooterGame.log")
        if not os.path.isfile(log_path):
            _replay_log_cache.update({"ts": now, "is_replay": False, "map_path": ""})
            return False, ""

        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 262144), os.SEEK_SET)
                tail = f.read().decode("utf-8", errors="ignore")
        except Exception:
            _replay_log_cache.update({"ts": now, "is_replay": False, "map_path": ""})
            return False, ""

        last_menu_pos = max(
            tail.rfind("/Game/Maps/Menu/MainMenuV2"),
            tail.rfind("TransitionToMainMenu"),
            tail.rfind("LogDemo: StopDemo"),
        )
        last_demo_pos = max(
            tail.rfind("LogDemo: Playback"),
            tail.rfind("DemoNetDriver: Playback"),
        )
        if last_demo_pos > last_menu_pos and last_demo_pos >= 0:
            active_chunk = tail[max(0, last_demo_pos - 4096):]
            if "NPEV2" not in active_chunk:
                m_map = re.findall(r"(/Game/Maps/[A-Za-z0-9_]+/[A-Za-z0-9_]+)", active_chunk)
                map_path = ""
                for cand in reversed(m_map):
                    if "MainMenu" not in cand and "NPEV2" not in cand:
                        map_path = cand
                        break
                _replay_log_cache.update({"ts": now, "is_replay": True, "map_path": map_path})
                return True, map_path

        _replay_log_cache.update({"ts": now, "is_replay": False, "map_path": ""})
        return False, ""

    @staticmethod
    def detect_range_agent_from_log(content_data: dict) -> str | None:

        log_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VALORANT", "Saved", "Logs", "ShooterGame.log")
        if not os.path.isfile(log_path):
            return None
        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 131072), os.SEEK_SET)
                tail = f.read().decode("utf-8", errors="ignore")
        except Exception:
            return None

        matches = re.findall(r"AcknowledgePossession\('([A-Za-z0-9_]+)_PC_C", tail)
        if matches:
            last_internal = matches[-1].lower()
            for agent in (content_data or {}).get("agents", []):
                if agent.get("internal_name") and agent["internal_name"].lower() == last_internal:
                    return agent.get("uuid")
                if agent.get("display_name") and agent["display_name"].lower() == last_internal:
                    return agent.get("uuid")
        return None

    @staticmethod
    def is_replay_session(presence: dict | None, coregame_data: dict | None = None) -> bool:
        if Utilities.is_basic_training(presence, coregame_data):
            return False
        p = presence or {}
        pp = p.get("partyPresenceData") if isinstance(p.get("partyPresenceData"), dict) else {}
        loop_state = str(
            p.get("sessionLoopState")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        ).strip().upper()
        if loop_state in ("MENUS", "PREGAME", "STARTUP"):
            return False
        cg = coregame_data or {}
        cg_prov = str(cg.get("ProvisioningFlow") or "").strip().lower()
        if cg_prov in ("matchmaking", "customgame"):
            return False
        mp = p.get("matchPresenceData") if isinstance(p.get("matchPresenceData"), dict) else {}
        prov = str(
            p.get("provisioningFlow")
            or mp.get("provisioningFlow")
            or pp.get("partyOwnerProvisioningFlow")
            or ""
        ).strip().lower()
        pstate = str(p.get("partyState") or pp.get("partyState") or "").strip().upper()
        qid = str(p.get("queueId") or mp.get("queueId") or pp.get("queueId") or "").strip().lower()
        if (
            ("replay" in prov and "newplayerexperience" not in prov)
            or "REPLAY" in loop_state
            or "REPLAY" in pstate
            or qid == "replay"
        ):
            return True
        is_log_replay, _ = Utilities.detect_replay_from_log()
        return is_log_replay

    @staticmethod
    def get_map_splash_key(map_display_name: str) -> str:
        if not map_display_name:
            return "game_icon"
        slug = map_display_name.strip().lower().replace(" ", "_")
        if slug == "the_range":
            slug = "range"
        return f"splash_{slug}"

    @staticmethod
    def _inspect_gauntlet_log(match_id: str, my_subject: str, teammate_subjects: list):

        if not my_subject:
            return None, None
        cache_key = (match_id or "", my_subject.lower())
        now_mono = time.monotonic()
        cached = _gauntlet_log_cache.get(cache_key)
        if cached:
            if (cached.get("color") and cached.get("role")) or (now_mono - cached.get("ts", 0.0)) < 4.0:
                return cached.get("color"), cached.get("role")

        log_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VALORANT", "Saved", "Logs", "ShooterGame.log")
        if not os.path.isfile(log_path):
            return None, None

        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 524288), os.SEEK_SET)
                tail = f.read().decode("utf-8", errors="ignore")
        except Exception:
            return None, None

        color = cached.get("color") if cached else None
        role = cached.get("role") if cached else None

        if match_id and not color:
            m_tm = re.search(rf"{re.escape(match_id)}-tm([1-8])\b", tail, re.IGNORECASE)
            if m_tm:
                color = _GAUNTLET_TEAM_NUMBER_COLORS.get(int(m_tm.group(1)))

        my_sub_lower = my_subject.lower()
        teammate_subs = {str(s).lower() for s in (teammate_subjects or []) if s and str(s).lower() != my_sub_lower}
        incognito_pattern = re.compile(
            r"Subject had empty display name\.\s*([0-9a-fA-F-]+)\s*\r?\n"
            r"[^\r\n]*?GameName=(Purple|Blue|Cyan|Green|Yellow|Orange|Pink|Red)\s+\w+\s+(O|X)\b",
            re.IGNORECASE,
        )
        for m in incognito_pattern.finditer(tail):
            sub = m.group(1).lower()
            c_val = m.group(2).lower()
            r_val = m.group(3).lower()
            if sub == my_sub_lower:
                color = c_val
                role = r_val
            elif sub in teammate_subs:
                if not color:
                    color = c_val
                if not role:
                    role = "x" if r_val == "o" else "o"

        _gauntlet_log_cache[cache_key] = {"color": color, "role": role, "ts": now_mono}
        return color, role

    @staticmethod
    def _resolve_gauntlet_teammates(player_data, coregame_data):
        if not isinstance(coregame_data, dict):
            return [], None, None
        my_subject = str((player_data or {}).get("Subject") or (player_data or {}).get("subject") or "").strip()
        players = coregame_data.get("Players") or []
        my_player = None
        if my_subject:
            for p in players:
                if str(p.get("Subject") or p.get("subject") or "").lower() == my_subject.lower():
                    my_player = p
                    break
        src = my_player or player_data or {}
        team_num = src.get("TeamNumber") if src.get("TeamNumber") is not None else src.get("teamNumber")
        team_id = str(src.get("TeamID") or src.get("teamId") or "").lower().strip()

        teammates = []
        if team_num is not None:
            teammates = [
                p for p in players
                if (p.get("TeamNumber") if p.get("TeamNumber") is not None else p.get("teamNumber")) == team_num
            ]
        if not teammates and team_id:
            candidates = [
                p for p in players
                if str(p.get("TeamID") or p.get("teamId") or "").lower().strip() == team_id
            ]
            if len(candidates) <= 2:
                teammates = candidates
        return teammates, my_subject, team_num

    @staticmethod
    def detect_duo_color(player_data, coregame_data=None):

        if not player_data and not coregame_data:
            return None

        teammates, my_subject, team_num = Utilities._resolve_gauntlet_teammates(player_data, coregame_data)
        if team_num is None and player_data:
            team_num = player_data.get("TeamNumber") if player_data.get("TeamNumber") is not None else player_data.get("teamNumber")
        if team_num is None and isinstance(coregame_data, dict):
            voice_id = str(coregame_data.get("TeamVoiceID") or coregame_data.get("TeamMUCName") or "")
            m = re.search(r"(?:-tm|-)([1-8])(?:$|@)", voice_id)
            if m:
                team_num = int(m.group(1))

        if team_num is not None:
            try:
                tn = int(team_num)
                if tn in _GAUNTLET_TEAM_NUMBER_COLORS:
                    color = _GAUNTLET_TEAM_NUMBER_COLORS[tn]
                    debug(f"[gauntlet] resolved TeamNumber={tn} -> color={color!r}")
                    return color
            except (ValueError, TypeError):
                pass

        match_id = str((coregame_data or {}).get("MatchID") or "")
        teammate_subs = [p.get("Subject") or p.get("subject") for p in teammates]
        log_color, _ = Utilities._inspect_gauntlet_log(match_id, my_subject, teammate_subs)
        if log_color:
            debug(f"[gauntlet] resolved ShooterGame.log -> color={log_color!r}")
            return log_color

        if not player_data:
            return None
        team_id = str(player_data.get("TeamID") or player_data.get("teamId") or "").lower().strip()
        if not team_id or team_id in ("red", "blue"):
            return None
        color_keywords = {
            "cyan": ["cyan", "sloth"],
            "orange": ["orange", "bear"],
            "purple": ["purple", "corgi"],
            "blue": ["blue", "penguin"],
            "red": ["red", "elephant"],
            "yellow": ["yellow", "squirrel"],
            "green": ["green", "octopi", "octopus"],
            "pink": ["pink", "rabbit", "bunny"],
        }
        for color, keywords in color_keywords.items():
            if any(k in team_id for k in keywords):
                debug(f"[gauntlet] resolved team_id={team_id!r} -> color={color!r}")
                return color
        debug(f"[gauntlet] unmapped team_id={team_id!r} team_num={team_num!r}")
        return None

    @staticmethod
    def detect_duo_role(player_data, coregame_data=None):

        if not player_data and not coregame_data:
            return None
        if player_data:
            role = player_data.get("SubTeamRole") or player_data.get("Role") or player_data.get("DuoRole")
            if role and str(role).lower() in ("x", "o"):
                return str(role).lower()

        teammates, my_subject, _ = Utilities._resolve_gauntlet_teammates(player_data, coregame_data)
        if my_subject:
            match_id = str((coregame_data or {}).get("MatchID") or "")
            teammate_subs = [p.get("Subject") or p.get("subject") for p in teammates]
            _, log_role = Utilities._inspect_gauntlet_log(match_id, my_subject, teammate_subs)
            if log_role in ("o", "x"):
                debug(f"[gauntlet] resolved ShooterGame.log -> role={log_role!r}")
                return log_role

            if len(teammates) >= 1:
                sorted_teammates = sorted(
                    teammates,
                    key=lambda p: str(p.get("Subject") or p.get("subject") or "").lower(),
                )
                my_sub_lower = my_subject.lower()
                if str(sorted_teammates[0].get("Subject") or sorted_teammates[0].get("subject") or "").lower() == my_sub_lower:
                    return "o"
                if len(sorted_teammates) >= 2 and str(sorted_teammates[1].get("Subject") or sorted_teammates[1].get("subject") or "").lower() == my_sub_lower:
                    return "x"
        return None

    @staticmethod
    def fetch_agent_data(uuid, content_data, player_data=None, coregame_data=None):
        uuid_lower = str(uuid or "").strip().lower()
        if not uuid_lower:
            return "rank_0", "?"
        if uuid_lower == _ABILITY_DRAFT_AGENT_UUID:
            color = Utilities.detect_duo_color(player_data, coregame_data)
            role = Utilities.detect_duo_role(player_data, coregame_data)
            if color and role:
                return f"agent_hybrid_robo_{color}_{role}", f"Hybrid Robo Agent ({color.capitalize()} - {role.upper()})"
            if color:
                return f"agent_hybrid_robo_{color}", f"Hybrid Robo Agent ({color.capitalize()})"
            return "agent_hybrid_robo", "Hybrid Robo Agent"

        for agent in content_data.get("agents", []):
            if str(agent.get("uuid") or "").strip().lower() == uuid_lower:
                if agent.get("internal_name") == "AbilityDraftAgent":
                    color = Utilities.detect_duo_color(player_data, coregame_data)
                    role = Utilities.detect_duo_role(player_data, coregame_data)
                    if color and role:
                        return f"agent_hybrid_robo_{color}_{role}", f"Hybrid Robo Agent ({color.capitalize()} - {role.upper()})"
                    if color:
                        return f"agent_hybrid_robo_{color}", f"Hybrid Robo Agent ({color.capitalize()})"
                    return "agent_hybrid_robo", "Hybrid Robo Agent"

                agent_slug = agent["display_name"].lower().replace("/", "").replace(" ", "_")
                agent_image = f"agent_{agent_slug}"
                agent_name = agent["display_name_localized"]
                return agent_image, agent_name

        if uuid_lower in _AGENT_UUID_FALLBACK:
            return _AGENT_UUID_FALLBACK[uuid_lower]
        return "rank_0", "?"

    @staticmethod
    def fetch_mode_data(data, content_data):
        if Utilities.is_basic_training(data):
            mode_name = Utilities.localize_content_name("Basic Training", "presences", "modes", "basictraining")
            return "mode_discovery", mode_name
        if Utilities.is_range(data):
            mode_name = Utilities.fetch_map_data({"MapID": "/Game/Maps/Poveglia/Range"}, content_data)[1] or "The Range"
            return "mode_discovery", mode_name
        if Utilities.is_replay_session(data):
            mode_name = Localizer.get_localized_text("presences", "replay", "watching") or "Watching replay"
            return "mode_replay", mode_name

        pp = (data.get("partyPresenceData") or {}) if data else {}
        mp = (data.get("matchPresenceData") or {}) if data else {}
        loop_state = str(
            (data.get("sessionLoopState") if data else "")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        ).strip().upper()
        if loop_state == "MENUS":
            queue_id = (data.get("queueId") or pp.get("queueId") or "") if data else ""
        else:
            queue_id = (data.get("queueId") or pp.get("queueId") or mp.get("queueId") or "") if data else ""
        queue_id_lower = (queue_id or "").lower().strip()
        clean_queue_id = queue_id_lower[8:] if queue_id_lower.startswith("console_") else queue_id_lower

        aliases = content_data["queue_aliases"]
        icons = content_data["modes_with_icons"]
        mode_name = aliases.get(queue_id) or aliases.get(queue_id_lower) or aliases.get(clean_queue_id)
        if mode_name is None:
            mode_name = "Custom"
            debug(f"[mode] Custom fallback -> queueId root={data.get('queueId')!r} party={pp.get('queueId')!r} match={mp.get('queueId')!r}")

        if not clean_queue_id:
            image_key = "custom"
        elif clean_queue_id in icons:
            image_key = clean_queue_id
        elif queue_id_lower in icons:
            image_key = queue_id_lower
        elif queue_id in icons:
            image_key = queue_id
        else:
            image_key = "discovery"

        asset_alias_map = {
            "competitive": "unrated",
            "valaram": "onesite",
            "aros": "onesite",
            "allrandomonesite": "onesite",
            "tdm": "hurm",
            "teamdeathmatch": "hurm",
            "skirmish2v2": "skirmish",
            "2v2": "skirmish",
            "2v2skirmish": "skirmish",
            "skirmishascension": "skirmish",
            "knockout": "dodgeball",
            "retake": "fortcollins",
            "draftarena": "abilitydraftarena",
            "gauntlet": "abilitydraftarena",
        }
        image_key = asset_alias_map.get(image_key, image_key)

        image = f"mode_{image_key}"
        mode_name = Utilities.localize_content_name(mode_name, "presences", "modes", queue_id or queue_id_lower or clean_queue_id)
        return image, mode_name

    @staticmethod
    def get_content_preferences(client,pref,presence,player_data,coregame_data,content_data):
        if isinstance(pref, (list, tuple)) and pref:
            pref = pref[0]
        pref_str = str(pref or "").strip().lower()
        if pref_str in ("rank", str(Localizer.get_localized_text("config", "rank")).lower()):
            return Utilities.fetch_rank_data(client,content_data)
        if pref_str in ("map", str(Localizer.get_localized_text("config", "map")).lower()):
            gmap = Utilities.fetch_map_data(coregame_data,content_data)
            return Utilities.get_map_splash_key(gmap[0]), gmap[1]
        if pref_str in ("agent", str(Localizer.get_localized_text("config", "agent")).lower()):
            char_id = None
            if player_data:
                char_id = player_data.get("CharacterID") or player_data.get("characterId")
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
                pp = (presence or {}).get("partyPresenceData") or {}
                mp = (presence or {}).get("matchPresenceData") or {}
                qid = str((presence or {}).get("queueId") or mp.get("queueId") or pp.get("queueId") or "").lower().strip()
                if qid.startswith("console_"):
                    qid = qid[8:]
                map_id = str((coregame_data or {}).get("MapID") or "").lower()
                if qid in ("abilitydraftarena", "draftarena", "gauntlet") or "abilitydraft" in map_id:
                    char_id = _ABILITY_DRAFT_AGENT_UUID
            if char_id:
                return Utilities.fetch_agent_data(char_id, content_data, player_data=player_data, coregame_data=coregame_data)
            return "rank_0", "?"
        return "game_icon", "VALORANT"

    @staticmethod
    def localize_content_name(default,*keys):
        localized = Localizer.get_localized_text(*keys)
        if localized is not None:
            return localized
        return default

    @staticmethod
    def get_join_state(client, config, presence=None):
        return None

    @staticmethod
    def fetch_account_level(client, data=None):

        global _account_level_cache

        if _account_level_cache is not None and _account_level_cache > 0:
            return _account_level_cache

        if data:
            level = data.get("accountLevel") or (data.get("playerPresenceData") or {}).get("accountLevel") or 0
            if level and level > 0:
                _account_level_cache = level
                return level

        try:
            if hasattr(client, 'fetch_account_xp'):
                account_xp = client.fetch_account_xp()
                if account_xp:
                    if "Progress" in account_xp and isinstance(account_xp["Progress"], dict):
                        if "Level" in account_xp["Progress"]:
                            level = account_xp["Progress"]["Level"]
                            if level and level > 0:
                                _account_level_cache = level
                                return level
                    if "Level" in account_xp:
                        level = account_xp["Level"]
                        if level and level > 0:
                            _account_level_cache = level
                            return level
                    if "accountLevel" in account_xp:
                        level = account_xp["accountLevel"]
                        if level and level > 0:
                            _account_level_cache = level
                            return level
                    for key in ["AccountLevel", "account_level", "PlayerLevel", "playerLevel"]:
                        if key in account_xp:
                            level = account_xp[key]
                            if level and level > 0:
                                _account_level_cache = level
                                return level
        except Exception as e:
            debug(f"Error fetching level via fetch_account_xp: {e}")
            pass

        try:
            player_loadout = client.fetch_player_loadout()
            if player_loadout:
                if "AccountLevel" in player_loadout:
                    level = player_loadout["AccountLevel"]
                    if level and level > 0:
                        _account_level_cache = level
                        return level
                if "accountLevel" in player_loadout:
                    level = player_loadout["accountLevel"]
                    if level and level > 0:
                        _account_level_cache = level
                        return level
                if "Identity" in player_loadout and isinstance(player_loadout["Identity"], dict):
                    if "AccountLevel" in player_loadout["Identity"]:
                        level = player_loadout["Identity"]["AccountLevel"]
                        if level and level > 0:
                            _account_level_cache = level
                            return level
        except Exception as e:
            debug(f"Error fetching level via fetch_player_loadout: {e}")
            pass

        return 0
