"""The connection manager: one place that decides how the share service is reached and reports the truth about it.

States shown to the owner: Sharing online, Connecting, Reconnecting, Sharing offline, or Failed with a reason.
"Online" is only reported after Handoff fetches its own /healthz through the public address and sees this very run's
instance id, so the link shown has actually been proven to lead here.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .binaries import HelperDownloader, HelperError
from .providers import QuickTunnel, detect_lan_ip, normalize_custom_url, tailscale_info

log = logging.getLogger("handoff.sharing")

PROVIDERS = ("lan", "quick", "custom", "tailscale")
LABELS = {
    "lan": "Same Wi-Fi", "quick": "Quick Share (temporary)", "custom": "Your own address", "tailscale": "Tailscale (advanced)",
}

QUICK_TERMS = (
    "Quick Share sends visitors through a free tunnel run by Cloudflare. Cloudflare describes these tunnels as being "
    "for testing and development, with no uptime guarantee. The address changes every time Handoff restarts or "
    "reconnects, so a link you sent earlier may stop working. Traffic passes through Cloudflare, which can in principle "
    "see it. Limits on usage or bandwidth may apply and can change, and your computer must stay on and online. "
    "Handoff will download Cloudflare's helper program once and check its fingerprint before using it."
)


TEMP_NOTE = "This address is temporary and changes when Handoff restarts or reconnects."
VERIFIED_MSG = "Sharing online. " + TEMP_NOTE
UNVERIFIED_MSG = (
    "Sharing is on, but this computer couldn't confirm the link yet (its own internet lookup can be slow for brand-new "
    "addresses). Open the link on your phone using mobile data to check it. " + TEMP_NOTE
)


class State(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class ConsentRequired(Exception):
    def __init__(self):
        super().__init__(QUICK_TERMS)


class SharingError(Exception):
    pass


def default_health_check(base_url: str, instance: str, timeout: float = 8.0) -> bool:
    """True if `base_url` leads to THIS running Handoff (matching instance id)."""
    try:
        req = urllib.request.Request(base_url + "/healthz", headers={"User-Agent": "Handoff-selfcheck/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (owner-chosen address)
            data = json.load(r)
        return data.get("app") == "handoff" and data.get("instance") == instance
    except Exception:  # noqa: BLE001 - any failure simply means "not reachable"
        return False


class ConnectionManager:
    def __init__(
        self,
        ctx,
        gate: bool = False,
        downloader: HelperDownloader | None = None,
        health_check: Callable[[str, str], bool] = default_health_check,
        tunnel_factory: Callable[[Path, int, Path], Any] = QuickTunnel,
        lan_ip: Callable[[], str] = detect_lan_ip,
        tailscale: Callable[[], dict] = tailscale_info,
        poll: float = 2.0,
        health_every: float = 20.0,
        connect_timeout: float = 90.0,
        address_timeout: float = 30.0,
        edge_timeout: float = 45.0,
        settle: float = 3.0,
        check_window: float = 25.0,
    ):
        self.ctx = ctx
        self.gate = gate  # desktop mode: the share service only answers while sharing is switched on
        self._bin_dir = ctx.settings.data_dir.parent / "bin" if gate else ctx.settings.data_dir / "bin"
        self.downloader = downloader or HelperDownloader(self._bin_dir)
        self.health_check = health_check
        self.tunnel_factory = tunnel_factory
        self.lan_ip = lan_ip
        self.tailscale = tailscale
        self.poll, self.health_every, self.connect_timeout = poll, health_every, connect_timeout
        self.address_timeout, self.edge_timeout, self.settle, self.check_window = address_timeout, edge_timeout, settle, check_window
        self._verified = True  # False only for Quick Share when this computer could not confirm the link

        self._lock = threading.RLock()
        self._state = State.OFFLINE
        self._message = "Sharing is off."
        self._since = time.time()
        self._provider: str | None = None
        self._base: str | None = None
        self._wanted = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tunnel: Any = None
        self._address_changed = False
        self._helper = {"phase": "idle", "percent": 0}
        self._tailscale_command: str | None = None

    # ------------------------------------------------------------------ reading
    @property
    def db(self):
        return self.ctx.db

    def saved_provider(self) -> str | None:
        return self.db.get_setting("sharing.provider")

    def quick_consented(self) -> bool:
        return bool(self.db.get_setting("sharing.quick_consent_at"))

    def accepting(self) -> bool:
        """Should the share service answer visitors? Always yes in server mode; in desktop mode only while sharing is on."""
        return (not self.gate) or self._wanted

    @staticmethod
    def wants_network_listener(provider: str | None) -> bool:
        """Only same-Wi-Fi and own-address sharing need the share service to listen beyond this computer.
        Tunnels connect to it locally, so for them it listens on this computer only."""
        return provider in ("lan", "custom")

    def accepts_peer(self, peer: str) -> bool:
        """Desktop mode: refuse connections from other computers unless the chosen method needs them."""
        if not self.gate or peer in ("127.0.0.1", "::1", "localhost"):
            return True
        return self.wants_network_listener(self._provider)

    @property
    def tunnel_active(self) -> bool:
        t = self._tunnel
        return bool(self._provider == "quick" and t is not None and t.alive())

    def base_url(self) -> str | None:
        with self._lock:
            return self._base if self._state in (State.ONLINE, State.RECONNECTING) else None

    def link_base(self) -> str:
        """Address to build links from. In server mode this is PUBLIC_BASE_URL or localhost."""
        return self.base_url() or self.ctx.settings.share_base()

    def status(self) -> dict:
        with self._lock:
            provider = self._provider or self.saved_provider()
            return {
                "managed": self.gate,
                "state": self._state.value,
                "message": self._message,
                "since": self._since,
                "provider": provider,
                "provider_label": LABELS.get(provider or "", None),
                "base_url": self._base if self._state in (State.ONLINE, State.RECONNECTING) else None,
                "temporary": provider == "quick",
                "address_changed": self._address_changed,
                "verified": self._verified,
                "helper": dict(self._helper),
                "quick_consented": self.quick_consented(),
                "quick_terms": QUICK_TERMS,
                "custom_url": self.db.get_setting("sharing.custom_url"),
                "tailscale_command": self._tailscale_command,
                "share_port": self.ctx.settings.share_port,
            }

    # ---------------------------------------------------------------- internals
    def _set(self, state: State, message: str, base: str | None = None, keep_base: bool = True) -> None:
        with self._lock:
            if state != self._state:
                self._since = time.time()
            self._state, self._message = state, message
            if base is not None:
                self._base = base
            elif not keep_base:
                self._base = None
        log.info("sharing: %s (%s)", state.value, message)

    def _go_online(self, base: str, message: str, verified: bool = True) -> None:
        last = self.db.get_setting("sharing.last_base_url")
        with self._lock:
            self._verified = verified
            if last and last != base:
                self._address_changed = True
        self.db.set_setting("sharing.last_base_url", base)
        self._set(State.ONLINE, message, base=base)

    def dismiss_address_change(self) -> None:
        with self._lock:
            self._address_changed = False

    def _wait(self, seconds: float) -> bool:
        """Sleep; True means stop was requested."""
        return self._stop.wait(seconds)

    def _healthy(self, base: str) -> bool:
        return self.health_check(base, self.ctx.instance_id)

    def _until(self, predicate: Callable[[], Any], timeout: float, interval: float | None = None) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            value = predicate()
            if value:
                return value
            self._stop.wait(interval or min(self.poll, 1.0))
        return None

    # ------------------------------------------------------------------ control
    def start(self, provider: str, custom_url: str | None = None, accept_quick_terms: bool = False) -> dict:
        if provider not in PROVIDERS:
            raise SharingError("Unknown connection method.")
        if provider == "quick" and not self.quick_consented():
            if not accept_quick_terms:
                raise ConsentRequired()
            self.db.set_setting("sharing.quick_consent_at", str(int(time.time())))
        if provider == "custom":
            try:
                custom_url = normalize_custom_url(custom_url or self.db.get_setting("sharing.custom_url") or "")
            except ValueError as e:
                raise SharingError(str(e)) from e
            self.db.set_setting("sharing.custom_url", custom_url)
        self._shutdown_worker()
        self.db.set_setting("sharing.provider", provider)
        with self._lock:
            self._provider, self._wanted, self._base = provider, True, None
            self._stop = threading.Event()
        if self.ctx.share_bind_hook:
            self.ctx.share_bind_hook("0.0.0.0" if self.wants_network_listener(provider) else "127.0.0.1")
        self._set(State.CONNECTING, "Starting…")
        targets = {"lan": self._run_lan, "quick": self._run_quick, "custom": self._run_custom, "tailscale": self._run_tailscale}
        self._thread = threading.Thread(target=self._guard, args=(targets[provider],), daemon=True, name=f"sharing-{provider}")
        self._thread.start()
        return self.status()

    def _guard(self, target: Callable[[], None]) -> None:
        try:
            target()
        except Exception as e:  # noqa: BLE001 - never let the worker die silently
            log.exception("sharing worker crashed")
            self._set(State.FAILED, f"Something went wrong ({type(e).__name__}). Try again, or pick another method.")

    def stop(self) -> dict:
        """Stop sharing. In desktop mode the share service also stops answering, so nothing stays reachable."""
        with self._lock:
            self._wanted = False
        self._shutdown_worker()
        if self.ctx.share_bind_hook:
            self.ctx.share_bind_hook("127.0.0.1")  # nothing should be listening beyond this computer while stopped
        self._set(State.OFFLINE, "Sharing is stopped. Clients can't open your links until you start it again.", keep_base=False)
        return self.status()

    def _shutdown_worker(self) -> None:
        self._stop.set()
        t = self._tunnel
        if t is not None:
            t.stop()
        th = self._thread
        if th and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=8)
        self._tunnel = None
        self._thread = None

    def ensure_online(self, timeout: float = 90.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._state == State.ONLINE:
                return True
            if self._state == State.OFFLINE and not self._wanted:
                return False
            time.sleep(0.2)
        return self._state == State.ONLINE

    def resume_saved(self) -> bool:
        """On launch, continue with the method the owner used last, if it needs no new permission."""
        provider = self.saved_provider()
        if provider in ("lan", "custom") or (provider == "quick" and self.quick_consented()):
            try:
                self.start(provider)
                return True
            except (SharingError, ConsentRequired):
                return False
        return False

    # ---------------------------------------------------------------- providers
    def _run_lan(self) -> None:
        port = self.ctx.settings.share_port
        last_ip = None
        while not self._stop.is_set():
            ip = self.lan_ip()
            if ip.startswith("127."):
                self._set(State.RECONNECTING, "No network connection found. Connect to Wi-Fi or a network.", keep_base=False)
                last_ip = None
            elif ip != last_ip:
                if not self.health_check(f"http://127.0.0.1:{port}", self.ctx.instance_id):
                    self._set(State.FAILED, "The sharing service on this computer isn't answering.")
                else:
                    base = f"http://{ip}:{port}"
                    self._go_online(base, "Sharing on this Wi-Fi only. People on other networks can't open these links, and the link is not encrypted (plain HTTP).")
                    last_ip = ip
            if self._wait(max(self.poll, 0.05) * 3):
                return

    def _run_custom(self) -> None:
        base = self.db.get_setting("sharing.custom_url") or ""
        deadline = time.monotonic() + self.connect_timeout
        failing = 0
        first = True
        while not self._stop.is_set():
            ok = self._healthy(base)
            if ok:
                failing = 0
                if self._state != State.ONLINE:
                    self._go_online(base, "Sharing online through your own address.")
                first = False
            else:
                failing += 1
                if self._state == State.ONLINE and failing >= 2:
                    self._set(State.RECONNECTING, f"Can't reach {base} right now. Checking again…")
                elif first and time.monotonic() > deadline:
                    self._set(State.FAILED, f"Handoff can't reach {base}. Check that it forwards to this computer's share port "
                              f"({self.ctx.settings.share_port}) and that your internet connection is working. Handoff keeps checking.")
            if self._wait(max(self.poll, 0.05) * (1 if self._state != State.ONLINE else 5)):
                return

    def _run_tailscale(self) -> None:
        port = self.ctx.settings.share_port
        self._tailscale_command = f"tailscale funnel --bg {port}"
        deadline = time.monotonic() + max(self.connect_timeout, 180)
        while not self._stop.is_set():
            info = self.tailscale()
            if not info.get("installed"):
                self._set(State.FAILED, "Tailscale isn't installed. Install it from tailscale.com, sign in, then try again.")
            elif not info.get("running") or not info.get("dns_name"):
                self._set(State.FAILED, "Tailscale is installed but not signed in or not running. Open Tailscale and sign in.")
            else:
                base = f"https://{info['dns_name']}"
                if self._healthy(base):
                    self._go_online(base, "Sharing online through Tailscale Funnel. Bandwidth limits apply and Tailscale does not publish them.")
                else:
                    msg = (f"Waiting for Tailscale Funnel. Run this once in a terminal, then Handoff will detect it: "
                           f"{self._tailscale_command}")
                    self._set(State.RECONNECTING if self._state == State.ONLINE else State.CONNECTING, msg)
                    if time.monotonic() > deadline:
                        self._set(State.FAILED, msg + " (Funnel also has to be enabled for your Tailscale account.)")
            if self._wait(max(self.poll, 0.05) * 3):
                return

    def _on_helper_progress(self, done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        self._helper = {"phase": "downloading", "percent": pct}
        if pct % 5 == 0 or pct == 100:  # update (and log) in steps, not on every percent
            self._set(State.CONNECTING, f"Downloading the sharing helper (first time only)… {pct}%")

    def _run_quick(self) -> None:
        self._set(State.CONNECTING, "Preparing the sharing helper…")
        try:
            binary = self.downloader.ensure(self._on_helper_progress)
        except HelperError as e:
            self._helper = {"phase": "failed", "percent": 0}
            self._set(State.FAILED, str(e))
            return
        self._helper = {"phase": "ready", "percent": 100}
        delays = [2, 5, 10, 30]
        failures = 0
        first = True
        while not self._stop.is_set():
            self._set(State.CONNECTING if first else State.RECONNECTING,
                      "Opening a temporary public address…" if first else "Reconnecting with a new temporary address…")
            tunnel = self.tunnel_factory(binary, self.ctx.settings.share_port, self._bin_dir / "tunnel")
            self._tunnel = tunnel
            tunnel.start()
            # 1. the helper asks for a temporary address
            self._until(lambda: tunnel.url or not tunnel.alive(), self.address_timeout)
            url = tunnel.url
            # 2. the helper connects that address to the internet (reported by the helper itself, no DNS involved)
            connected = False
            if url:
                self._set(State.CONNECTING if first else State.RECONNECTING, "Got an address. Connecting it to the internet…")
                self._until(lambda: tunnel.ready() or not tunnel.alive(), self.edge_timeout)
                connected = bool(tunnel.alive() and tunnel.ready())
            if not connected:
                detail = (tunnel.recent[-1] if getattr(tunnel, "recent", None) else "").strip()
                tunnel.stop()
                self._tunnel = None
                if self._stop.is_set():
                    return
                failures += 1
                if failures > len(delays):
                    self._set(State.FAILED, "Couldn't open a temporary address. Your network may be blocking it, or the free service "
                              "may be down. Check your internet connection, or choose another method. "
                              + (f"Last message: {detail[:160]}" if detail else ""))
                    return
                self._set(State.RECONNECTING, "The temporary address didn't connect. Trying again…")
                if self._wait(delays[failures - 1]):
                    return
                first = False
                continue
            failures, first = 0, False
            # 3. a short check from this computer. It is NOT required: this computer's own DNS can be slow to learn a
            #    brand-new name, and that must not keep the owner waiting. The result is shown honestly instead.
            self._set(State.CONNECTING, "Connected. Checking the link…")
            self._wait(self.settle)
            verified = bool(self._until(lambda: self._healthy(url), self.check_window, interval=3.0))
            self._go_online(url, VERIFIED_MSG if verified else UNVERIFIED_MSG, verified=verified)
            bad = 0
            while not self._stop.is_set():
                if self._wait(self.health_every):
                    break
                if not tunnel.alive():
                    self._set(State.RECONNECTING, "The sharing helper stopped. Reconnecting…")
                    break
                if self._healthy(url):
                    if not self._verified or bad:
                        bad = 0
                        self._go_online(url, VERIFIED_MSG, verified=True)
                    continue
                if not self._verified:
                    continue  # never confirmed from here; the helper is still connected, so leave it as is
                bad += 1
                self._set(State.RECONNECTING, "Connection lost. Checking again…")
                if bad >= 3:
                    break
            tunnel.stop()
            self._tunnel = None
