import hashlib
import os

from handoff.__main__ import backup, restore, verify
from handoff.security import RateLimiter, hash_password, verify_password
from handoff.serve import parse_range
from handoff.storage import file_path

from .conftest import PNG, PASSWORD, make_env, make_link, sign_in, upload


# ---------------------------------------------------------------- uploads & integrity
def test_upload_preserves_bytes_and_hash(env, project):
    data = os.urandom(3 * 1024 * 1024 + 17)
    r = upload(env, project, "master.bin", data)
    assert r.status_code == 201
    body = r.json()
    assert body["size"] == len(data)
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    stored = file_path(env.settings, project, body["id"]).read_bytes()
    assert stored == data  # byte-for-byte identical, nothing re-encoded


def test_streamed_upload_without_content_length(env, project):
    chunks = [os.urandom(100_000) for _ in range(5)]

    def gen():
        yield from chunks

    r = env.owner.put(f"/api/projects/{project}/files", params={"name": "streamed.bin"}, content=gen())
    assert r.status_code == 201
    assert r.json()["sha256"] == hashlib.sha256(b"".join(chunks)).hexdigest()
    assert list(env.settings.incoming_dir.glob("*.part")) == []


def test_disk_reserve_refuses_and_cleans_up(env, project):
    env.settings.min_free_bytes = 10**18
    r = upload(env, project, "big.bin", b"x" * 1000)
    assert r.status_code == 507
    assert list(env.settings.incoming_dir.glob("*")) == []
    assert env.owner.get(f"/api/projects/{project}").json()["files"] == []


def test_optional_cap_is_enforced_and_cleans_up(env, project):
    env.settings.max_upload_bytes = 1000
    r = upload(env, project, "big.bin", b"x" * 5000)
    assert r.status_code == 413
    assert list(env.settings.incoming_dir.glob("*")) == []
    assert env.owner.get(f"/api/projects/{project}").json()["files"] == []


def test_filename_never_becomes_a_path(env, project):
    r = upload(env, project, "../../evil.txt", b"hello")
    assert r.status_code == 201
    assert "/" not in r.json()["name"] and "\\" not in r.json()["name"]
    outside = [p for p in env.settings.data_dir.rglob("*") if p.is_file() and "evil" in p.name]
    assert outside == []


def test_upload_requires_login_and_csrf(env, project):
    from fastapi.testclient import TestClient
    from handoff.owner_app import create_owner_app

    anon = TestClient(create_owner_app(env.ctx), base_url="http://localhost")
    assert anon.put(f"/api/projects/{project}/files", params={"name": "a"}, content=b"x").status_code == 401
    no_csrf = env.owner.headers.pop("X-CSRF-Token")
    assert upload(env, project, "a", b"x").status_code == 403
    env.owner.headers["X-CSRF-Token"] = no_csrf


