from pypresence import Presence as PyPresence
import asyncio, base64, collections, ctypes, glob, json, os, pypresence.baseclient, pypresence.utils, re, requests, sys, threading, time, traceback, urllib3
urllib3.disable_warnings()

from ..utilities.processes import Processes
from ..utilities.logging import Logger
from ..content.content_loader import Loader
from ..localization.localization import Localizer
from .presence_utilities import Utilities
from .presences import (ingame, menu, startup, pregame)

_RIOT_NATIVE_DISCORD_IDS = (
    "1443350165678198935",
    "1443349464290168976",
    "1443033465766281327",
    "700136079562375258",
    "390266029710049282",
)
_RE_IPC_OPEN = re.compile(r"Socket Opened:\s*(\d+)\s+(\d+)")
_RE_IPC_CLOSE = re.compile(r"Socket Close:\s*(\d+)")
_RE_IPC_MSG = re.compile(r"Socket Message:\s*(\d+)")
_ORIG_GET_IPC_PATH = pypresence.utils.get_ipc_path

def _fast_win32_get_ipc_path(pipe=None):

    if sys.platform == "win32":
        target = f"discord-ipc-{pipe}" if pipe is not None else "discord-ipc-"
        try:
            for entry in os.scandir(r"\\?\pipe"):
                if entry.name.startswith(target):
                    return entry.path
        except Exception:
            pass
    return _ORIG_GET_IPC_PATH(pipe)

pypresence.utils.get_ipc_path = _fast_win32_get_ipc_path
pypresence.baseclient.get_ipc_path = _fast_win32_get_ipc_path

