from ...presence_utilities import Utilities
from ....localization.localization import Localizer

from .away import presence as away

def presence(rpc, client=None, data=None, content_data=None, config=None):
    if not data:
        return

    is_afk = data.get("isIdle", False)
    if is_afk:
        away(rpc, client, data, content_data, config)
    else:
        party_state, party_size = Utilities.build_party_state(data)
        pp = data.get("partyPresenceData") or {}
        mp = data.get("matchPresenceData") or {}
        match_map = data.get("matchMap") or pp.get("matchMap") or pp.get("partyOwnerMatchMap") or mp.get("matchMap") or ""
        coregame_like = {"MapID": match_map} if match_map else {}
        game_map, map_name = Utilities.fetch_map_data(coregame_like, content_data)
        custom_game_team = str(data.get("customGameTeam") or pp.get("customGameTeam") or "").strip()
        team = content_data["team_image_aliases"].get(custom_game_team) or content_data["team_image_aliases"].get(custom_game_team.lower(), "game_icon_white")
        team_patched = content_data["team_aliases"].get(custom_game_team) or content_data["team_aliases"].get(custom_game_team.lower())
        team_patched = Utilities.localize_content_name(team_patched, "presences", "team_names", custom_game_team)
        buttons = Utilities.get_join_state(client, config, data)

        if not map_name:
            map_name = Localizer.get_localized_text("presences", "client_states", "custom_setup")

        party_id = data.get("partyId") or pp.get("partyId") or None

        rpc.update(
            state=party_state,
            details=Localizer.get_localized_text("presences", "client_states", "custom_setup"),
            large_image=Utilities.get_map_splash_key(game_map),
            large_text=map_name,
            small_image=team,
            small_text=team_patched if team_patched and len(team_patched) >= 2 else None,
            party_size=party_size,
            party_id=party_id,
            buttons=buttons,
        )
