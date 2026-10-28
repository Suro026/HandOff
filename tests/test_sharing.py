"""Connection manager tests. Tunnel, download and network checks are replaced by fakes; the real ones are exercised by
the live checks documented in the README, not by this suite."""
import hashlib
import os
import threading
import time

import pytest

from handoff.sharing.binaries import HelperDownloader, HelperError
from handoff.sharing.manager import ConnectionManager, ConsentRequired, SharingError, State
from handoff.sharing.providers import normalize_custom_url

from .conftest import make_env, make_link, sign_in, upload


class FakeTunnel:
    made: list = []
    connects = True  # does the helper manage to connect the address to the internet?

    def __init__(self, binary, port, work):
        self.port, self.url, self._alive, self.recent = port, None, False, []
        self.n = len(FakeTunnel.made)
        FakeTunnel.made.append(self)

    def start(self):
        self._alive = True
        self.url = f"https://fake-{self.n}.trycloudflare.com"

    def alive(self):
        return self._alive

    def ready(self):
        return self._alive and FakeTunnel.connects

    def stop(self):
        self._alive = False


class FakeDownloader:
    def ensure(self, progress=None):
        if progress:
            progress(5, 10)
        return "fake-binary"


class Health:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def __call__(self, base, instance):
        self.calls.append(base)
        return self.ok() if callable(self.ok) else self.ok


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _reset_fake_tunnels():
    FakeTunnel.made = []
    FakeTunnel.connects = True


def desktop_env(tmp_path, health=None, **mgr_kwargs):
    health = health or Health()
    defaults = dict(downloader=FakeDownloader(), health_check=health, tunnel_factory=FakeTunnel,
                    lan_ip=lambda: "192.168.1.20", poll=0.02, health_every=0.05, connect_timeout=1.0,
                    address_timeout=1.0, edge_timeout=1.0, settle=0.01, check_window=0.5)
    defaults.update(mgr_kwargs)
    # The share client connects from this computer, like a local tunnel process would.
    env = make_env(tmp_path, gate=True, manager=lambda ctx: ConnectionManager(ctx, gate=True, **defaults),
                   share_client={"client": ("127.0.0.1", 50000)})
    sign_in(env)
    env.health = health
    env.mgr = env.ctx.manager
    return env


# ------------------------------------------------------------------ Quick Share
def test_quick_share_requires_consent_then_goes_online_with_a_temporary_address(tmp_path):
    env = desktop_env(tmp_path)
    with pytest.raises(ConsentRequired):
        env.mgr.start("quick")
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    st = env.mgr.status()
    assert st["base_url"] == "https://fake-0.trycloudflare.com" and st["temporary"] is True
    assert st["provider_label"] == "Quick Share (temporary)"
    assert "temporary" in st["message"] and "changes" in st["message"]
    assert env.mgr.tunnel_active
    env.mgr.stop()


def test_consent_is_remembered_and_api_asks_for_it_first(tmp_path):
    env = desktop_env(tmp_path)
    r = env.owner.post("/api/sharing/start", json={"provider": "quick"})
    assert r.status_code == 409 and r.json()["code"] == "consent_required"
    assert "testing and development" in r.json()["terms"]  # the real limits are shown before anything is downloaded
    ok = env.owner.post("/api/sharing/start", json={"provider": "quick", "accept_quick_terms": True})
    assert ok.status_code == 200
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    assert env.mgr.quick_consented()
    env.owner.post("/api/sharing/stop")


def test_link_uses_the_real_public_address_and_cannot_be_made_before_sharing_is_online(tmp_path):
    env = desktop_env(tmp_path)
    pid = env.owner.post("/api/projects", json={"title": "P"}).json()["id"]
    early = env.owner.post(f"/api/projects/{pid}/links", json={})
    assert early.status_code == 409 and "Start sharing" in early.json()["detail"]
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    made = make_link(env, pid)
    assert made["url"].startswith("https://fake-0.trycloudflare.com/s/")
    assert made["temporary"] is True and made["provider"] == "quick"
    env.mgr.stop()


