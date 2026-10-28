"""Small pure-ASGI middleware (no buffering, safe for large streamed bodies)."""
from __future__ import annotations

import json
from urllib.parse import urlparse

from fastapi import Request


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8080
        return host[1:].split("]")[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class SecurityHeaders:
    """Adds baseline headers to every response unless the handler already set them.
    With `allowed_hosts` it also rejects unexpected Host headers (DNS rebinding) and cross-origin writes."""

    def __init__(self, app, headers: dict[str, str], allowed_hosts: tuple[str, ...] | None = None):
        self.app = app
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.allowed_hosts = allowed_hosts

    async def _reject(self, send, status: int, message: str):
        body = json.dumps({"detail": message}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.allowed_hosts is not None:
            req = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if _hostname(req.get("host", "")) not in self.allowed_hosts:
                return await self._reject(send, 400, "Unexpected Host header.")
            origin = req.get("origin")
            if origin and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
                if urlparse(origin).netloc.lower() != req.get("host", "").lower():
                    return await self._reject(send, 403, "Cross-origin request blocked.")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                present = {k.decode().lower() for k, _ in message.get("headers", [])}
                extra = [(k.encode(), v.encode()) for k, v in self.headers.items() if k not in present]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_wrapper)
