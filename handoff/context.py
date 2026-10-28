"""Shared state for the two apps. One process, one database, one rate limiter."""
from __future__ import annotations

import secrets
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Settings
from .db import Database
from .keys import KeyStore
from .security import RateLimiter, Signer, load_secret
from .storage import cleanup_stale_parts, file_path


@dataclass
class Context:
    settings: Settings
    db: Database
    signer: Signer
    keys: KeyStore
    # Random per run. The share service reports it on /healthz so a self-check can prove that a public address
    # really leads to this running copy and not to something else.
    instance_id: str = field(default_factory=lambda: secrets.token_hex(8))
    manager: Any = None  # sharing.manager.ConnectionManager, set by build_context
    on_quit: Callable[[], None] | None = None  # set by the desktop launcher
    # Set by the desktop launcher: make the share service listen on this computer only, or on the network.
    share_bind_hook: Callable[[str], None] | None = None
    login_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10, 300))
    lookup_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(240, 60))
    password_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10, 600))
    active_uploads: int = 0


def build_context(settings: Settings, gate_sharing: bool = False) -> Context:
    from .sharing.manager import ConnectionManager

    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.migrate(settings.backups_dir)
    _move_legacy_secret(settings)
    ctx = Context(
        settings=settings, db=db, signer=Signer(load_secret(settings.secret_path)), keys=KeyStore(settings.key_dir)
    )
    ctx.manager = ConnectionManager(ctx, gate=gate_sharing)
    startup_housekeeping(ctx)
    return ctx


def _move_legacy_secret(settings: Settings) -> None:
    """Earlier versions kept the signing secret next to the database, where backups copied it."""
    old, new = settings.legacy_secret_path, settings.secret_path
    if old.exists() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))


def startup_housekeeping(ctx: Context) -> dict:
    """Single process, so any 'uploading' row left over is from a crash. Reconcile the DB with the disk."""
    s, db = ctx.settings, ctx.db
    cleanup_stale_parts(s)
    stale = db.query("SELECT id, project_id FROM files WHERE status = 'uploading'")
    for row in stale:
        file_path(s, row["project_id"], row["id"]).unlink(missing_ok=True)
    db.execute("DELETE FROM files WHERE status = 'uploading'")
    missing = 0
    for row in db.query("SELECT id, project_id, size_bytes FROM files WHERE status = 'ready'"):
        p = file_path(s, row["project_id"], row["id"])
        if not p.exists() or p.stat().st_size != row["size_bytes"]:
            db.execute("UPDATE files SET status = 'missing' WHERE id = ?", (row["id"],))
            missing += 1
    return {"missing": missing}


def delete_project_files(ctx: Context, project_id: str) -> None:
    shutil.rmtree(ctx.settings.files_dir / project_id, ignore_errors=True)