def test_stop_sharing_stops_the_tunnel_and_pauses_the_share_service(tmp_path):
    env = desktop_env(tmp_path)
    pid = env.owner.post("/api/projects", json={"title": "P"}).json()["id"]
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    token = make_link(env, pid)["token"]
    assert env.share.get(f"/s/{token}").status_code == 200
    tunnel = FakeTunnel.made[-1]
    assert env.owner.post("/api/sharing/stop").json()["state"] == "offline"
    assert not tunnel.alive()
    paused = env.share.get(f"/s/{token}")
    assert paused.status_code == 503 and "Sharing is paused" in paused.text
    assert env.share.get("/healthz").status_code == 200  # the service itself is fine; only visitors are refused
    assert env.mgr.status()["base_url"] is None


def test_lost_tunnel_reconnects_with_a_new_address_and_old_links_can_be_copied_again(tmp_path):
    env = desktop_env(tmp_path)
    pid = env.owner.post("/api/projects", json={"title": "P"}).json()["id"]
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    link = make_link(env, pid)
    assert link["url"].startswith("https://fake-0.")
    FakeTunnel.made[0]._alive = False  # the helper process dies
    assert wait_for(lambda: env.mgr.status()["base_url"] == "https://fake-1.trycloudflare.com"
                    and env.mgr.status()["state"] == "online", timeout=8)
    st = env.mgr.status()
    assert st["address_changed"] is True
    copied = env.owner.get(f"/api/links/{link['id']}/url").json()["url"]
    assert copied == f"https://fake-1.trycloudflare.com/s/{link['token']}"  # same secret, new address
    env.owner.post("/api/sharing/dismiss-address-change")
    assert env.mgr.status()["address_changed"] is False
    env.mgr.stop()


def test_failed_self_check_shows_reconnecting_then_recovers(tmp_path):
    flag = {"ok": True}
    env = desktop_env(tmp_path, health=Health(lambda: flag["ok"]))
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    flag["ok"] = False
    assert wait_for(lambda: env.mgr.status()["state"] == "reconnecting")
    flag["ok"] = True
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    env.mgr.stop()


def test_slow_self_check_never_blocks_for_long_and_is_reported_honestly(tmp_path):
    """This computer's own lookup of a brand-new address can be slow. The owner must not wait minutes for it, and must
    be told plainly that the link was not confirmed from here."""
    flag = {"ok": False}
    env = desktop_env(tmp_path, health=Health(lambda: flag["ok"]))
    started = time.time()
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online", timeout=5)
    assert time.time() - started < 4
    st = env.mgr.status()
    assert st["verified"] is False and "couldn't confirm" in st["message"] and "mobile data" in st["message"]
    assert st["base_url"] == "https://fake-0.trycloudflare.com"
    flag["ok"] = True  # later the check passes, and the status says so
    assert wait_for(lambda: env.mgr.status()["verified"] is True, timeout=5)
    assert "couldn't confirm" not in env.mgr.status()["message"]
    env.mgr.stop()


def test_not_online_until_the_helper_reports_it_connected_to_the_internet(tmp_path):
    FakeTunnel.connects = False
    env = desktop_env(tmp_path, edge_timeout=5.0)
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: "Connecting it to the internet" in env.mgr.status()["message"])
    time.sleep(0.3)
    assert env.mgr.status()["state"] == "connecting" and env.mgr.status()["base_url"] is None
    FakeTunnel.connects = True
    assert wait_for(lambda: env.mgr.status()["state"] == "online", timeout=5)
    env.mgr.stop()


def test_helper_that_never_connects_is_restarted_not_waited_on_forever(tmp_path):
    FakeTunnel.connects = False
    env = desktop_env(tmp_path, edge_timeout=0.3)
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: len(FakeTunnel.made) >= 2 and "didn't connect" in env.mgr.status()["message"] or len(FakeTunnel.made) >= 2, timeout=8)
    assert env.mgr.status()["state"] in ("reconnecting", "connecting")
    env.mgr.stop()


