"""Owner dashboard API. Bound to localhost by default. Never exposed through the share port."""
from __future__ import annotations

import hmac
import secrets
import shutil
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import anyio
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .context import Context, delete_project_files
from .db import now
from .filetypes import clean_name, preview_kind, sniff_mime
from .middleware import SecurityHeaders, client_ip
from .security import hash_password, new_token, token_hash, verify_password
from .sharing.manager import ConsentRequired, SharingError
from .storage import UploadError, file_path, stream_to_disk

STATIC = Path(__file__).parent / "static" / "owner"
SESSION_COOKIE = "hid"


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=1000)


class LoginIn(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1000)


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field("", max_length=5000)


class LinkIn(BaseModel):
    label: str = Field("", max_length=200)
    access: Literal["download", "view_only"] = "download"
    scope: Literal["project", "files"] = "project"
    file_ids: list[str] = []
    password: str | None = Field(None, min_length=6, max_length=200)
    expires_in_hours: float | None = Field(None, gt=0, le=24 * 365)
    max_downloads: int | None = Field(None, ge=1)


class SharingStartIn(BaseModel):
    provider: Literal["lan", "quick", "custom", "tailscale"]
    custom_url: str | None = Field(None, max_length=300)
    accept_quick_terms: bool = False


def _file_dict(row) -> dict:
    return {
        "id": row["id"], "name": row["original_name"], "size": row["size_bytes"], "mime": row["mime_sniffed"],
        "sha256": row["sha256"], "status": row["status"], "created_at": row["created_at"],
        "previewable": preview_kind(row["mime_sniffed"], row["size_bytes"]) is not None,
    }


def link_status(row) -> str:
    if row["revoked_at"]:
        return "revoked"
    if row["expires_at"] and row["expires_at"] <= now():
        return "expired"
    if row["max_downloads"] is not None and row["download_count"] >= row["max_downloads"]:
        return "exhausted"
    return "active"


def _link_dict(row, recoverable: bool = False) -> dict:
    return {
        "id": row["id"], "label": row["label"], "access": row["access"], "scope": row["scope"],
        "recoverable": recoverable,
        "has_password": bool(row["password_hash"]), "expires_at": row["expires_at"],
        "max_downloads": row["max_downloads"], "download_count": row["download_count"],
        "revoked_at": row["revoked_at"], "created_at": row["created_at"],
        "last_accessed_at": row["last_accessed_at"], "status": link_status(row),
    }