class SafeRPC:

    def __init__(self, client_id: str):
        self.client_id = str(client_id)
        self._rpc: PyPresence | None = None
        self._last_payload: dict | None = None
        self._lock = threading.Lock()
        self._guard_running = False
        self._riot_sockets: set[str] = set()
        self._our_socket_id: int = -1
        self._last_opened_socket_id: int = -1
        self._last_log_pos: int = -1
        self._active_discord_log_dir: str = ""
        self._last_handoff_ts: float = 0.0
        self._pending_handoff: bool = False
        self._scheduled_handoff_at: float = 0.0
        self._session_start_ts: int = int(time.time())
        self._last_state_sig: tuple | None = None
        self._transition_boost_until: float = 0.0
        self._last_gateway_flush_ts: float = 0.0
        self._jitter_bit: int = 0
        self._riot_log_path: str = ""
        self._riot_log_pos: int = -1
        self._ipc_loop = asyncio.new_event_loop()
        self._ags_cache_ts: float = 0.0
        self._last_ags_party_id: str = ""
        self._ags_activities: dict = {}
        self._last_discord_secret: str | None = None
        self._last_ags_size: list[int] | None = None
        self._my_puuid: str = ""
        self._preempt_waves: list[float] = []
        self._flush_timestamps: collections.deque[float] = collections.deque()

    def set_my_puuid(self, puuid: str) -> None:
        if puuid:
            self._my_puuid = str(puuid).strip()

    def _schedule_waves_unlocked(self, now: float, offsets: tuple[float, ...], replace: bool = False) -> None:

        candidates = [t for t in ([] if replace else self._preempt_waves) if t > now]
        for off in offsets:
            candidates.append(now + off)
        candidates.sort()
        merged: list[float] = []
        for t in candidates:
            if not merged or (t - merged[-1]) >= 1.1:
                merged.append(t)
        self._preempt_waves = merged[:6]

    def _prune_flush_window_unlocked(self, now: float) -> None:
        while self._flush_timestamps and (now - self._flush_timestamps[0]) > 20.2:
            self._flush_timestamps.popleft()

    def _can_flush_unlocked(self, now: float, reserve: int = 0) -> bool:
        self._prune_flush_window_unlocked(now)
        return len(self._flush_timestamps) < (5 - reserve)

    def _record_flush_unlocked(self, now: float) -> None:
        self._prune_flush_window_unlocked(now)
        self._flush_timestamps.append(now)
        self._last_gateway_flush_ts = now

    def notify_state_transition(self, duration: float = 16.0) -> None:

        now = time.monotonic()
        with self._lock:
            self._pending_handoff = True
            self._scheduled_handoff_at = now + 3.2
            self._transition_boost_until = max(self._transition_boost_until, now + duration)
            self._schedule_waves_unlocked(now, (0.65, 2.00, 4.50, 8.50, 13.50), replace=False)

    @property
    def is_connected(self) -> bool:
        return self._rpc is not None

    def _max_riot_socket_id(self) -> int:
        return max((int(s) for s in self._riot_sockets), default=-1)

    def _bump_our_socket_id_estimate(self) -> None:
        max_known = max(self._our_socket_id, self._last_opened_socket_id, self._max_riot_socket_id())
        self._our_socket_id = max_known + 1 if max_known >= 0 else 1
        self._last_opened_socket_id = self._our_socket_id

    def _parse_discord_log_chunk(self, chunk: str) -> tuple[bool, bool]:
        contended = False
        needs_handoff = False
        for line in chunk.splitlines():
            if "[RPCServer:IPC]" not in line:
                continue
            m_open = _RE_IPC_OPEN.search(line)
            if m_open:
                sock_id, app_id = m_open.group(1), m_open.group(2)
                sid = int(sock_id)
                if self._last_opened_socket_id >= 0 and sid < self._last_opened_socket_id - 5:
                    self._riot_sockets.clear()
                    self._our_socket_id = -1
                    self._last_opened_socket_id = sid
                else:
                    self._last_opened_socket_id = max(self._last_opened_socket_id, sid)
                if app_id == self.client_id:
                    self._our_socket_id = sid
                else:
                    self._riot_sockets.add(sock_id)
                    contended = True
                    needs_handoff = True
                continue
            m_close = _RE_IPC_CLOSE.search(line)
            if m_close:
                closed_sock = m_close.group(1)
                self._riot_sockets.discard(closed_sock)
                if int(closed_sock) == self._our_socket_id:
                    self._our_socket_id = -1
                    needs_handoff = True
                continue
            m_msg = _RE_IPC_MSG.search(line)
            if m_msg:
                msg_sock = m_msg.group(1)
                msg_sid = int(msg_sock)
                self._last_opened_socket_id = max(self._last_opened_socket_id, msg_sid)
                if self._our_socket_id <= 0 or msg_sid != self._our_socket_id:
                    self._riot_sockets.add(msg_sock)
                    contended = True
                    needs_handoff = True

        max_riot = self._max_riot_socket_id()
        if max_riot >= 0 and (self._our_socket_id < 0 or max_riot >= self._our_socket_id):
            contended = True
            needs_handoff = True
        if needs_handoff:
            self._pending_handoff = True
        return contended, needs_handoff

    def _resolve_discord_log_dir(self, appdata: str) -> str:
        if self._active_discord_log_dir and os.path.exists(os.path.join(self._active_discord_log_dir, "renderer_js.log")):
            return self._active_discord_log_dir
        best_dir = ""
        best_mtime = -1.0
        for client_dir in ("discord", "discordptb", "discordcanary"):
            cand_dir = os.path.join(appdata, client_dir, "logs")
            cand_log = os.path.join(cand_dir, "renderer_js.log")
            try:
                if os.path.exists(cand_log):
                    mt = os.path.getmtime(cand_log)
                    if mt > best_mtime:
                        best_mtime = mt
                        best_dir = cand_dir
            except Exception:
                pass
        self._active_discord_log_dir = best_dir or os.path.join(appdata, "discord", "logs")
        return self._active_discord_log_dir

    def _check_discord_ipc_contended(self) -> tuple[bool, bool]:

        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return False, self._pending_handoff
        log_dir = self._resolve_discord_log_dir(appdata)
        log_path = os.path.join(log_dir, "renderer_js.log")
        old_log_path = os.path.join(log_dir, "renderer_js.old.log")
        try:
            if not os.path.exists(log_path):
                return False, self._pending_handoff
            size = os.path.getsize(log_path)
            if self._last_log_pos < 0 or size < self._last_log_pos:
                combined_chunks: list[str] = []
                if os.path.exists(old_log_path):
                    try:
                        old_size = os.path.getsize(old_log_path)
                        old_start = max(0, old_size - 1024 * 1024)
                        with open(old_log_path, "rb") as fold:
                            fold.seek(old_start)
                            combined_chunks.append(fold.read(old_size - old_start).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
                start_pos = max(0, size - 2 * 1024 * 1024)
                with open(log_path, "rb") as f:
                    f.seek(start_pos)
                    combined_chunks.append(f.read(size - start_pos).decode("utf-8", errors="ignore"))
                    self._last_log_pos = f.tell()
                _, needs_handoff = self._parse_discord_log_chunk("\n".join(combined_chunks))
                return bool(self._riot_sockets), (needs_handoff or self._pending_handoff)
            if size == self._last_log_pos:
                max_riot = self._max_riot_socket_id()
                if max_riot >= 0 and (self._our_socket_id < 0 or max_riot >= self._our_socket_id):
                    self._pending_handoff = True
                    return True, True
                return False, self._pending_handoff
            with open(log_path, "rb") as f:
                f.seek(self._last_log_pos)
                chunk = f.read(size - self._last_log_pos).decode("utf-8", errors="ignore")
                self._last_log_pos = f.tell()
            contended, needs_handoff = self._parse_discord_log_chunk(chunk)
            return contended, (needs_handoff or self._pending_handoff)
        except Exception:
            return False, self._pending_handoff

    def _check_riot_client_log_contended(self) -> bool:

        localappdata = os.environ.get("LOCALAPPDATA", "")
        if not localappdata:
            return False
        log_dir = os.path.join(localappdata, "Riot Games", "Riot Client", "Logs", "Riot Client Logs")
        try:
            if not self._riot_log_path or not os.path.exists(self._riot_log_path):
                logs = glob.glob(os.path.join(log_dir, "*_Riot Client.log"))
                if not logs:
                    return False
                self._riot_log_path = max(logs, key=os.path.getmtime)
                self._riot_log_pos = os.path.getsize(self._riot_log_path)
                return False
            size = os.path.getsize(self._riot_log_path)
            if size <= self._riot_log_pos:
                if size < self._riot_log_pos:
                    self._riot_log_pos = size
                return False
            with open(self._riot_log_path, "rb") as f:
                f.seek(self._riot_log_pos)
                chunk = f.read(size - self._riot_log_pos).decode("utf-8", errors="ignore")
                self._riot_log_pos = f.tell()
            now = time.monotonic()
            immediate_hit = False
            debounce_hit = False
            for line in chunk.splitlines():
                if "activitygateway/activities/v1/" in line or "sdk.social_layer_presence" in line:
                    immediate_hit = True
                elif "notifying REST of presence UPDATE for " in line and "valorant" in line:
                    if not self._my_puuid or self._my_puuid in line:
                        immediate_hit = True
                elif any(
                    marker in line
                    for marker in (
                        "ares-parties/parties/v1/",
                        "ares-pregame/pregame/v1/",
                        "ares-core-game/core-game/v1/",
                        "ares-session/v1/sessions/",
                    )
                ):
                    debounce_hit = True
            if immediate_hit:
                with self._lock:
                    self._ags_cache_ts = 0.0
                    self._schedule_waves_unlocked(now, (0.65, 2.00, 4.50, 8.50), replace=True)
                    self._transition_boost_until = max(self._transition_boost_until, now + 12.0)
                return True
            if debounce_hit:
                with self._lock:
                    self._ags_cache_ts = 0.0
                    self._schedule_waves_unlocked(now, (1.20, 3.00, 6.50), replace=False)
                    self._transition_boost_until = max(self._transition_boost_until, now + 12.0)
                return True
            return False
        except Exception:
            return False

    def _resolve_riot_discord_secret(self, party_id: str | None) -> tuple[str | None, list[int] | None]:

        now = time.monotonic()
        clean_pid = str(party_id or "").replace("rprn:party:valorant:", "").strip()
        if clean_pid != self._last_ags_party_id or (now - self._ags_cache_ts) >= 8.0:
            self._last_ags_party_id = clean_pid
            self._ags_cache_ts = now
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
                            data = resp.json()
                            if isinstance(data, dict) and isinstance(data.get("activities"), dict):
                                self._ags_activities = data["activities"]
            except Exception:
                pass

        best_act = None
        for act in (self._ags_activities or {}).values():
            if not isinstance(act, dict) or act.get("product") != "valorant" or not act.get("isMember"):
                continue
            secret = act.get("discordSecret")
            if not secret or not isinstance(secret, str):
                continue
            if clean_pid and act.get("id") == clean_pid:
                best_act = act
                break
            best_act = act

        if best_act:
            players = best_act.get("players") if isinstance(best_act.get("players"), dict) else {}
            cur_p = max(1, int(players.get("current") or 1))
            max_p = max(cur_p, int(players.get("max") or 5))
            self._last_discord_secret = str(best_act["discordSecret"])
            self._last_ags_size = [cur_p, max_p]
            return self._last_discord_secret, self._last_ags_size

        fallback_secret = self._last_discord_secret or (f"discord-{clean_pid[:12]}" if clean_pid else None)
        return fallback_secret, self._last_ags_size

    def _prepare_gateway_payload_unlocked(self, raw_payload: dict, force_flush: bool = False) -> dict:

        payload = dict(raw_payload)
        payload["pid"] = Processes.get_valorant_pid()
        payload.setdefault("instance", True)
        if "start" not in raw_payload and "end" not in raw_payload:
            payload["start"] = self._session_start_ts
        if force_flush:
            self._jitter_bit ^= 1
            if payload.get("end") is not None:
                payload["end"] = int(payload["end"]) + self._jitter_bit
            elif payload.get("start") is not None:
                payload["start"] = int(payload["start"]) + self._jitter_bit
            self._last_gateway_flush_ts = time.monotonic()
        party_id = payload.get("party_id")
        if party_id:
            clean_pid = str(party_id).replace("rprn:party:valorant:", "").strip()
            if clean_pid:
                payload["party_id"] = f"rprn:party:valorant:{clean_pid}"
            secret, ags_size = self._resolve_riot_discord_secret(clean_pid)
            psize = payload.get("party_size") or ags_size or [1, 5]
            if isinstance(psize, (list, tuple)) and len(psize) == 2:
                cur_s = max(1, int(psize[0]))
                max_s = max(cur_s, int(psize[1]))
                payload["party_size"] = [cur_s, max_s]
            if secret:
                payload["join"] = secret
                payload.pop("buttons", None)
        return payload

    def _reconnect_main_rpc_unlocked(self, payload: dict | None = None) -> bool:

        old_rpc = self._rpc
        try:
            new_rpc = PyPresence(client_id=self.client_id, loop=self._ipc_loop)
            new_rpc.connect()
            if payload is not None:
                new_rpc.update(**payload)
        except Exception:
            if old_rpc is not None:
                try:
                    old_rpc.close()
                except Exception:
                    pass
            self._rpc = None
            return False
        if old_rpc is not None:
            try:
                old_rpc.close()
            except Exception:
                pass
        self._rpc = new_rpc
        self._bump_our_socket_id_estimate()
        self._last_handoff_ts = time.monotonic()
        self._pending_handoff = False
        return True

    def _start_priority_guard(self) -> None:
        if self._guard_running:
            return
        self._guard_running = True
        threading.Thread(target=self._priority_guard_loop, daemon=True).start()

    def _priority_guard_loop(self) -> None:

        while self._guard_running:
            time.sleep(0.03)
            if not Processes.are_processes_running():
                self.clear_and_close()
                break
            ipc_contended, needs_handoff = self._check_discord_ipc_contended()
            self._check_riot_client_log_contended()
            now = time.monotonic()
            with self._lock:
                if self._rpc is None or not self._last_payload:
                    continue
                if ipc_contended:
                    self._schedule_waves_unlocked(now, (0.65, 2.00, 4.50), replace=False)
                if self._scheduled_handoff_at > 0 and now >= self._scheduled_handoff_at:
                    self._pending_handoff = True
                    self._scheduled_handoff_at = 0.0
                startup_text = Localizer.get_localized_text("presences", "client_states", "startup")
                is_startup_loading = self._last_payload.get("details") == startup_text
                can_handoff = (needs_handoff or self._pending_handoff) and (now - self._last_handoff_ts) >= 4.0
                if is_startup_loading:
                    if not can_handoff:
                        continue
                else:
                    due_wave = (
                        bool(self._preempt_waves)
                        and now >= self._preempt_waves[0]
                        and (now - self._last_gateway_flush_ts) >= 0.55
                        and self._can_flush_unlocked(now, reserve=1)
                    )
                    due_ipc = (
                        ipc_contended
                        and (now - self._last_gateway_flush_ts) >= 0.55
                        and self._can_flush_unlocked(now, reserve=0)
                    )
                    due_heartbeat = (
                        (now - self._last_gateway_flush_ts) >= 5.5
                        and self._can_flush_unlocked(now, reserve=2)
                    )
                    if not (can_handoff or due_wave or due_ipc or due_heartbeat):
                        continue
                    while self._preempt_waves and self._preempt_waves[0] <= now + 0.15:
                        self._preempt_waves.pop(0)
                payload = self._prepare_gateway_payload_unlocked(self._last_payload, force_flush=True)
                if can_handoff:
                    if self._reconnect_main_rpc_unlocked(payload=payload):
                        self._record_flush_unlocked(now)
                    continue
                try:
                    self._rpc.update(**payload)
                    self._record_flush_unlocked(now)
                except Exception:
                    if not self._reconnect_main_rpc_unlocked(payload=payload):
                        self._close_unlocked()
                        break
                    self._record_flush_unlocked(now)

    def ensure_connected(self) -> bool:
        with self._lock:
            if self._rpc is not None:
                return True
            try:
                self._check_discord_ipc_contended()
                self._check_riot_client_log_contended()
                if self._session_start_ts <= 0:
                    self._session_start_ts = int(time.time())
                rpc = PyPresence(client_id=self.client_id, loop=self._ipc_loop)
                rpc.connect()
                self._rpc = rpc
                self._bump_our_socket_id_estimate()
                self._last_handoff_ts = time.monotonic()
                self._pending_handoff = False
                self._flush_timestamps.clear()
                self._start_priority_guard()
                Logger.debug("[rpc] Connected to Discord IPC pipe.")
                return True
            except Exception as e:
                Logger.debug(f"[rpc] Discord IPC not available yet: {e}")
                self._rpc = None
                return False

    def update(self, **kwargs) -> None:
        if not Processes.are_processes_running():
            self.clear_and_close()
            return
        if not self.ensure_connected():
            return
        with self._lock:
            if self._rpc is None:
                return
            prepared = self._prepare_gateway_payload_unlocked(dict(kwargs), force_flush=False)
            state_sig = (
                prepared.get("details"),
                prepared.get("state"),
                prepared.get("large_image"),
                prepared.get("large_text"),
                prepared.get("small_image"),
                prepared.get("small_text"),
                tuple(prepared.get("party_size") or ()),
                prepared.get("party_id"),
                prepared.get("join"),
                kwargs.get("start"),
                kwargs.get("end"),
            )
            now = time.monotonic()
            state_changed = state_sig != self._last_state_sig
            self._last_payload = dict(kwargs)
            if not state_changed:
                return
            self._last_state_sig = state_sig
            startup_text = Localizer.get_localized_text("presences", "client_states", "startup")
            if kwargs.get("details") != startup_text:
                self._schedule_waves_unlocked(now, (0.75, 2.20, 5.00, 9.50), replace=False)
                self._transition_boost_until = max(self._transition_boost_until, now + 14.0)
            if not self._can_flush_unlocked(now, reserve=0):
                self._schedule_waves_unlocked(now, (0.55, 1.85, 4.20), replace=False)
                return
            payload = self._prepare_gateway_payload_unlocked(self._last_payload, force_flush=True)
            try:
                self._rpc.update(**payload)
                self._record_flush_unlocked(now)
            except Exception as e:
                Logger.debug(f"[rpc] IPC pipe lost during update ({e}); attempting seamless handoff.")
                if self._reconnect_main_rpc_unlocked(payload=payload):
                    self._record_flush_unlocked(now)
                else:
                    self._close_unlocked()

    def _close_unlocked(self) -> None:
        self._guard_running = False
        self._last_payload = None
        self._last_state_sig = None
        self._session_start_ts = 0
        self._pending_handoff = False
        self._scheduled_handoff_at = 0.0
        self._preempt_waves.clear()
        self._flush_timestamps.clear()
        if self._rpc is None:
            return
        rpc = self._rpc
        self._rpc = None
        try:
            rpc.clear()
        except Exception:
            pass
        try:
            rpc.close()
        except Exception:
            pass
        Logger.debug("[rpc] Cleared and closed Discord Rich Presence.")

    def clear_and_close(self) -> None:

        with self._lock:
            self._close_unlocked()

class Presence:

    def __init__(self, config):
        self.config = config
        self.client = None
        self.saved_locale = None
        self.cached_account_level = None
        self.rpc = SafeRPC(client_id=str(Localizer.get_config_value("client_id")))
        self.content_data = {}
        self._last_ptype: str = ""

    def disconnect_rpc(self) -> None:
        self._last_ptype = ""
        self.rpc.clear_and_close()

    def get_account_level(self, data=None):
        if self.cached_account_level is not None and self.cached_account_level > 0:
            return self.cached_account_level

        level = Utilities.fetch_account_level(self.client, data)
        if level and level > 0:
            self.cached_account_level = level

        return level

    def _resolve_and_update(self, presence_data: dict) -> None:

        pp = presence_data.get("partyPresenceData") or {}
        mp = presence_data.get("matchPresenceData") or {}
        session_state = (
            presence_data.get("sessionLoopState")
            or mp.get("sessionLoopState")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        )
        if isinstance(session_state, str):
            session_state = session_state.strip().upper()
        else:
            session_state = str(session_state).strip().upper()

        provisioning = (
            presence_data.get("provisioningFlow")
            or mp.get("provisioningFlow")
            or ""
        )
        if provisioning == "ShootingRange":
            self.update_presence("INGAME", presence_data)
            return

        if session_state in ("MENUS", "PREGAME", "INGAME"):
            self.update_presence(session_state, presence_data)
            return

        try:
            if self.client.pregame_fetch_player() is not None:
                self.update_presence("PREGAME", presence_data)
                return
        except Exception:
            pass

        try:
            if self.client.coregame_fetch_player() is not None:
                self.update_presence("INGAME", presence_data)
                return
        except Exception:
            pass

        self.update_presence("MENUS", presence_data)

    def _refresh_content_async(self) -> None:
        try:
            full_data = Loader.load_all_content(self.client, fast_only=False)
            if full_data:
                self.content_data = full_data
        except Exception:
            pass

    def run_active_session(self, initial_presence: dict | None = None) -> None:

        try:
            self.rpc.set_my_puuid(getattr(self.client, "puuid", ""))
            if not self.content_data or Localizer.locale != self.saved_locale:
                self.saved_locale = Localizer.locale
                self.content_data = Loader.load_all_content(self.client, fast_only=True)
                threading.Thread(target=self._refresh_content_async, daemon=True).start()
            elif not self.content_data.get("season"):
                threading.Thread(target=self._refresh_content_async, daemon=True).start()

            if initial_presence is not None:
                self._resolve_and_update(initial_presence)

            missing_ticks = 0
            while Processes.are_processes_running():
                if Localizer.locale != self.saved_locale:
                    self.saved_locale = Localizer.locale
                    self.content_data = Loader.load_all_content(self.client, fast_only=True)
                    threading.Thread(target=self._refresh_content_async, daemon=True).start()

                try:
                    presence_data = self.client.fetch_presence()
                except requests.exceptions.ConnectionError:
                    if not Processes.are_processes_running():
                        break
                    try:
                        self.client.activate()
                    except Exception:
                        pass
                    presence_data = None
                except Exception:
                    presence_data = None

                if presence_data is not None:
                    missing_ticks = 0
                    self._resolve_and_update(presence_data)
                else:
                    missing_ticks += 1
                    if not Processes.are_processes_running() or missing_ticks >= 120:
                        break

                time.sleep(min(0.25, float(Localizer.get_config_value("presence_refresh_interval") or 1.0)))
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            Logger.debug(f"[presence] Session error: {e}")
            traceback.print_exc()
        finally:
            self.disconnect_rpc()

    def init_loop(self) -> None:
        self.run_active_session()

    def update_presence(self, ptype, data=None):
        if not Processes.are_processes_running():
            self.disconnect_rpc()
            return
        try:
            ptype_upper = ptype.upper() if isinstance(ptype, str) else str(ptype).upper()
            effective_ptype = ptype_upper if ptype_upper in ("STARTUP", "MENUS", "PREGAME", "INGAME") else "MENUS"
            if effective_ptype != self._last_ptype:
                if self._last_ptype and effective_ptype != "STARTUP":
                    self.rpc.notify_state_transition()
                self._last_ptype = effective_ptype
            presence_types = {
                "STARTUP": startup,
                "MENUS": menu,
                "PREGAME": pregame,
                "INGAME": ingame,
            }

            if ptype_upper == "STARTUP":
                presence_types["STARTUP"].presence(self.rpc, client=self.client, data=data, content_data=self.content_data, config=self.config)
            elif ptype_upper in presence_types:
                presence_types[ptype_upper].presence(self.rpc, client=self.client, data=data, content_data=self.content_data, config=self.config)
            elif data is not None and ("partyState" in data or "queueId" in data):
                presence_types["MENUS"].presence(self.rpc, client=self.client, data=data, content_data=self.content_data, config=self.config)
        except requests.exceptions.ConnectionError:
            if not Processes.are_processes_running():
                self.disconnect_rpc()
        except Exception as e:
            Logger.debug(f"[presence] Failed to update {ptype} presence: {e}")