def test_real_tunnel_process_wrapper_reads_address_and_connection_from_helper_output(tmp_path):
    """Runs a stand-in program that prints what cloudflared prints. No network is used."""
    import sys
    from handoff.sharing.providers import QuickTunnel

    script = tmp_path / "fake_cloudflared.py"
    script.write_text(
        "import sys, time, pathlib\n"
        f"pathlib.Path(r'{tmp_path / 'argv.txt'}').write_text(' '.join(sys.argv[1:]))\n"
        "print('INF Requesting new quick Tunnel on https://api.trycloudflare.com ...', flush=True)\n"
        "print('INF |  https://random-words-here.trycloudflare.com  |', flush=True)\n"
        "time.sleep(0.3)\n"
        "print('INF Registered tunnel connection connIndex=0 location=xyz protocol=http2', flush=True)\n"
        "time.sleep(30)\n"
    )
    if sys.platform == "win32":
        launcher = tmp_path / "fake_cloudflared.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n')
    else:
        launcher = tmp_path / "fake_cloudflared.sh"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    t = QuickTunnel(launcher, 8123, tmp_path / "work")
    t.start()
    try:
        assert wait_for(lambda: t.url is not None, timeout=10)
        assert t.url == "https://random-words-here.trycloudflare.com"  # not the api.trycloudflare.com address
        assert t.ready() is False or t.registered >= 1
        assert wait_for(t.ready, timeout=10) and t.registered == 1
        argv = (tmp_path / "argv.txt").read_text()
        assert "--url http://127.0.0.1:8123" in argv and "--protocol http2" in argv and "--no-autoupdate" in argv
    finally:
        t.stop()
    assert wait_for(lambda: not t.alive(), timeout=10)


def test_helper_failure_is_reported_in_plain_words(tmp_path):
    class Broken:
        def ensure(self, progress=None):
            raise HelperError("Download failed. Check your internet connection.")

    env = desktop_env(tmp_path, downloader=Broken())
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "failed")
    assert "internet connection" in env.mgr.status()["message"]


# ------------------------------------------------------------------ other methods
def test_same_wifi_uses_the_local_address_and_says_it_is_plain_http(tmp_path):
    env = desktop_env(tmp_path)
    env.mgr.start("lan")
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    st = env.mgr.status()
    assert st["base_url"] == f"http://192.168.1.20:{env.settings.share_port}"
    assert "Wi-Fi only" in st["message"] and "not encrypted" in st["message"]
    assert st["temporary"] is False
    env.mgr.stop()


def test_same_wifi_without_a_network_says_so(tmp_path):
    env = desktop_env(tmp_path, lan_ip=lambda: "127.0.0.1")
    env.mgr.start("lan")
    assert wait_for(lambda: env.mgr.status()["state"] == "reconnecting")
    assert "No network" in env.mgr.status()["message"]
    env.mgr.stop()


def test_custom_address_is_validated_and_must_pass_the_self_check(tmp_path):
    env = desktop_env(tmp_path)
    with pytest.raises(SharingError):
        env.mgr.start("custom", custom_url="not a url")
    env.mgr.start("custom", custom_url="https://Files.Example.com/")
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    assert env.mgr.status()["base_url"] == "https://files.example.com"
    assert "your own address" in env.mgr.status()["message"]
    env.mgr.stop()


def test_custom_address_that_is_unreachable_fails_with_advice_and_keeps_checking(tmp_path):
    flag = {"ok": False}
    env = desktop_env(tmp_path, health=Health(lambda: flag["ok"]), connect_timeout=0.2)
    env.mgr.start("custom", custom_url="https://files.example.com")
    assert wait_for(lambda: env.mgr.status()["state"] == "failed")
    assert "can't reach" in env.mgr.status()["message"] and str(env.settings.share_port) in env.mgr.status()["message"]
    flag["ok"] = True
    assert wait_for(lambda: env.mgr.status()["state"] == "online", timeout=8)
    env.mgr.stop()


