import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from handoff import desktop
from handoff.context import build_context
from handoff.desktop import InstanceLock, ServiceRunner, app_home, desktop_settings, pick_port


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def refused(port) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def test_app_home_follows_each_operating_systems_convention(monkeypatch, tmp_path):
    monkeypatch.delenv("HANDOFF_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert app_home() == tmp_path / "local" / "Handoff"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert app_home().parts[-3:] == ("Library", "Application Support", "Handoff")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert app_home() == tmp_path / "xdg" / "handoff"
    monkeypatch.setenv("HANDOFF_HOME", str(tmp_path / "custom"))
    assert app_home() == tmp_path / "custom"


def test_pick_port_falls_back_when_the_preferred_port_is_busy():
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        other = pick_port(port)
        assert other != port and 0 < other < 65536
    finally:
        busy.close()


def test_only_one_instance_can_hold_the_lock():
    port = free_port()
    a, b = InstanceLock(port), InstanceLock(port)
    assert a.acquire() is True
    assert b.acquire() is False
    a.release()
    assert b.acquire() is True
    b.release()


def test_desktop_settings_keep_keys_outside_the_data_folder(tmp_path):
    s = desktop_settings(tmp_path, 8080, 8081)
    assert s.key_dir == tmp_path / "keys" and not s.key_dir.is_relative_to(s.data_dir)
    assert s.owner_bind == "127.0.0.1"  # the dashboard never listens beyond this computer


def test_service_runner_starts_both_services_rebinds_and_stops_cleanly(tmp_path):
    s = desktop_settings(tmp_path, free_port(), free_port())
    ctx = build_context(s, gate_sharing=True)
    runner = ServiceRunner(ctx)
    ctx.share_bind_hook = runner.set_share_bind
    runner.start()
    try:
        assert get(f"http://127.0.0.1:{s.owner_port}/api/auth/session")[0] == 200
        health = json.loads(get(f"http://127.0.0.1:{s.share_port}/healthz")[1])
        assert health["instance"] == ctx.instance_id
        assert runner.share_bind == "127.0.0.1"
        ctx.share_bind_hook("0.0.0.0")  # switching to same-Wi-Fi sharing opens the listener to the network
        assert runner.share_bind == "0.0.0.0"
        assert get(f"http://127.0.0.1:{s.share_port}/healthz")[0] == 200
        ctx.share_bind_hook("127.0.0.1")
        assert runner.share_bind == "127.0.0.1"
        assert get(f"http://127.0.0.1:{s.share_port}/healthz")[0] == 200
    finally:
        runner.stop()
    assert refused(s.owner_port) and refused(s.share_port)


def test_visitors_arriving_through_a_local_tunnel_are_not_mistaken_for_other_computers(tmp_path):
    """A local tunnel connects from 127.0.0.1 and passes the visitor's address in X-Forwarded-For. A server that rewrites
    the client address from that header makes every visitor look like another computer, so Handoff would refuse them all.
    This goes through the real server, which the in-process test clients do not."""
    s = desktop_settings(tmp_path, free_port(), free_port())
    ctx = build_context(s, gate_sharing=True)
    ctx.manager._provider, ctx.manager._wanted = "quick", True  # as while Quick Share is on
    runner = ServiceRunner(ctx)
    runner.start()
    try:
        forwarded = {"X-Forwarded-For": "203.0.113.9", "CF-Connecting-IP": "203.0.113.9"}
        req = urllib.request.Request(f"http://127.0.0.1:{s.share_port}/healthz", headers=forwarded)
        assert urllib.request.urlopen(req, timeout=5).status == 200
        with pytest.raises(urllib.error.HTTPError) as unknown:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{s.share_port}/s/nope", headers=forwarded), timeout=5)
        assert unknown.value.code == 404  # the normal "no longer active" page, not a refusal
    finally:
        runner.stop()


def _api(opener, base, method, path, body=None, csrf=None):
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with opener.open(req, timeout=5) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def test_desktop_program_starts_by_itself_shows_status_and_quits_from_the_dashboard(tmp_path):
    home = tmp_path / "home"
    env = {**os.environ, "HANDOFF_HOME": str(home), "HANDOFF_LOCK_PORT": str(free_port())}
    cmd = [sys.executable, "-m", "handoff", "desktop", "--no-browser", "--no-tray"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        run_file = home / "run.json"
        deadline = time.time() + 25
        while time.time() < deadline and not run_file.exists():
            assert proc.poll() is None, proc.stdout.read()
            time.sleep(0.2)
        info = json.loads(run_file.read_text())
        base = f"http://127.0.0.1:{info['owner_port']}"
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        # no terminal-style setup: first run goes straight to creating the owner account
        assert _api(opener, base, "GET", "/api/auth/session")["setup_needed"] is True
        csrf = _api(opener, base, "POST", "/api/setup", {"username": "owner", "password": "a-long-password"})["csrf"]
        status = _api(opener, base, "GET", "/api/sharing", csrf=csrf)
        assert status["managed"] is True and status["state"] == "offline" and status["message"]

        # starting a second copy just points at the first
        second = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
        assert second.returncode == 0 and "already running" in second.stdout

        # data and keys live where the app says, keys outside the data folder
        assert (home / "data" / "db" / "handoff.sqlite3").exists()
        assert not (home / "data" / "keys").exists()

        # Quit works from the dashboard and leaves nothing running
        assert _api(opener, base, "POST", "/api/app/quit", {}, csrf=csrf)["ok"] is True
        assert proc.wait(timeout=20) == 0
        assert not run_file.exists()
        assert refused(info["owner_port"]) and refused(info["share_port"])
    finally:
        if proc.poll() is None:
            proc.kill()
