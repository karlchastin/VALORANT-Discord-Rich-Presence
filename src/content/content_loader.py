from concurrent.futures import ThreadPoolExecutor
import gc
import requests

from ..localization.localization import Localizer

_STATIC_API_CACHE: dict[tuple[str, str], dict] = {}
_STATIC_ENDPOINTS = ("/agents", "/maps", "/gamemodes", "/competitivetiers")

class Loader:

    @staticmethod
    def _compact_endpoint_data(endpoint: str, raw_items: list) -> list:

        if not isinstance(raw_items, list):
            return []
        if endpoint == "/agents":
            return [
                {
                    "uuid": a.get("uuid", ""),
                    "developerName": a.get("developerName", ""),
                    "displayName": a.get("displayName", ""),
                }
                for a in raw_items
                if isinstance(a, dict)
            ]
        if endpoint == "/maps":
            return [
                {
                    "uuid": m.get("uuid", ""),
                    "displayName": m.get("displayName", ""),
                    "mapUrl": m.get("mapUrl", ""),
                }
                for m in raw_items
                if isinstance(m, dict)
            ]
        if endpoint == "/gamemodes":
            return [
                {
                    "uuid": g.get("uuid", ""),
                    "displayName": g.get("displayName", ""),
                }
                for g in raw_items
                if isinstance(g, dict)
            ]
        if endpoint == "/competitivetiers":
            if not raw_items or not isinstance(raw_items[-1], dict):
                return []
            tiers = raw_items[-1].get("tiers") or []
            return [
                {
                    "tiers": [
                        {
                            "tier": t.get("tier", 0),
                            "tierName": t.get("tierName", ""),
                        }
                        for t in tiers
                        if isinstance(t, dict)
                    ]
                }
            ]
        return raw_items

    @staticmethod
    def fetch(endpoint: str = "/", language: str = "en-US") -> dict:
        cache_key = (endpoint, language)
        cached = _STATIC_API_CACHE.get(cache_key)
        if cached:
            return cached
        try:
            url = f"https://valorant-api.com/v1{endpoint}?language={language}"
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("data"):
                compacted = {"data": Loader._compact_endpoint_data(endpoint, data["data"])}
                _STATIC_API_CACHE[cache_key] = compacted
                return compacted
            return {}
        except (requests.RequestException, ValueError, KeyError):
            return {}

    @staticmethod
    def preload_static_content(language: str = "en-US") -> None:
        if all((ep, language) in _STATIC_API_CACHE for ep in _STATIC_ENDPOINTS):
            return
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(Loader.fetch, ep, language) for ep in _STATIC_ENDPOINTS]
            for fut in futures:
                try:
                    fut.result(timeout=10)
                except Exception:
                    pass
        gc.collect()

    @staticmethod
    def load_all_content(client, fast_only: bool = False) -> dict:
        content_data = {
            "agents": [],
            "maps": [],
            "modes": [],
            "comp_tiers": [],
            "season": {},
            "queue_aliases": {
                "newmap": "New Map",
                "competitive": "Competitive",
                "unrated": "Unrated",
                "spikerush": "Spike Rush",
                "deathmatch": "Deathmatch",
                "ggteam": "Escalation",
                "onefa": "Replication",
                "custom": "Custom",
                "snowball": "Snowball Fight",
                "swiftplay": "Swiftplay",
                "hurm": "Team Deathmatch",
                "teamdeathmatch": "Team Deathmatch",
                "tdm": "Team Deathmatch",
                "skirmish": "Skirmish",
                "skirmish2v2": "Skirmish: 2v2",
                "2v2": "Skirmish: 2v2",
                "2v2skirmish": "Skirmish: 2v2",
                "skirmishascension": "Skirmish: Ascension",
                "skirmishascension1v1": "Skirmish: Ascension 1v1",
                "skirmishascension2v2": "Skirmish: Ascension 2v2",
                "onesite": "All Random One Site",
                "valaram": "All Random One Site",
                "aros": "All Random One Site",
                "allrandomonesite": "All Random One Site",
                "dodgeball": "Knockout",
                "knockout": "Knockout",
                "fortcollins": "Retake",
                "retake": "Retake",
                "abilitydraftarena": "Gauntlet: Glitched",
                "gauntlet": "Gauntlet: Glitched",
                "draftarena": "Gauntlet: Glitched",
                "premier": "Premier",
                "botmatch": "Bot Match",
                "basictraining": "Basic Training",
                "": "Custom",
            },
            "team_aliases": {
                "TeamOne": "Defender",
                "TeamTwo": "Attacker",
                "TeamSpectate": "Observer",
                "teamspectate": "Observer",
                "Observer": "Observer",
                "observer": "Observer",
                "TeamOneCoaches": "Defender Coach",
                "TeamTwoCoaches": "Attacker Coach",
            },
            "team_image_aliases": {
                "TeamOne": "team_defender",
                "TeamTwo": "team_attacker",
                "Red": "team_defender",
                "Blue": "team_attacker",
                "TeamSpectate": "team_observer",
                "teamspectate": "team_observer",
                "Observer": "team_observer",
                "observer": "team_observer",
                "Spectate": "team_observer",
                "spectate": "team_observer",
            },
            "modes_with_icons": [
                "ggteam", "onefa", "snowball", "spikerush", "unrated", "competitive", "deathmatch",
                "swiftplay", "hurm", "tdm", "teamdeathmatch", "skirmish", "skirmish2v2", "onesite", "valaram",
                "2v2", "2v2skirmish", "aros", "allrandomonesite", "dodgeball", "knockout",
                "fortcollins", "retake", "abilitydraftarena", "gauntlet", "draftarena",
                "skirmishascension1v1", "skirmishascension2v2", "skirmishascension",
                "premier", "custom",
            ],
        }

        locale = getattr(Localizer, "locale", "en-US") or "en-US"
        fallback_locale = "en-US"
        lang_param = "en-US" if locale == fallback_locale else "all"
        endpoints = ("/agents", "/maps", "/gamemodes", "/competitivetiers")

        if fast_only:
            all_content = {}
            results = {ep: _STATIC_API_CACHE.get((ep, lang_param), {}) for ep in endpoints}
        else:

            pool = ThreadPoolExecutor(max_workers=5)
            try:
                riot_future = pool.submit(lambda: (client.fetch_content() or {}) if client else {})
                api_futures = {ep: pool.submit(Loader.fetch, ep, lang_param) for ep in endpoints}
                try:
                    all_content = riot_future.result(timeout=3.5)
                except Exception:
                    all_content = {}
                results = {}
                for ep in endpoints:
                    try:
                        results[ep] = api_futures[ep].result(timeout=4.0)
                    except Exception:
                        results[ep] = _STATIC_API_CACHE.get((ep, lang_param), {})
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        agents = results["/agents"].get("data") or []
        maps = results["/maps"].get("data") or []
        modes = results["/gamemodes"].get("data") or []
        ct_data = results["/competitivetiers"].get("data") or []
        comp_tiers = ct_data[-1].get("tiers", []) if ct_data else []

        for season in (all_content.get("Seasons") or []):
            if not isinstance(season, dict):
                continue
            if season.get("IsActive") and season.get("Type") == "act":
                content_data["season"] = {
                    "competitive_uuid": season.get("ID", ""),
                    "season_uuid": season.get("ID", ""),
                    "display_name": season.get("Name", ""),
                }

        def _extract_name(raw_name) -> tuple[str, str]:
            if isinstance(raw_name, dict):
                base = raw_name.get(fallback_locale, "")
                return base, raw_name.get(locale, base)
            val = str(raw_name or "")
            return val, val

        for agent in agents:
            if not isinstance(agent, dict):
                continue
            uuid = agent.get("uuid", "")
            internal_name = agent.get("developerName", "")

            if internal_name == "AbilityDraftAgent" or uuid == "773f0c78-4486-752b-68ef-4585d7f4b848":
                disp_name = "Hybrid Robo Agent"
                disp_localized = "Hybrid Robo Agent"
            else:
                disp_name, disp_localized = _extract_name(agent.get("displayName"))

            content_data["agents"].append({
                "uuid": uuid,
                "display_name": disp_name,
                "display_name_localized": disp_localized,
                "internal_name": internal_name,
            })

        for game_map in maps:
            if not isinstance(game_map, dict):
                continue
            disp_name, disp_localized = _extract_name(game_map.get("displayName"))
            map_url = game_map.get("mapUrl") or ""
            content_data["maps"].append({
                "uuid": game_map.get("uuid", ""),
                "display_name": disp_name,
                "display_name_localized": disp_localized,
                "path": map_url,
                "internal_name": map_url.split("/")[-1] if map_url else "",
            })

        for mode in modes:
            if not isinstance(mode, dict):
                continue
            disp_name, disp_localized = _extract_name(mode.get("displayName"))
            content_data["modes"].append({
                "uuid": mode.get("uuid", ""),
                "display_name": disp_name,
                "display_name_localized": disp_localized,
            })

        for tier in comp_tiers:
            if not isinstance(tier, dict):
                continue
            disp_name, disp_localized = _extract_name(tier.get("tierName"))
            content_data["comp_tiers"].append({
                "display_name": disp_name,
                "display_name_localized": disp_localized,
                "id": tier.get("tier", 0),
            })

        return content_data
