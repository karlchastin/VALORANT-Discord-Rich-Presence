from pypresence import Presence as PyPresence
import asyncio, base64, collections, glob, os, pypresence.baseclient, pypresence.utils, re, requests, sys, threading, time, traceback, urllib3, winreg
urllib3.disable_warnings()

from ..utilities.processes import Processes
from ..utilities.logging import Logger
from ..utilities.rcs import Riot_Client_Services
from ..utilities.version_checker import Checker
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
        self._riot_log_scan_ts: float = 0.0
        self._ags_cache_ts: float = 0.0
        self._last_ags_party_id: str = ""
        self._ags_activities: dict = {}
        self._last_discord_secret: str | None = None
        self._last_activity_id: str | None = None
        self._discord_linked: bool = False
        self._last_ags_size: list[int] | None = None
        self._my_puuid: str = ""
        self._client = None
        self._systray = None
        self._protocol_registered: bool = False
        self._preempt_waves: list[float] = []
        self._flush_timestamps: collections.deque[float] = collections.deque()

    def set_my_puuid(self, puuid: str) -> None:
        if puuid:
            self._my_puuid = str(puuid).strip()

    def set_client(self, client) -> None:
        self._client = client
        if client is not None and getattr(client, "puuid", None):
            self._my_puuid = str(client.puuid).strip()

    def set_systray(self, systray) -> None:
        self._systray = systray

    def _register_discord_protocol(self) -> None:

        if self._protocol_registered or sys.platform != "win32":
            return
        try:
            rcs_path = Riot_Client_Services.get_rcs_path()
            if getattr(sys, "frozen", False):
                exe_path = os.path.abspath(sys.executable)
                cmd = f'"{exe_path}" --launch-valorant'
            elif rcs_path:
                exe_path = rcs_path
                cmd = f'"{rcs_path}" --launch-product=valorant --launch-patchline=live'
            else:
                exe_path = os.path.abspath(sys.executable)
                cmd = f'"{exe_path}"'

            base_key = rf"Software\Classes\discord-{self.client_id}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:Run game {self.client_id} protocol")
                winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base_key}\DefaultIcon") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, exe_path)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base_key}\shell\open\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
            self._protocol_registered = True
        except Exception:
            pass

    def _subscribe_ipc_events_unlocked(self, rpc: PyPresence) -> None:

        for evt in ("ACTIVITY_JOIN", "ACTIVITY_JOIN_REQUEST"):
            try:
                rpc.send_data(1, {"cmd": "SUBSCRIBE", "evt": evt, "nonce": f"sub_{evt}_{int(time.time() * 1000)}"})
                rpc.loop.run_until_complete(rpc.read_output())
            except Exception:
                pass

    def _on_ipc_frame_unlocked(self, frame: dict | None) -> None:
        if not isinstance(frame, dict):
            return
        evt = frame.get("evt")
        data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
        if evt == "ACTIVITY_JOIN_REQUEST":
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            user_id = str(user.get("id") or "").strip()
            if user_id and self._rpc is not None:
                try:
                    self._rpc.send_data(
                        1,
                        {
                            "cmd": "SEND_ACTIVITY_JOIN_INVITE",
                            "args": {"user_id": user_id},
                            "nonce": f"invite_{user_id}_{int(time.time() * 1000)}",
                        },
                    )
                    self._rpc.loop.run_until_complete(self._rpc.read_output())
                except Exception:
                    pass
        elif evt == "ACTIVITY_JOIN":
            secret = str(data.get("secret") or "").strip()
            if secret:
                threading.Thread(target=self._handle_activity_join, args=(secret,), daemon=True).start()

    def _drain_ipc_events_unlocked(self) -> None:
        if self._rpc is None or self._rpc.sock_reader is None or self._rpc.loop is None:
            return
        try:
            self._rpc.loop.run_until_complete(asyncio.sleep(0))
            while len(self._rpc.sock_reader._buffer) >= 8:
                frame = self._rpc.loop.run_until_complete(self._rpc.read_output())
                self._on_ipc_frame_unlocked(frame)
        except Exception:
            pass

    def _send_activity_update_unlocked(self, payload: dict) -> None:
        self._drain_ipc_events_unlocked()
        res = self._rpc.update(**payload)
        while isinstance(res, dict) and res.get("evt") in ("ACTIVITY_JOIN", "ACTIVITY_JOIN_REQUEST"):
            self._on_ipc_frame_unlocked(res)
            res = self._rpc.loop.run_until_complete(self._rpc.read_output())

    def _handle_activity_join(self, secret: str) -> None:

        Logger.debug(f"[rpc] Handling ACTIVITY_JOIN for secret={secret!r}")
        riot_secret = ""
        target_party_id = ""
        host_puuid = ""
        activity_id = ""

        if "|valrpc:" in secret:
            riot_part, valrpc_part = secret.split("|valrpc:", 1)
            riot_secret = riot_part.strip()
            tokens = valrpc_part.strip().split(":")
            if len(tokens) >= 1:
                target_party_id = tokens[0].strip()
            if len(tokens) >= 2:
                host_puuid = tokens[1].strip()
            if len(tokens) >= 3:
                activity_id = tokens[2].strip()
        elif secret.startswith("valrpc:"):
            tokens = secret[7:].strip().split(":")
            if len(tokens) >= 1:
                target_party_id = tokens[0].strip()
            if len(tokens) >= 2:
                host_puuid = tokens[1].strip()
            if len(tokens) >= 3:
                activity_id = tokens[2].strip()
            if len(tokens) >= 4:
                riot_secret = tokens[3].strip()
        elif secret.startswith("discord-"):
            riot_secret = secret.strip()

        if not Processes.are_processes_running():
            rcs_path = Riot_Client_Services.get_rcs_path()
            if rcs_path:
                try:
                    import subprocess
                    subprocess.Popen([rcs_path, "--launch-product=valorant", "--launch-patchline=live"])
                except Exception:
                    pass
            for _ in range(90):
                if Processes.are_processes_running() and self._client is not None:
                    break
                time.sleep(0.5)

        client = self._client
        if client is not None and target_party_id:
            try:
                cur_party = client.fetch_party() or {}
                if str(cur_party.get("ID") or "").strip() == target_party_id:
                    return
            except Exception:
                pass

        lf = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
        port = pw = auth = ""
        if os.path.isfile(lf):
            try:
                with open(lf, "r", encoding="utf-8") as f:
                    parts = f.read().strip().split(":")
                if len(parts) >= 4:
                    port, pw = parts[2], parts[3]
                    auth = base64.b64encode(f"riot:{pw}".encode("utf-8")).decode("ascii")
            except Exception:
                pass

        if port and auth:
            headers = {"Authorization": f"Basic {auth}"}
            if not activity_id:
                try:
                    r_acts = requests.get(
                        f"https://127.0.0.1:{port}/activity-gateway/v1/activities",
                        headers=headers,
                        verify=False,
                        timeout=0.8,
                    )
                    if r_acts.status_code == 200:
                        for act in ((r_acts.json() or {}).get("activities") or {}).values():
                            if not isinstance(act, dict) or act.get("product") != "valorant":
                                continue
                            if (riot_secret and act.get("discordSecret") == riot_secret) or (target_party_id and act.get("id") == target_party_id):
                                activity_id = str(act.get("activityId") or "").strip()
                                if not target_party_id:
                                    target_party_id = str(act.get("id") or "").strip()
                                break
                except Exception:
                    pass

            if not activity_id or not target_party_id or not host_puuid:
                try:
                    r_friends = requests.get(
                        f"https://127.0.0.1:{port}/social/v4/friends",
                        headers=headers,
                        verify=False,
                        timeout=0.8,
                    )
                    if r_friends.status_code == 200:
                        for fr in (r_friends.json() or {}).get("friends") or []:
                            if not isinstance(fr, dict) or fr.get("product") != "valorant":
                                continue
                            f_puuid = str(fr.get("puuid") or "").strip()
                            f_party = fr.get("party") if isinstance(fr.get("party"), dict) else {}
                            f_pid = str(f_party.get("id") or "").replace("rprn:party:valorant:", "").strip()
                            if (host_puuid and f_puuid == host_puuid) or (target_party_id and f_pid == target_party_id):
                                if not target_party_id and f_pid:
                                    target_party_id = f_pid
                                if not host_puuid and f_puuid:
                                    host_puuid = f_puuid
                                for action in f_party.get("actions") or []:
                                    if isinstance(action, str) and ":ags:" in action and not activity_id:
                                        activity_id = action.rsplit(":ags:", 1)[-1].strip()
                                break
                except Exception:
                    pass

            if activity_id:
                try:
                    r_lookup = requests.get(
                        f"https://127.0.0.1:{port}/activity-gateway/v1/activities/{activity_id}/lookup",
                        headers=headers,
                        verify=False,
                        timeout=1.2,
                    )
                    if r_lookup.status_code == 200:
                        lk = r_lookup.json() or {}
                        if not target_party_id and lk.get("id"):
                            target_party_id = str(lk.get("id")).strip()
                        if not riot_secret and lk.get("discordSecret"):
                            riot_secret = str(lk.get("discordSecret")).strip()
                except Exception:
                    pass

                if riot_secret:
                    try:
                        r_join = requests.post(
                            f"https://127.0.0.1:{port}/activity-gateway/v1/activities/{activity_id}/join",
                            headers=headers,
                            json={"discordSecret": riot_secret, "product": "valorant"},
                            verify=False,
                            timeout=1.8,
                        )
                        if r_join.status_code in (200, 204):
                            time.sleep(0.35)
                            if client is not None and target_party_id:
                                cur_party = client.fetch_party() or {}
                                if str(cur_party.get("ID") or "").strip() == target_party_id:
                                    setattr(client, "_live_party_cache", (0.0, None))
                                    Logger.debug(f"[rpc] Joined party {target_party_id} via Native Riot Activity Gateway.")
                                    return
                    except Exception:
                        pass

        if client is not None and target_party_id:
            try:
                res = client.party_join(target_party_id) or {}
                joined_id = str(res.get("ID") or "").strip()
                if not joined_id:
                    time.sleep(0.25)
                    joined_id = str((client.fetch_party() or {}).get("ID") or "").strip()
                if joined_id == target_party_id:
                    setattr(client, "_live_party_cache", (0.0, None))
                    Logger.debug(f"[rpc] Joined party {target_party_id} via RPC valclient fallback.")
                    return
            except Exception:
                pass

            if host_puuid:
                try:
                    client.party_request_to_join(target_party_id, host_puuid)
                    Logger.debug(f"[rpc] Sent in-game party_request_to_join for party {target_party_id} (host={host_puuid}).")
                except Exception:
                    pass
                if port and auth and activity_id:
                    try:
                        requests.post(
                            f"https://127.0.0.1:{port}/activity-gateway/v1/activities/{activity_id}/request-invite",
                            headers={"Authorization": f"Basic {auth}"},
                            json={"member": host_puuid},
                            verify=False,
                            timeout=1.2,
                        )
                    except Exception:
                        pass

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
            self._transition_boost_until = max(self._transition_boost_until, now + duration)
            self._schedule_waves_unlocked(now, (0.80, 2.20, 3.80, 6.50, 11.50), replace=False)
            self._last_ags_party_id = ""
            self._ags_activities.clear()
            self._last_discord_secret = None
            self._last_activity_id = None
            self._last_ags_size = None
            self._ags_cache_ts = 0.0
            self._last_state_sig = None

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
                elif app_id in _RIOT_NATIVE_DISCORD_IDS:
                    self._riot_sockets.add(sock_id)
                    contended = True
                continue
            m_close = _RE_IPC_CLOSE.search(line)
            if m_close:
                closed_sock = m_close.group(1)
                self._riot_sockets.discard(closed_sock)
                if int(closed_sock) == self._our_socket_id:
                    self._our_socket_id = -1
                continue
            m_msg = _RE_IPC_MSG.search(line)
            if m_msg:
                msg_sock = m_msg.group(1)
                msg_sid = int(msg_sock)
                self._last_opened_socket_id = max(self._last_opened_socket_id, msg_sid)
                if msg_sock in self._riot_sockets:
                    contended = True

        return contended, self._pending_handoff

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
                return False, (needs_handoff or self._pending_handoff)
            if size == self._last_log_pos:
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
            now = time.monotonic()
            if not self._riot_log_path or not os.path.exists(self._riot_log_path) or (now - self._riot_log_scan_ts) >= 2.0:
                self._riot_log_scan_ts = now
                logs = glob.glob(os.path.join(log_dir, "*_Riot Client.log"))
                if not logs:
                    return False
                newest = max(logs, key=os.path.getmtime)
                if newest != self._riot_log_path:
                    self._riot_log_path = newest
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
            immediate_hit = False
            debounce_hit = False
            for line in chunk.splitlines():
                if "activitygateway/activities/v1/" in line or "sdk.social_layer_presence" in line or "product session purge data" in line:
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
                    self._schedule_waves_unlocked(now, (0.80, 2.20, 3.80, 6.50, 11.50), replace=True)
                    self._transition_boost_until = max(self._transition_boost_until, now + 15.0)
                return True
            if debounce_hit:
                with self._lock:
                    self._ags_cache_ts = 0.0
                    self._schedule_waves_unlocked(now, (1.20, 3.50, 6.80), replace=False)
                    self._transition_boost_until = max(self._transition_boost_until, now + 12.0)
                return True
            return False
        except Exception:
            return False

    def _resolve_riot_discord_secret(self, party_id: str | None) -> tuple[str | None, str | None, bool, list[int] | None]:

        now = time.monotonic()
        clean_pid = str(party_id or "").replace("rprn:party:valorant:", "").replace("valrpc:", "").strip()
        if not clean_pid:
            return None, None, False, None

        if clean_pid != self._last_ags_party_id:
            self._last_discord_secret = None
            self._last_activity_id = None
            self._last_ags_size = None

        if clean_pid != self._last_ags_party_id or (now - self._ags_cache_ts) >= 8.0:
            try:
                lf = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
                if os.path.isfile(lf):
                    with open(lf, "r", encoding="utf-8") as f:
                        parts = f.read().strip().split(":")
                    if len(parts) >= 4:
                        port, pw = parts[2], parts[3]
                        auth = base64.b64encode(f"riot:{pw}".encode("utf-8")).decode("ascii")
                        headers = {"Authorization": f"Basic {auth}"}
                        try:
                            r_aes = requests.get(
                                f"https://127.0.0.1:{port}/aes/v1/status/discord",
                                headers=headers,
                                verify=False,
                                timeout=0.4,
                            )
                            if r_aes.status_code == 200:
                                aes_data = r_aes.json() or {}
                                self._discord_linked = (aes_data.get("type") == "Available" and not aes_data.get("error"))
                        except Exception:
                            pass

                        resp = requests.get(
                            f"https://127.0.0.1:{port}/activity-gateway/v1/activities",
                            headers=headers,
                            verify=False,
                            timeout=0.5,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            if isinstance(data, dict) and isinstance(data.get("activities"), dict):
                                self._ags_activities = data["activities"]
                                for act in self._ags_activities.values():
                                    if (
                                        isinstance(act, dict)
                                        and act.get("product") == "valorant"
                                        and act.get("isMember")
                                        and act.get("id") == clean_pid
                                    ):
                                        act_id = str(act.get("activityId") or "").strip()
                                        players = act.get("players") if isinstance(act.get("players"), dict) else {}
                                        if act_id and (int(players.get("max") or 0) <= 0 or not act.get("discordSecret")):
                                            try:
                                                r_lk = requests.get(
                                                    f"https://127.0.0.1:{port}/activity-gateway/v1/activities/{act_id}/lookup",
                                                    headers=headers,
                                                    verify=False,
                                                    timeout=0.5,
                                                )
                                                if r_lk.status_code == 200 and isinstance(r_lk.json(), dict):
                                                    self._ags_activities[act_id] = r_lk.json()
                                            except Exception:
                                                pass
                                        break
            except Exception:
                pass

        best_act = None
        for act in (self._ags_activities or {}).values():
            if not isinstance(act, dict) or act.get("product") != "valorant" or not act.get("isMember"):
                continue
            if act.get("id") == clean_pid:
                best_act = act
                break

        if best_act:
            players = best_act.get("players") if isinstance(best_act.get("players"), dict) else {}
            cur_p = max(1, int(players.get("current") or 1))
            max_p = max(cur_p, int(players.get("max") or 5))
            self._last_ags_party_id = clean_pid
            self._ags_cache_ts = now
            secret_val = best_act.get("discordSecret")
            self._last_discord_secret = str(secret_val).strip() if isinstance(secret_val, str) and secret_val.strip() else None
            act_id_val = best_act.get("activityId")
            self._last_activity_id = str(act_id_val).strip() if isinstance(act_id_val, str) and act_id_val.strip() else None
            self._last_ags_size = [cur_p, max_p]
            return self._last_discord_secret, self._last_activity_id, self._discord_linked, self._last_ags_size

        self._last_ags_party_id = clean_pid
        self._ags_cache_ts = now - 7.0
        return None, None, self._discord_linked, None

    def _prepare_gateway_payload_unlocked(self, raw_payload: dict, force_flush: bool = False) -> dict:

        payload = dict(raw_payload)
        payload.pop("buttons", None)

        for field in ("details", "state", "large_image", "large_text", "small_image", "small_text"):
            if field in payload:
                val = payload[field]
                if val is None or (isinstance(val, str) and not val.strip()):
                    payload.pop(field, None)

        if "large_image" not in payload:
            payload.pop("large_text", None)
            payload.pop("small_image", None)
            payload.pop("small_text", None)
        elif "small_image" not in payload:
            payload.pop("small_text", None)

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
            clean_pid = str(party_id).replace("rprn:party:valorant:", "").replace("valrpc:", "").strip()
            riot_secret, activity_id, is_linked, _ags_size = self._resolve_riot_discord_secret(clean_pid)
            if clean_pid:
                if is_linked and riot_secret:
                    payload["party_id"] = f"rprn:party:valorant:{clean_pid}"
                else:
                    payload["party_id"] = f"valrpc:{clean_pid}"
            psize = payload.get("party_size") or [1, 5]
            if isinstance(psize, (list, tuple)) and len(psize) == 2:
                cur_s = max(1, int(psize[0]))
                max_s = max(cur_s, int(psize[1]))
                payload["party_size"] = [cur_s, max_s]
            if clean_pid:
                valrpc_token = f"valrpc:{clean_pid}:{self._my_puuid}:{activity_id or ''}"
                if riot_secret:
                    combined = f"{riot_secret}|{valrpc_token}"
                    payload["join"] = combined if len(combined) <= 128 else riot_secret
                else:
                    payload["join"] = valrpc_token[:128]
                payload.pop("buttons", None)
        else:
            payload.pop("party_id", None)
            payload.pop("party_size", None)
            payload.pop("join", None)
        return payload

    def _reconnect_main_rpc_unlocked(self, payload: dict | None = None) -> bool:

        old_rpc = self._rpc
        try:
            new_rpc = PyPresence(client_id=self.client_id)
            new_rpc.connect()
            self._subscribe_ipc_events_unlocked(new_rpc)
            if payload is not None:
                new_rpc.update(**payload)
        except Exception:
            return False

        self._rpc = new_rpc
        if old_rpc is not None:
            try:
                old_rpc.close()
            except Exception:
                pass
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
                if self._rpc is None:
                    continue
                self._drain_ipc_events_unlocked()
                if not self._last_payload:
                    continue
                if self._scheduled_handoff_at > 0 and now >= self._scheduled_handoff_at:
                    self._pending_handoff = True
                    self._scheduled_handoff_at = 0.0
                startup_text = Localizer.get_localized_text("presences", "startup", "loading")
                is_startup_loading = self._last_payload.get("details") == startup_text
                can_handoff = self._pending_handoff and (now - self._last_handoff_ts) >= 4.0
                if is_startup_loading:
                    if not can_handoff:
                        continue
                else:
                    due_wave = (
                        bool(self._preempt_waves)
                        and now >= self._preempt_waves[0]
                        and (now - self._last_gateway_flush_ts) >= 0.75
                        and self._can_flush_unlocked(now, reserve=2)
                    )
                    due_ipc = (
                        ipc_contended
                        and (now - self._last_gateway_flush_ts) >= 0.08
                    )
                    if not (can_handoff or due_wave or due_ipc):
                        continue
                    while self._preempt_waves and self._preempt_waves[0] <= now + 0.15:
                        self._preempt_waves.pop(0)
                payload = self._prepare_gateway_payload_unlocked(self._last_payload, force_flush=True)
                if can_handoff:
                    if self._reconnect_main_rpc_unlocked(payload=payload):
                        self._record_flush_unlocked(now)
                    continue
                if not self._can_flush_unlocked(now, reserve=0):
                    if self._reconnect_main_rpc_unlocked(payload=payload):
                        self._flush_timestamps.clear()
                        self._record_flush_unlocked(now)
                    continue
                try:
                    self._send_activity_update_unlocked(payload)
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
                self._register_discord_protocol()
                self._check_discord_ipc_contended()
                self._check_riot_client_log_contended()
                if self._session_start_ts <= 0:
                    self._session_start_ts = int(time.time())
                rpc = PyPresence(client_id=self.client_id)
                rpc.connect()
                self._subscribe_ipc_events_unlocked(rpc)
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
            startup_text = Localizer.get_localized_text("presences", "startup", "loading")
            if kwargs.get("details") != startup_text:
                self._schedule_waves_unlocked(now, (1.20,), replace=True)
                self._transition_boost_until = max(self._transition_boost_until, now + 4.0)
            if not self._can_flush_unlocked(now, reserve=0):

                payload = self._prepare_gateway_payload_unlocked(self._last_payload, force_flush=True)
                if self._reconnect_main_rpc_unlocked(payload=payload):
                    self._flush_timestamps.clear()
                    self._record_flush_unlocked(now)
                    return
                else:
                    self._schedule_waves_unlocked(now, (0.55, 1.85), replace=False)
                    return
            payload = self._prepare_gateway_payload_unlocked(self._last_payload, force_flush=True)
            try:
                self._send_activity_update_unlocked(payload)
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
        self._last_menu_update_check_ts: float = 0.0
        self._menu_update_check_in_flight: bool = False

    def _poll_menu_update_if_due(self) -> None:

        now = time.monotonic()
        if self._menu_update_check_in_flight or (now - self._last_menu_update_check_ts) < 5.0:
            return
        self._last_menu_update_check_ts = now
        self._menu_update_check_in_flight = True

        def _worker():
            try:
                Checker.check_remote_signal(self.config)
            except Exception:
                pass
            finally:
                self._menu_update_check_in_flight = False

        threading.Thread(target=_worker, daemon=True).start()

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
        raw_state = (
            ("INGAME" if mp.get("sessionLoopState") == "INGAME" else None)
            or presence_data.get("sessionLoopState")
            or mp.get("sessionLoopState")
            or pp.get("partyOwnerSessionLoopState")
            or ""
        )
        if isinstance(raw_state, str):
            session_state = raw_state.strip().upper()
        else:
            session_state = str(raw_state).strip().upper()

        if session_state in ("MENUS", "PREGAME"):
            if (
                session_state == "MENUS"
                and (
                    getattr(self.client, "_game_flow_state", "") in ("TransitionToInGame", "InGame")
                    or time.monotonic() < getattr(self.client, "_match_hint_until", 0.0)
                )
            ) or (
                session_state == "PREGAME"
                and (
                    getattr(self.client, "_game_flow_state", "") in ("TransitionToInGame", "InGame")
                    or time.monotonic() < getattr(self.client, "_match_hint_until", 0.0)
                )
            ):
                try:
                    if self.client.coregame_fetch_player() is not None:
                        self.update_presence("INGAME", presence_data)
                        return
                except Exception:
                    pass
            self.update_presence(session_state, presence_data)
            return

        provisioning = (
            presence_data.get("provisioningFlow")
            or mp.get("provisioningFlow")
            or ""
        )
        if provisioning == "ShootingRange" or Utilities.is_range(presence_data) or Utilities.is_replay_session(presence_data):
            self.update_presence("INGAME", presence_data)
            return

        if session_state == "INGAME":
            self.update_presence("INGAME", presence_data)
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
            self.rpc.set_client(self.client)
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
            if effective_ptype == "MENUS":

                pp = (data or {}).get("partyPresenceData") if isinstance(data, dict) else {}
                pstate = str((data or {}).get("partyState") or (pp or {}).get("partyState") or "").upper()
                if pstate not in ("MATCHMAKING", "STARTING_MATCHMAKING", "MATCHMADE_GAME_STARTING"):
                    self._poll_menu_update_if_due()
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