def create_owner_app(ctx: Context) -> FastAPI:
    s, db = ctx.settings, ctx.db
    app = FastAPI(title="Handoff owner", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SecurityHeaders,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
            "Cache-Control": "no-store",
        },
        allowed_hosts=s.owner_allowed_hosts,
    )

    # --- helpers for links and sharing ---------------------------------------
    manager = ctx.manager

    def require_sharing_online() -> None:
        """Desktop mode only: a link is only useful while Handoff is actually reachable, so insist on it."""
        if manager.gate and manager.status()["state"] != "online":
            raise HTTPException(409, "Sharing is not online yet. Start sharing first, then create or copy the link.")

    def link_url(token: str) -> str:
        return f"{manager.link_base()}/s/{token}"

    def link_context() -> dict:
        st = manager.status()
        return {
            "local_only": s.is_local_only() if not manager.gate else st["provider"] == "lan",
            "temporary": st["temporary"],
            "provider": st["provider"],
        }

    # --- auth ---------------------------------------------------------------
    def current_session(request: Request):
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid:
            return None
        row = db.one(
            "SELECT s.*, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id_hash = ?",
            (token_hash(sid),),
        )
        if not row or row["expires_at"] <= now():
            return None
        return row

    def owner_user(request: Request):
        row = current_session(request)
        if not row:
            raise HTTPException(401, "Sign in required.")
        if request.method not in ("GET", "HEAD") and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), row["csrf"]
        ):
            raise HTTPException(403, "Missing or invalid CSRF token.")
        return row

    def start_session(response: Response, user_id: int) -> str:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        expires = (datetime.now(timezone.utc) + timedelta(hours=s.session_hours)).isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO sessions (id_hash, user_id, csrf, created_at, expires_at) VALUES (?,?,?,?,?)",
            (token_hash(sid), user_id, csrf, now(), expires),
        )
        response.set_cookie(SESSION_COOKIE, sid, max_age=s.session_hours * 3600, httponly=True, samesite="strict")
        return csrf

    @app.get("/api/auth/session")
    def session_info(request: Request):
        row = current_session(request)
        has_user = db.one("SELECT 1 FROM users LIMIT 1") is not None
        return {
            "setup_needed": not has_user,
            "authenticated": bool(row),
            "username": row["username"] if row else None,
            "csrf": row["csrf"] if row else None,
            "version": __version__,
        }

    @app.post("/api/setup")
    def setup(body: Credentials, response: Response):
        with db.tx() as c:
            if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise HTTPException(409, "Setup is already complete.")
            cur = c.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                (body.username, hash_password(body.password), now()),
            )
            user_id = cur.lastrowid
        return {"csrf": start_session(response, user_id)}

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request, response: Response):
        ip = client_ip(request, s.trust_proxy_headers)
        if not ctx.login_limiter.allow(ip):
            raise HTTPException(429, "Too many sign-in attempts. Wait a few minutes and try again.")
        user = db.one("SELECT * FROM users WHERE username = ?", (body.username,))
        ok = verify_password(body.password, user["password_hash"]) if user else False
        if not user or not ok:
            raise HTTPException(401, "Wrong username or password.")
        return {"csrf": start_session(response, user["id"])}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(owner_user)):
        sid = request.cookies.get(SESSION_COOKIE, "")
        db.execute("DELETE FROM sessions WHERE id_hash = ?", (token_hash(sid),))
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    # --- projects -----------------------------------------------------------
    def project_or_404(pid: str):
        row = db.one("SELECT * FROM projects WHERE id = ? AND archived_at IS NULL", (pid,))
        if not row:
            raise HTTPException(404, "Project not found.")
        return row

    @app.get("/api/projects")
    def list_projects(user=Depends(owner_user)):
        rows = db.query(
            """SELECT p.*,
                 (SELECT COUNT(*) FROM files f WHERE f.project_id = p.id AND f.status = 'ready') AS file_count,
                 (SELECT COALESCE(SUM(size_bytes), 0) FROM files f WHERE f.project_id = p.id AND f.status = 'ready') AS total_bytes,
                 (SELECT COUNT(*) FROM share_links l WHERE l.project_id = p.id AND l.revoked_at IS NULL) AS open_links
               FROM projects p WHERE p.archived_at IS NULL ORDER BY p.created_at DESC"""
        )
        return [
            {"id": r["id"], "title": r["title"], "note": r["note"], "created_at": r["created_at"],
             "file_count": r["file_count"], "total_bytes": r["total_bytes"], "open_links": r["open_links"]}
            for r in rows
        ]

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectIn, user=Depends(owner_user)):
        pid, ts = uuid.uuid4().hex, now()
        db.execute(
            "INSERT INTO projects (id, title, note, created_at, updated_at) VALUES (?,?,?,?,?)",
            (pid, body.title.strip(), body.note, ts, ts),
        )
        return {"id": pid, "title": body.title.strip()}

    @app.get("/api/projects/{pid}")
    def get_project(pid: str, user=Depends(owner_user)):
        p = project_or_404(pid)
        files = db.query("SELECT * FROM files WHERE project_id = ? AND status != 'uploading' ORDER BY created_at", (pid,))
        links = db.query("SELECT * FROM share_links WHERE project_id = ? ORDER BY created_at DESC", (pid,))
        return {
            "id": p["id"], "title": p["title"], "note": p["note"], "created_at": p["created_at"],
            "files": [_file_dict(f) for f in files],
            "links": [_link_dict(l, ctx.keys.decrypt_token(l["token_enc"]) is not None) for l in links],
        }

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: str, user=Depends(owner_user)):
        project_or_404(pid)
        delete_project_files(ctx, pid)
        db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        return Response(status_code=204)

    # --- uploads ------------------------------------------------------------
    @app.put("/api/projects/{pid}/files", status_code=201)
    async def upload(pid: str, request: Request, name: str = Query(min_length=1, max_length=1000)):
        await anyio.to_thread.run_sync(owner_user, request)
        await anyio.to_thread.run_sync(project_or_404, pid)
        if ctx.active_uploads >= s.max_concurrent_uploads:
            raise HTTPException(429, "Too many uploads in progress. Wait for one to finish.")
        declared_len = None
        raw_len = request.headers.get("content-length")
        if raw_len and raw_len.isdigit():
            declared_len = int(raw_len)
        fid, display = uuid.uuid4().hex, clean_name(name)
        part = s.incoming_dir / f"{fid}.part"
        final = file_path(s, pid, fid)
        await anyio.to_thread.run_sync(
            db.execute,
            "INSERT INTO files (id, project_id, original_name, mime_declared, status, created_at) VALUES (?,?,?,?, 'uploading', ?)",
            (fid, pid, display, (request.headers.get("content-type") or "")[:255], now()),
        )
        ctx.active_uploads += 1
        try:
            size, sha, head = await stream_to_disk(request.stream(), s, part, final, declared_len)
        except UploadError as e:
            await anyio.to_thread.run_sync(db.execute, "DELETE FROM files WHERE id = ?", (fid,))
            return JSONResponse({"detail": e.message}, status_code=e.status)
        except BaseException:
            await anyio.to_thread.run_sync(db.execute, "DELETE FROM files WHERE id = ?", (fid,))
            raise
        finally:
            ctx.active_uploads -= 1
        mime = sniff_mime(head)
        await anyio.to_thread.run_sync(
            db.execute,
            "UPDATE files SET size_bytes = ?, sha256 = ?, mime_sniffed = ?, status = 'ready' WHERE id = ?",
            (size, sha, mime, fid),
        )
        row = await anyio.to_thread.run_sync(db.one, "SELECT * FROM files WHERE id = ?", (fid,))
        return _file_dict(row)

    @app.delete("/api/files/{fid}", status_code=204)
    def delete_file(fid: str, user=Depends(owner_user)):
        row = db.one("SELECT * FROM files WHERE id = ?", (fid,))
        if not row:
            raise HTTPException(404, "File not found.")
        file_path(s, row["project_id"], fid).unlink(missing_ok=True)
        db.execute("DELETE FROM files WHERE id = ?", (fid,))
        return Response(status_code=204)

    # --- share links ----------------------------------------------------------
    @app.post("/api/projects/{pid}/links", status_code=201)
    def create_link(pid: str, body: LinkIn, user=Depends(owner_user)):
        project_or_404(pid)
        require_sharing_online()
        if body.access == "view_only" and body.max_downloads is not None:
            raise HTTPException(400, "A download limit has no effect on a view-only link.")
        file_ids: list[str] = []
        if body.scope == "files":
            if not body.file_ids:
                raise HTTPException(400, "Choose at least one file for this link.")
            marks = ",".join("?" * len(body.file_ids))
            found = db.query(
                f"SELECT id FROM files WHERE project_id = ? AND status = 'ready' AND id IN ({marks})",
                (pid, *body.file_ids),
            )
            file_ids = [r["id"] for r in found]
            if len(file_ids) != len(set(body.file_ids)):
                raise HTTPException(400, "One or more files are not part of this project.")
        expires = None
        if body.expires_in_hours:
            expires = (datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)).isoformat(timespec="seconds")
        token, lid = new_token(), uuid.uuid4().hex
        with db.tx() as c:
            c.execute(
                """INSERT INTO share_links (id, project_id, token_hash, token_enc, label, scope, access, password_hash,
                   expires_at, max_downloads, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (lid, pid, token_hash(token), ctx.keys.encrypt_token(token), body.label.strip(), body.scope,
                 body.access, hash_password(body.password) if body.password else None, expires, body.max_downloads, now()),
            )
            for f in file_ids:
                c.execute("INSERT INTO share_link_files (link_id, file_id) VALUES (?,?)", (lid, f))
        # Visitors are looked up by hash. The secret is also stored encrypted so the owner can copy the link again
        # later, for example after a temporary public address changes.
        return {"id": lid, "token": token, "url": link_url(token), **link_context()}

    @app.get("/api/links/{lid}/url")
    def link_full_url(lid: str, user=Depends(owner_user)):
        row = db.one("SELECT * FROM share_links WHERE id = ?", (lid,))
        if not row:
            raise HTTPException(404, "Link not found.")
        if row["revoked_at"]:
            raise HTTPException(409, "This link was revoked. Create a new one.")
        require_sharing_online()
        token = ctx.keys.decrypt_token(row["token_enc"])
        if token is None:
            raise HTTPException(
                409,
                "Handoff can't show this link again (it was created before links could be copied again, or this install "
                "was restored from a backup). The link you already sent still works. Create a new link to copy one.",
            )
        return {"id": lid, "url": link_url(token), **link_context()}

    @app.delete("/api/links/{lid}", status_code=204)
    def revoke_link(lid: str, user=Depends(owner_user)):
        if not db.one("SELECT 1 FROM share_links WHERE id = ?", (lid,)):
            raise HTTPException(404, "Link not found.")
        db.execute("UPDATE share_links SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now(), lid))
        return Response(status_code=204)

    @app.get("/api/access-log")
    def access_log(project_id: str | None = None, limit: int = Query(200, ge=1, le=1000), user=Depends(owner_user)):
        sql = """SELECT a.at, a.event, l.label, l.id AS link_id, f.original_name
                 FROM access_log a JOIN share_links l ON l.id = a.link_id LEFT JOIN files f ON f.id = a.file_id"""
        params: list = []
        if project_id:
            sql += " WHERE l.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY a.id DESC LIMIT ?"
        params.append(limit)
        return [
            {"at": r["at"], "event": r["event"], "link": r["label"] or r["link_id"][:8], "file": r["original_name"]}
            for r in db.query(sql, params)
        ]

    # --- sharing connection ---------------------------------------------------
    @app.get("/api/sharing")
    def sharing_status(user=Depends(owner_user)):
        return manager.status()

    @app.post("/api/sharing/start")
    def sharing_start(body: SharingStartIn, user=Depends(owner_user)):
        if not manager.gate:
            raise HTTPException(409, "Connection methods are managed by the desktop app. In server mode, set PUBLIC_BASE_URL.")
        try:
            return manager.start(body.provider, body.custom_url, body.accept_quick_terms)
        except ConsentRequired as e:
            return JSONResponse({"detail": str(e), "code": "consent_required", "terms": str(e)}, status_code=409)
        except SharingError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/sharing/stop")
    def sharing_stop(user=Depends(owner_user)):
        return manager.stop()

    @app.post("/api/sharing/dismiss-address-change", status_code=204)
    def sharing_dismiss(user=Depends(owner_user)):
        manager.dismiss_address_change()
        return Response(status_code=204)

    @app.post("/api/app/quit")
    def quit_app(user=Depends(owner_user)):
        if ctx.on_quit is None:
            raise HTTPException(409, "Quit is only available in the desktop app.")
        threading.Timer(0.3, ctx.on_quit).start()  # let this response reach the browser first
        return {"ok": True}

    # --- diagnostics ----------------------------------------------------------
    @app.get("/api/diagnostics")
    def diagnostics(user=Depends(owner_user)):
        usage = shutil.disk_usage(s.data_dir)
        warnings = []
        if not manager.gate and s.is_local_only():
            warnings.append("Share links only work on this computer until PUBLIC_BASE_URL points somewhere clients can reach.")
        if usage.free < s.reserve_bytes():
            warnings.append("Free disk space is below the reserve. New uploads will be refused.")
        return {
            "version": __version__, "share_base": manager.link_base(), "local_only": s.is_local_only(), "desktop": manager.gate,
            "free_bytes": usage.free, "total_bytes": usage.total, "reserve_bytes": s.reserve_bytes(),
            "max_upload_bytes": s.max_upload_bytes, "warnings": warnings,
        }

    @app.post("/api/diagnostics/link-test")
    def link_test(user=Depends(owner_user)):
        url = f"{manager.link_base()}/healthz"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 (owner-configured URL)
                ok = r.status == 200
            detail = "Reachable from this computer. This does not prove clients on other networks can reach it."
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"Could not reach {url} from this computer ({type(e).__name__})."
        return {"ok": ok, "url": url, "detail": detail}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="owner-ui")
    return app
