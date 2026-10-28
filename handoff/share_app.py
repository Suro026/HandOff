"""Client share service. Exposes only /s/*, /static/* and /healthz. No owner routes and no uploads exist here."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .context import Context
from .db import now
from .filetypes import content_disposition, preview_kind
from .middleware import SecurityHeaders, client_ip
from .serve import file_response, parse_range
from .storage import file_path

import mimetypes

# Browsers refuse module scripts that aren't served as JavaScript, and some systems map .mjs to something else.
mimetypes.add_type("text/javascript", ".mjs")

HERE = Path(__file__).parent
STATIC = HERE / "static" / "share"

env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))


def _filesize(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{n} B"


def _when(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return value


env.filters["filesize"] = _filesize
env.filters["when"] = _when


def html(template: str, status: int = 200, **ctx) -> HTMLResponse:
    return HTMLResponse(env.get_template(template).render(**ctx), status_code=status)


_PAUSED_BODY = (
    b"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    b"<title>Sharing paused</title><body style='font:16px system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
    b"<h1>Sharing is paused</h1><p>The person who sent this link has stopped sharing for now. "
    b"Please contact them, or try again later.</p>"
)


class SharingGate:
    """In the desktop app the share service only answers while the owner has sharing switched on."""

    def __init__(self, app, ctx: Context):
        self.app, self.ctx = app, ctx

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http":
            peer = (scope.get("client") or ("", 0))[0]
            if not self.ctx.manager.accepts_peer(peer):
                body = b"Not available."
                await send({"type": "http.response.start", "status": 403, "headers": [
                    (b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        if scope["type"] == "http" and path.startswith("/s/") and not self.ctx.manager.accepting():
            await send({"type": "http.response.start", "status": 503, "headers": [
                (b"content-type", b"text/html; charset=utf-8"), (b"content-length", str(len(_PAUSED_BODY)).encode()),
                (b"retry-after", b"300"), (b"cache-control", b"no-store"), (b"x-robots-tag", b"noindex, nofollow"),
            ]})
            await send({"type": "http.response.body", "body": _PAUSED_BODY})
            return
        await self.app(scope, receive, send)


def create_share_app(ctx: Context) -> FastAPI:
    s, db = ctx.settings, ctx.db
    app = FastAPI(title="Handoff share", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SharingGate, ctx=ctx)
    app.add_middleware(
        SecurityHeaders,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            # blob:/data: are needed by the bundled PDF viewer for page images, fonts and its worker. Everything else is same-origin.
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; font-src 'self' blob: data:; "
                                       "worker-src 'self' blob:; frame-ancestors 'none'",
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",  # temporary public addresses have been seen in search results
        },
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def real_ip(request: Request) -> str:
        """Client address for rate limits and the log. Behind our own local tunnel process, the tunnel's header is
        trusted; otherwise forwarded headers are only trusted if the owner turned that on."""
        peer = request.client.host if request.client else ""
        if peer in ("127.0.0.1", "::1") and ctx.manager.tunnel_active:
            forwarded = request.headers.get("cf-connecting-ip")
            if forwarded:
                return forwarded.strip()
        return client_ip(request, s.trust_proxy_headers)

    def inactive(status: int = 404) -> HTMLResponse:
        # Same page for unknown, revoked and expired links, so nothing leaks about which one it was.
        return html("inactive.html", status)

    def resolve(token: str, request: Request):
        """Returns (link, ip) or (None, ip). Checks the database on every request so revocation is immediate."""
        ip = real_ip(request)
        if not ctx.lookup_limiter.allow(ip):
            return None, ip
        link = db.one("SELECT * FROM share_links WHERE token_hash = ?", (_hash(token),))
        if not link or link["revoked_at"] or (link["expires_at"] and link["expires_at"] <= now()):
            return None, ip
        return link, ip

    def unlocked(link, request: Request) -> bool:
        if not link["password_hash"]:
            return True
        return ctx.signer.check_unlock(link["id"], request.cookies.get(f"unlock-{link['id']}"))

    def visible_files(link):
        if link["scope"] == "project":
            return db.query(
                "SELECT * FROM files WHERE project_id = ? AND status = 'ready' ORDER BY created_at", (link["project_id"],)
            )
        return db.query(
            """SELECT f.* FROM files f JOIN share_link_files x ON x.file_id = f.id
               WHERE x.link_id = ? AND f.status = 'ready' ORDER BY f.created_at""",
            (link["id"],),
        )

    def find_file(link, fid: str):
        for f in visible_files(link):
            if f["id"] == fid:
                return f
        return None

    def log(link, file_id: str | None, event: str, ip: str):
        db.execute(
            "INSERT INTO access_log (link_id, file_id, event, at, ip_hash) VALUES (?,?,?,?,?)",
            (link["id"], file_id, event, now(), ctx.signer.ip_hash(ip)),
        )

    def starts_at_zero(request: Request, size: int) -> bool:
        rng = parse_range(request.headers.get("range"), size)
        return rng is None or (rng != "invalid" and rng[0] == 0)

    def counts_as_download(request: Request, size: int) -> bool:
        """A download is a request for the whole file from the start (no Range, or bytes=0-).
        Small probes such as bytes=0-0 and resumed ranges from the middle are not counted."""
        rng = parse_range(request.headers.get("range"), size)
        return rng is None or (rng != "invalid" and rng[0] == 0 and rng[1] >= size - 1)

    @app.get("/healthz")
    def healthz():
        # `instance` lets Handoff prove that a public address leads to this very run.
        return {"ok": True, "app": "handoff", "instance": ctx.instance_id}

    @app.get("/robots.txt")
    def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.get("/s/{token}")
    def page(token: str, request: Request):
        link, ip = resolve(token, request)
        if not link:
            return inactive()
        if not unlocked(link, request):
            return html("gate.html", token=token, error=None)
        files = visible_files(link)
        db.execute("UPDATE share_links SET last_accessed_at = ? WHERE id = ?", (now(), link["id"]))
        log(link, None, "view", ip)
        project = db.one("SELECT title FROM projects WHERE id = ?", (link["project_id"],))
        exhausted = link["max_downloads"] is not None and link["download_count"] >= link["max_downloads"]
        items = [
            {
                "id": f["id"], "name": f["original_name"], "size": f["size_bytes"], "mime": f["mime_sniffed"],
                "sha256": f["sha256"], "kind": preview_kind(f["mime_sniffed"], f["size_bytes"]),
            }
            for f in files
        ]
        remaining = None
        if link["max_downloads"] is not None:
            remaining = max(link["max_downloads"] - link["download_count"], 0)
        return html(
            "share.html", token=token, title=project["title"] if project else "Files", files=items,
            view_only=link["access"] == "view_only", exhausted=exhausted, expires_at=link["expires_at"],
            remaining=remaining,
        )

    @app.post("/s/{token}/unlock")
    async def unlock(token: str, request: Request):
        link, ip = resolve(token, request)
        if not link:
            return inactive()
        if not link["password_hash"]:
            return RedirectResponse(f"/s/{token}", status_code=303)
        if not ctx.password_limiter.allow(f"{ip}:{link['id']}"):
            return html("gate.html", 429, token=token, error="Too many attempts. Wait a few minutes and try again.")
        body = (await request.body())[:4096].decode("utf-8", "ignore")
        password = parse_qs(body).get("password", [""])[0]
        from .security import verify_password

        if not verify_password(password, link["password_hash"]):
            return html("gate.html", 401, token=token, error="That password is not right.")
        resp = RedirectResponse(f"/s/{token}", status_code=303)
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" and s.trust_proxy_headers
        resp.set_cookie(
            f"unlock-{link['id']}", ctx.signer.make_unlock(link["id"]), max_age=12 * 3600, httponly=True,
            samesite="lax", path="/s/", secure=bool(secure),
        )
        return resp

    @app.api_route("/s/{token}/files/{fid}/raw", methods=["GET", "HEAD"])
    def raw(token: str, fid: str, request: Request):
        link, ip = resolve(token, request)
        if not link:
            return inactive()
        if not unlocked(link, request):
            return PlainTextResponse("Password required.", status_code=401)
        f = find_file(link, fid)
        kind = preview_kind(f["mime_sniffed"], f["size_bytes"]) if f else None
        if not f or not kind:
            return PlainTextResponse("No preview is available for this file.", status_code=404)
        p = file_path(s, f["project_id"], f["id"])
        if not p.exists():
            return PlainTextResponse("This file is currently unavailable.", status_code=404)
        if request.method == "GET" and starts_at_zero(request, f["size_bytes"]):
            log(link, f["id"], "preview", ip)
        media = "text/plain; charset=utf-8" if kind == "text" else f["mime_sniffed"]
        extra = {"X-Frame-Options": "SAMEORIGIN"} if kind == "pdf" else {
            "Content-Security-Policy": "default-src 'none'; sandbox", "X-Frame-Options": "SAMEORIGIN",
        }
        if kind == "pdf":
            extra["Content-Security-Policy"] = "frame-ancestors 'self'"
        return file_response(
            p, f["size_bytes"], media, content_disposition(f["original_name"], inline=True), f["sha256"],
            request.headers.get("range"), request.headers.get("if-range"), extra,
        )

    @app.api_route("/s/{token}/files/{fid}/download", methods=["GET", "HEAD"])
    def download(token: str, fid: str, request: Request):
        link, ip = resolve(token, request)
        if not link:
            return inactive()
        if not unlocked(link, request):
            return PlainTextResponse("Password required.", status_code=401)
        if link["access"] != "download":
            return PlainTextResponse("This link is view-only. Downloads are not enabled.", status_code=403)
        f = find_file(link, fid)
        if not f:
            return PlainTextResponse("File not found.", status_code=404)
        p = file_path(s, f["project_id"], f["id"])
        if not p.exists():
            return PlainTextResponse("This file is currently unavailable.", status_code=404)
        if request.method == "GET" and counts_as_download(request, f["size_bytes"]):
            # Counted only here, never on the page load, so chat-app link previews can't use up the limit.
            changed = db.execute(
                """UPDATE share_links SET download_count = download_count + 1
                   WHERE id = ? AND (max_downloads IS NULL OR download_count < max_downloads)""",
                (link["id"],),
            )
            if not changed:
                return PlainTextResponse("The download limit for this link has been reached.", status_code=410)
            log(link, f["id"], "download", ip)
        return file_response(
            p, f["size_bytes"], "application/octet-stream", content_disposition(f["original_name"], inline=False),
            f["sha256"], request.headers.get("range"), request.headers.get("if-range"), {},
        )

    return app


def _hash(token: str) -> str:
    from .security import token_hash

    return token_hash(token)