def test_tailscale_is_read_only_guided_and_never_required(tmp_path):
    info = {"installed": False}
    env = desktop_env(tmp_path, tailscale=lambda: info)
    env.mgr.start("tailscale")
    assert wait_for(lambda: env.mgr.status()["state"] == "failed")
    assert "isn't installed" in env.mgr.status()["message"]
    info.update(installed=True, running=True, dns_name="laptop.tail1234.ts.net")
    flag = {"ok": False}
    env.mgr.health_check = Health(lambda: flag["ok"])
    assert wait_for(lambda: "tailscale funnel --bg" in (env.mgr.status()["tailscale_command"] or ""))
    assert wait_for(lambda: "Waiting for Tailscale Funnel" in env.mgr.status()["message"])
    flag["ok"] = True
    assert wait_for(lambda: env.mgr.status()["state"] == "online", timeout=8)
    assert env.mgr.status()["base_url"] == "https://laptop.tail1234.ts.net"
    assert "do not publish" in env.mgr.status()["message"] or "does not publish" in env.mgr.status()["message"]
    env.mgr.stop()


def test_switching_methods_stops_the_previous_one(tmp_path):
    env = desktop_env(tmp_path)
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    first = FakeTunnel.made[0]
    env.mgr.start("lan")
    assert wait_for(lambda: env.mgr.status()["provider"] == "lan" and env.mgr.status()["state"] == "online")
    assert not first.alive()
    env.mgr.stop()


def test_saved_method_resumes_on_launch_only_when_no_new_permission_is_needed(tmp_path):
    env = desktop_env(tmp_path)
    env.mgr.start("lan")
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    env.mgr.stop()
    assert env.mgr.resume_saved() is True
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    env.mgr.stop()
    env.ctx.db.set_setting("sharing.provider", "tailscale")
    assert env.mgr.resume_saved() is False  # advanced methods are never started automatically


def test_server_mode_is_unchanged_and_ungated(env, project):
    assert env.ctx.manager.gate is False and env.ctx.manager.accepting() is True
    assert env.owner.post("/api/sharing/start", json={"provider": "lan"}).status_code == 409
    assert make_link(env, project)["url"].startswith(env.settings.share_base())


# ------------------------------------------------------------------ owner/desktop endpoints
def test_quit_endpoint_is_desktop_only_and_calls_the_launcher(tmp_path):
    env = desktop_env(tmp_path)
    assert env.owner.post("/api/app/quit").status_code == 409
    done = threading.Event()
    env.ctx.on_quit = done.set
    assert env.owner.post("/api/app/quit").status_code == 200
    assert done.wait(3)


def test_tunnel_peer_header_is_trusted_only_from_the_local_tunnel_process(tmp_path):
    env = desktop_env(tmp_path)
    pid = env.owner.post("/api/projects", json={"title": "P"}).json()["id"]
    env.mgr.start("quick", accept_quick_terms=True)
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    token = make_link(env, pid)["token"]
    from fastapi.testclient import TestClient
    from handoff.share_app import create_share_app

    local = TestClient(create_share_app(env.ctx), base_url="http://localhost", client=("127.0.0.1", 5000))
    remote = TestClient(create_share_app(env.ctx), base_url="http://localhost", client=("198.51.100.7", 5000))
    local.get(f"/s/{token}", headers={"cf-connecting-ip": "203.0.113.9"})
    refused = remote.get(f"/s/{token}", headers={"cf-connecting-ip": "203.0.113.50"})
    hashes = [r["ip_hash"] for r in env.ctx.db.query("SELECT ip_hash FROM access_log ORDER BY id")]
    assert hashes == [env.ctx.signer.ip_hash("203.0.113.9")]  # from the local tunnel: the real visitor address
    # With a tunnel, other computers can't reach the share service directly at all.
    assert refused.status_code == 403
    env.mgr.stop()


