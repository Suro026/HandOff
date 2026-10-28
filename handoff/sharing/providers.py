"""Small pieces the connection manager uses: the Quick Share tunnel process, LAN detection, Tailscale detection."""
from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("handoff.sharing")

_QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class QuickTunnel:
    """Runs `cloudflared tunnel --url http://127.0.0.1:PORT` and reads the temporary address from its output.

    It only ever points at the share service. The owner dashboard is never given to a tunnel.
    """

    def __init__(self, binary: Path, local_port: int, work_dir: Path):
        self.binary = Path(binary)
        self.local_port = local_port
        self.work_dir = Path(work_dir)
        self.url: str | None = None
        self.exit_code: int | None = None
        self.registered = 0  # tunnel connections the helper reports as established with the provider
        self._proc: subprocess.Popen | None = None
        self.recent: list[str] = []

    def start(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # An empty config file keeps a user's own cloudflared setup from interfering with a quick tunnel.
        empty = self.work_dir / "empty-config.yml"
        empty.write_text("")
        # http2 (TCP) rather than the default QUIC (UDP): many home and office networks block UDP, which would leave
        # the tunnel stuck connecting for a long time.
        cmd = [str(self.binary), "--config", str(empty), "tunnel", "--url", f"http://127.0.0.1:{self.local_port}",
               "--no-autoupdate", "--protocol", "http2"]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, errors="replace", creationflags=_NO_WINDOW,
        )
        threading.Thread(target=self._read, daemon=True, name="quick-tunnel-reader").start()

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.rstrip()
            if line:
                log.info("helper: %s", line[:300])  # kept in the log so a slow or failed connection can be diagnosed
            self.recent = (self.recent + [line])[-30:]
            if "Registered tunnel connection" in line:
                self.registered += 1
            if self.url is None:
                m = _QUICK_URL.search(line)
                if m and "api.trycloudflare.com" not in m.group(0):
                    self.url = m.group(0)
        self.exit_code = self._proc.wait()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ready(self) -> bool:
        """True once the helper says at least one connection to the provider is established."""
        return self.alive() and self.registered >= 1

    def stop(self) -> None:
        p = self._proc
        if not p or p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)


def detect_lan_ip() -> str:
    """The address other devices on this network would use. Opening a UDP socket sends no packets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def normalize_custom_url(raw: str) -> str:
    """Accept an address you control, such as https://files.example.com. Reject anything that is not a plain origin."""
    url = (raw or "").strip().rstrip("/")
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter an address that starts with https:// (or http://), for example https://files.example.com")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("Use just the address, with no path, password or extra parts.")
    return f"{parts.scheme}://{parts.netloc.lower()}"


def _tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in (r"C:\Program Files\Tailscale\tailscale.exe", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if Path(candidate).exists():
            return candidate
    return None


def tailscale_info() -> dict:
    """Read-only. Handoff never changes Tailscale's settings; it only reads status and tells the owner what to run."""
    exe = _tailscale_exe()
    if not exe:
        return {"installed": False}
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"installed": True, "running": False}
    name = ((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
    return {"installed": True, "running": data.get("BackendState") == "Running", "dns_name": name or None}