# ---------------------------------------------------------------- share links: download & range
def test_download_returns_identical_bytes_with_range_support(env, project):
    data = os.urandom(50_000)
    fid = upload(env, project, "clip.bin", data).json()["id"]
    token = make_link(env, project)["token"]
    base = f"/s/{token}/files/{fid}/download"

    full = env.share.get(base)
    assert full.status_code == 200 and full.content == data
    assert full.headers["accept-ranges"] == "bytes"
    assert "attachment" in full.headers["content-disposition"]

    part = env.share.get(base, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == data[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(data)}"

    tail = env.share.get(base, headers={"Range": "bytes=-5"})
    assert tail.status_code == 206 and tail.content == data[-5:]

    open_end = env.share.get(base, headers={"Range": "bytes=49990-"})
    assert open_end.status_code == 206 and open_end.content == data[49990:]

    bad = env.share.get(base, headers={"Range": "bytes=999999999-"})
    assert bad.status_code == 416 and bad.headers["content-range"] == f"bytes */{len(data)}"


def test_parse_range_edge_cases():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-0", 100) == (0, 0)
    assert parse_range("bytes=90-200", 100) == (90, 99)
    assert parse_range("bytes=5-2", 100) == "invalid"
    assert parse_range("bytes=0-1,5-6", 100) is None  # multi-range served as whole file
    assert parse_range("items=0-1", 100) is None
    assert parse_range("bytes=-0", 100) == "invalid"


def test_page_view_does_not_use_up_downloads(env, project):
    fid = upload(env, project, "a.bin", b"abc").json()["id"]
    link = make_link(env, project, max_downloads=1)
    token = link["token"]
    for _ in range(3):
        assert env.share.get(f"/s/{token}").status_code == 200
    assert env.share.get(f"/s/{token}/files/{fid}/download", headers={"Range": "bytes=0-0"}).status_code == 206
    first = env.share.get(f"/s/{token}/files/{fid}/download")
    assert first.status_code == 200
    second = env.share.get(f"/s/{token}/files/{fid}/download")
    assert second.status_code == 410


# ---------------------------------------------------------------- view-only
def test_view_only_blocks_download_but_allows_preview(env, project):
    pid = upload(env, project, "pic.png", PNG).json()["id"]
    bid = upload(env, project, "design.bin", os.urandom(500)).json()["id"]
    token = make_link(env, project, access="view_only")["token"]

    page = env.share.get(f"/s/{token}")
    assert page.status_code == 200
    assert "Download" not in page.text and "download" not in page.text.lower().replace("downloads", "")
    # A view-only page is just the document: no hash, no file type, no warning boxes. The limits are explained to the
    # owner when the link is created, not shown to the client.
    assert "SHA-256" not in page.text and "image/png" not in page.text and "cannot stop copying" not in page.text
    assert 'draggable="false"' in page.text  # no long-press "save image" on phones

    assert env.share.get(f"/s/{token}/files/{pid}/download").status_code == 403
    raw = env.share.get(f"/s/{token}/files/{pid}/raw")
    assert raw.status_code == 200 and raw.content == PNG
    assert raw.headers["content-type"] == "image/png"
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert env.share.get(f"/s/{token}/files/{bid}/raw").status_code == 404  # not previewable, so not viewable
    assert env.share.get(f"/s/{token}/files/{bid}/download").status_code == 403


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" \
      b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def test_view_only_pdf_uses_the_bundled_viewer_not_the_browsers_own(env, project):
    fid = upload(env, project, "report.pdf", PDF).json()["id"]
    token = make_link(env, project, access="view_only")["token"]
    page = env.share.get(f"/s/{token}").text
    assert f'data-src="/s/{token}/files/{fid}/raw"' in page and "<iframe" not in page  # no browser PDF toolbar
    assert "/static/pdfview.js" in page
    for asset in ("/static/pdfview.js", "/static/pdfjs/pdf.min.mjs", "/static/pdfjs/pdf.worker.min.mjs"):
        r = env.share.get(asset)
        assert r.status_code == 200
    assert env.share.get("/static/pdfjs/pdf.min.mjs").headers["content-type"].startswith("text/javascript")  # required for modules
    csp = env.share.get(f"/s/{token}").headers["content-security-policy"]
    assert "worker-src 'self' blob:" in csp and "script-src" not in csp  # scripts stay same-origin only
    assert env.share.get(f"/s/{token}/files/{fid}/download").status_code == 403


def test_download_page_is_short_and_keeps_file_details_folded_away(env, project):
    upload(env, project, "report.pdf", PDF)
    token = make_link(env, project)["token"]
    page = env.share.get(f"/s/{token}").text
    assert ">Download<" in page and "<iframe" in page  # a download link may use the browser's own viewer
    assert "<details class=\"preview\" open>" in page  # a single document opens straight away
    assert "File details" in page


def test_view_only_rejects_download_limit(env, project):
    r = env.owner.post(f"/api/projects/{project}/links", json={"access": "view_only", "max_downloads": 2})
    assert r.status_code == 400


# ---------------------------------------------------------------- revoke, expiry, password, scope
def test_revoked_expired_and_unknown_links_look_identical(env, project):
    upload(env, project, "a.bin", b"abc")
    a = make_link(env, project)
    b = make_link(env, project)
    assert env.share.get(f"/s/{a['token']}").status_code == 200
    assert env.owner.delete(f"/api/links/{a['id']}").status_code == 204
    env.ctx.db.execute("UPDATE share_links SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (b["id"],))
    revoked, expired, unknown = (env.share.get(f"/s/{t}") for t in (a["token"], b["token"], "nope" * 10))
    assert revoked.status_code == expired.status_code == unknown.status_code == 404
    assert revoked.text == expired.text == unknown.text


def test_password_gate(env, project):
    fid = upload(env, project, "a.bin", b"secret-bytes").json()["id"]
    token = make_link(env, project, password="hunter22")["token"]
    assert "Enter the password" in env.share.get(f"/s/{token}").text
    assert env.share.get(f"/s/{token}/files/{fid}/download").status_code == 401
    wrong = env.share.post(f"/s/{token}/unlock", content="password=nope", headers={"content-type": "application/x-www-form-urlencoded"})
    assert wrong.status_code == 401
    ok = env.share.post(f"/s/{token}/unlock", content="password=hunter22",
                        headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert ok.status_code == 303
    assert "a.bin" in env.share.get(f"/s/{token}").text
    assert env.share.get(f"/s/{token}/files/{fid}/download").content == b"secret-bytes"


def test_link_scoped_to_chosen_files(env, project):
    a = upload(env, project, "a.bin", b"AAA").json()["id"]
    b = upload(env, project, "b.bin", b"BBB").json()["id"]
    token = make_link(env, project, scope="files", file_ids=[a])["token"]
    page = env.share.get(f"/s/{token}").text
    assert "a.bin" in page and "b.bin" not in page
    assert env.share.get(f"/s/{token}/files/{a}/download").status_code == 200
    assert env.share.get(f"/s/{token}/files/{b}/download").status_code == 404


def test_token_is_stored_only_as_a_hash(env, project):
    token = make_link(env, project)["token"]
    rows = env.ctx.db.query("SELECT token_hash FROM share_links")
    assert token not in [r["token_hash"] for r in rows]
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- safe previews
def test_html_and_svg_are_never_rendered_inline(env, project):
    html = b"<html><script>alert(1)</script></html>"
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
    token = make_link(env, project)["token"]
    for name, data in (("page.html", html), ("logo.svg", svg)):
        fid = upload(env, project, name, data).json()["id"]
        r = env.share.get(f"/s/{token}/files/{fid}/raw")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert "sandbox" in r.headers["content-security-policy"]


# ---------------------------------------------------------------- separation of surfaces
def test_share_app_exposes_no_owner_routes(env, project):
    assert env.share.get("/api/projects").status_code == 404
    assert env.share.get("/api/auth/session").status_code == 404
    assert env.share.put(f"/api/projects/{project}/files", params={"name": "x"}, content=b"x").status_code in (404, 405)
    health = env.share.get("/healthz").json()
    assert health["ok"] is True and health["instance"] == env.ctx.instance_id


def test_owner_app_rejects_foreign_host_and_cross_origin_writes(env):
    assert env.owner.get("/api/auth/session", headers={"Host": "evil.example"}).status_code == 400
    r = env.owner.post("/api/projects", json={"title": "x"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_owner_endpoints_require_login(tmp_path):
    e = make_env(tmp_path)
    assert e.owner.get("/api/projects").status_code == 401
    assert e.owner.get("/api/auth/session").json()["setup_needed"] is True


def test_setup_only_works_once(env):
    r = env.owner.post("/api/setup", json={"username": "second", "password": PASSWORD})
    assert r.status_code == 409


# ---------------------------------------------------------------- backup, restore, verify
def test_backup_restore_roundtrip_keeps_links_working(env, project, tmp_path):
    data = os.urandom(20_000)
    fid = upload(env, project, "keep.bin", data).json()["id"]
    token = make_link(env, project)["token"]

    dest = tmp_path / "backup"
    assert backup(env.settings, dest) == 0
    manifest = (dest / "MANIFEST.sha256").read_text()
    assert hashlib.sha256(data).hexdigest() in manifest

    fresh = make_env(tmp_path, name="restored")  # empty install
    fresh.settings.db_path.unlink()
    for ext in ("-wal", "-shm"):
        (fresh.settings.db_path.parent / f"handoff.sqlite3{ext}").unlink(missing_ok=True)
    assert restore(fresh.settings, dest, force=False) == 0
    assert verify(fresh.settings, fix=False) == 0

    again = make_env(tmp_path, name="restored")
    r = again.share.get(f"/s/{token}/files/{fid}/download")
    assert r.status_code == 200 and r.content == data


def test_db_only_backup_skips_file_copy_but_writes_manifest(env, project, tmp_path):
    data = os.urandom(5000)
    upload(env, project, "a.bin", data)
    dest = tmp_path / "dbonly"
    assert backup(env.settings, dest, db_only=True) == 0
    assert (dest / "db" / "handoff.sqlite3").exists()
    assert not (dest / "files").exists()
    assert hashlib.sha256(data).hexdigest() in (dest / "MANIFEST.sha256").read_text()


def test_restore_refuses_to_overwrite_without_force(env, project, tmp_path):
    dest = tmp_path / "b"
    backup(env.settings, dest)
    assert restore(env.settings, dest, force=False) == 2


def test_verify_detects_corruption(env, project):
    fid = upload(env, project, "a.bin", b"original").json()["id"]
    file_path(env.settings, project, fid).write_bytes(b"tampered")
    assert verify(env.settings, fix=False) == 1


def test_missing_file_is_reconciled_at_startup(env, project, tmp_path):
    fid = upload(env, project, "a.bin", b"abc").json()["id"]
    file_path(env.settings, project, fid).unlink()
    from handoff.context import startup_housekeeping

    assert startup_housekeeping(env.ctx)["missing"] == 1
    token = make_link(env, project)["token"]
    assert "a.bin" not in env.share.get(f"/s/{token}").text


# ---------------------------------------------------------------- primitives
def test_password_hashing_and_rate_limit():
    h = hash_password("s3cret-value")
    assert verify_password("s3cret-value", h) and not verify_password("other", h)
    rl = RateLimiter(2, 60)
    assert rl.allow("k") and rl.allow("k") and not rl.allow("k") and rl.allow("other")