def test_without_a_tunnel_the_forwarded_header_is_ignored(tmp_path):
    env = desktop_env(tmp_path)
    pid = env.owner.post("/api/projects", json={"title": "P"}).json()["id"]
    env.mgr.start("custom", custom_url="https://files.example.com")
    assert wait_for(lambda: env.mgr.status()["state"] == "online")
    token = make_link(env, pid)["token"]
    from fastapi.testclient import TestClient
    from handoff.share_app import create_share_app

    remote = TestClient(create_share_app(env.ctx), base_url="http://localhost", client=("198.51.100.7", 5000))
    assert remote.get(f"/s/{token}", headers={"cf-connecting-ip": "203.0.113.50"}).status_code == 200
    row = env.ctx.db.one("SELECT ip_hash FROM access_log ORDER BY id DESC LIMIT 1")
    assert row["ip_hash"] == env.ctx.signer.ip_hash("198.51.100.7")  # a visitor can't pick their own logged address
    env.mgr.stop()


def test_pages_ask_search_engines_not_to_index(env, project):
    token = make_link(env, project)["token"]
    assert "noindex" in env.share.get(f"/s/{token}").headers["x-robots-tag"]
    assert "Disallow: /" in env.share.get("/robots.txt").text


# ------------------------------------------------------------------ helper download verification
def _downloader(tmp_path, payload, expected_sha):
    pins = {"base_url": "https://example.invalid/", "assets": {}}
    from handoff.sharing import binaries

    pins["assets"][binaries.platform_key()] = {"name": "cloudflared-test", "sha256": expected_sha, "kind": "bin"}

    class Resp:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self):
            self._p = payload

        def read(self, n):
            out, self._p = self._p[:n], self._p[n:]
            return out

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return HelperDownloader(tmp_path / "bin", pins=pins, opener=lambda url, timeout=60: Resp())


def test_helper_is_installed_only_when_its_fingerprint_matches(tmp_path):
    payload = os.urandom(1_200_000)
    d = _downloader(tmp_path, payload, hashlib.sha256(payload).hexdigest())
    path = d.ensure()
    assert path.read_bytes() == payload and d.is_installed()
    path.write_bytes(payload[:-1] + b"X")  # tampered after install
    assert d.is_installed() is False


def test_helper_with_wrong_fingerprint_is_discarded(tmp_path):
    payload = os.urandom(1_200_000)
    d = _downloader(tmp_path, payload, "0" * 64)
    with pytest.raises(HelperError, match="fingerprint"):
        d.ensure()
    assert not d.path.exists() and list((tmp_path / "bin").glob("*.part")) == []


def test_helper_download_failure_is_a_plain_message(tmp_path):
    def boom(url, timeout=60):
        raise OSError("no route")

    d = HelperDownloader(tmp_path / "bin", opener=boom)
    with pytest.raises(HelperError, match="internet connection"):
        d.ensure()


def test_pinned_hashes_are_present_for_every_supported_platform():
    import json
    from handoff.sharing.binaries import PINS_PATH

    pins = json.loads(PINS_PATH.read_text())
    assert set(pins["assets"]) >= {"windows-amd64", "linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64"}
    assert all(len(a["sha256"]) == 64 for a in pins["assets"].values())
    assert pins["base_url"].startswith("https://github.com/cloudflare/cloudflared/releases/download/")


def test_normalize_custom_url():
    assert normalize_custom_url("https://Files.Example.com/") == "https://files.example.com"
    assert normalize_custom_url("http://192.168.1.5:9000") == "http://192.168.1.5:9000"
    for bad in ("", "ftp://x.com", "https://user:pw@x.com", "https://x.com/path", "https://x.com?a=1", "x.com"):
        with pytest.raises(ValueError):
            normalize_custom_url(bad)
