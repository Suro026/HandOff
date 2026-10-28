"""Command line: serve (default), backup, restore, verify."""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import signal
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .context import build_context
from .db import Database
from .storage import file_path, sha256_file


async def serve(settings: Settings) -> None:
    import uvicorn

    from .owner_app import create_owner_app
    from .share_app import create_share_app

    ctx = build_context(settings)
    servers = [
        uvicorn.Server(uvicorn.Config(create_owner_app(ctx), host=settings.owner_bind, port=settings.owner_port,
                                      log_level="info", access_log=False, proxy_headers=False)),
        uvicorn.Server(uvicorn.Config(create_share_app(ctx), host=settings.share_bind, port=settings.share_port,
                                      log_level="info", access_log=False, proxy_headers=False)),
    ]
    for sv in servers:
        sv.install_signal_handlers = lambda: None  # we stop both together below

    def stop() -> None:
        for sv in servers:
            sv.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass

    print(f"Handoff {__version__}")
    print(f"  Owner dashboard : http://localhost:{settings.owner_port}  (bound to {settings.owner_bind} inside this process)")
    print(f"  Client sharing  : port {settings.share_port}, links use {settings.share_base()}")
    if settings.is_local_only():
        print("  Note: PUBLIC_BASE_URL is not set, so share links only work on this computer.")
    if settings.owner_bind not in ("127.0.0.1", "localhost", "::1"):
        print("  WARNING: the owner dashboard is listening beyond this computer. Set OWNER_BIND=127.0.0.1.")
    print(f"  Data directory  : {settings.data_dir}")
    await asyncio.gather(*(sv.serve() for sv in servers))


def _ready_files(db: Database):
    return db.query("SELECT id, project_id, size_bytes, sha256, status FROM files WHERE status IN ('ready','missing')")


def backup(settings: Settings, dest: Path, db_only: bool = False) -> int:
    """With db_only, write only the consistent database snapshot and the hash manifest. Use it when you copy
    the (write-once) files folder yourself with rsync or a file manager, to avoid storing every file twice."""
    settings.ensure_dirs()
    db = Database(settings.db_path)
    dest.mkdir(parents=True, exist_ok=True)
    db.backup_to(dest / "db" / "handoff.sqlite3")  # consistent even while the app is running
    # Encryption and signing keys are deliberately NOT copied: a backup must not carry what unlocks stored link secrets.
    copied = skipped = 0
    lines = []
    for row in _ready_files(db):
        src = file_path(settings, row["project_id"], row["id"])
        if not src.exists():
            print(f"missing on disk, not backed up: {row['project_id']}/{row['id']}", file=sys.stderr)
            continue
        out = dest / "files" / row["project_id"] / row["id"]
        if db_only:
            lines.append(f"{row['sha256']}  files/{row['project_id']}/{row['id']}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size == row["size_bytes"]:
            skipped += 1  # files are write-once, so same name and size means same content
        else:
            tmp = out.with_suffix(".tmp")
            shutil.copyfile(src, tmp)
            os.replace(tmp, out)
            copied += 1
        lines.append(f"{row['sha256']}  files/{row['project_id']}/{row['id']}")
    (dest / "MANIFEST.sha256").write_text("\n".join(lines) + ("\n" if lines else ""))
    if db_only:
        print(f"Database snapshot and manifest written to {dest}. Copy the files folder ({settings.files_dir}) yourself.")
        return 0
    print(f"Backup written to {dest}: {copied} file(s) copied, {skipped} already present.")
    print("Check it any time with:  sha256sum -c MANIFEST.sha256   (run inside the backup folder)")
    return 0


def restore(settings: Settings, src: Path, force: bool) -> int:
    if not (src / "db" / "handoff.sqlite3").exists():
        print(f"{src} does not look like a Handoff backup (no db/handoff.sqlite3).", file=sys.stderr)
        return 2
    if settings.db_path.exists() and not force:
        print("A database already exists in the data directory. Stop the app, then re-run with --force to replace it.", file=sys.stderr)
        return 2
    settings.ensure_dirs()
    shutil.copyfile(src / "db" / "handoff.sqlite3", settings.db_path)
    for ext in ("-wal", "-shm"):
        Path(str(settings.db_path) + ext).unlink(missing_ok=True)
    n = 0
    for p in (src / "files").rglob("*") if (src / "files").exists() else []:
        if p.is_file():
            out = settings.files_dir / p.relative_to(src / "files")
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out)
            n += 1
    print(f"Restored database and {n} file(s). Start the app, then run `verify` to confirm integrity.")
    print("Links you already sent keep working. Because encryption keys are never backed up, the app can't show "
          "the full text of older links again; create a new link when you need to copy one.")
    return 0


def verify(settings: Settings, fix: bool) -> int:
    db = Database(settings.db_path)
    db.migrate(settings.backups_dir)
    bad = ok = 0
    for row in _ready_files(db):
        p = file_path(settings, row["project_id"], row["id"])
        if not p.exists():
            print(f"MISSING   {row['project_id']}/{row['id']}")
            bad += 1
            continue
        if sha256_file(p) != row["sha256"]:
            print(f"MISMATCH  {row['project_id']}/{row['id']}  (content differs from what was uploaded)")
            bad += 1
            continue
        ok += 1
        if row["status"] == "missing" and fix:
            db.execute("UPDATE files SET status = 'ready' WHERE id = ?", (row["id"],))
            print(f"reinstated {row['project_id']}/{row['id']}")
    print(f"{ok} file(s) verified, {bad} problem(s).")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handoff")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the owner dashboard and the share service (default)")
    sub.add_parser("desktop", help="run as a desktop app: tray icon, automatic ports, connection manager")
    b = sub.add_parser("backup", help="write a consistent backup to a folder")
    b.add_argument("dest", type=Path)
    b.add_argument("--db-only", action="store_true", help="snapshot the database and manifest only (copy files yourself)")
    r = sub.add_parser("restore", help="restore a backup into DATA_DIR (stop the app first)")
    r.add_argument("src", type=Path)
    r.add_argument("--force", action="store_true")
    v = sub.add_parser("verify", help="re-hash every stored file and compare with the database")
    v.add_argument("--fix", action="store_true", help="mark files as ready again when they match")
    args, rest = parser.parse_known_args(argv)
    if args.cmd == "desktop":
        from .desktop import main as desktop_main

        return desktop_main(rest)
    settings = Settings.from_env()
    if args.cmd == "backup":
        return backup(settings, args.dest.resolve(), args.db_only)
    if args.cmd == "restore":
        return restore(settings, args.src.resolve(), args.force)
    if args.cmd == "verify":
        return verify(settings, args.fix)
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
