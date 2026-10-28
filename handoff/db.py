"""SQLite metadata store. Only metadata lives here; file bytes live on disk."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


MIGRATIONS: list[str] = [
    # version 1
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        id_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT
    );
    CREATE TABLE files (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        original_name TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        mime_declared TEXT NOT NULL DEFAULT '',
        mime_sniffed TEXT NOT NULL DEFAULT 'application/octet-stream',
        sha256 TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('uploading','ready','missing')),
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_files_project ON files(project_id);
    CREATE TABLE share_links (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL CHECK (scope IN ('project','files')),
        access TEXT NOT NULL CHECK (access IN ('download','view_only')),
        password_hash TEXT,
        expires_at TEXT,
        max_downloads INTEGER,
        download_count INTEGER NOT NULL DEFAULT 0,
        revoked_at TEXT,
        created_at TEXT NOT NULL,
        last_accessed_at TEXT
    );
    CREATE INDEX idx_links_project ON share_links(project_id);
    CREATE TABLE share_link_files (
        link_id TEXT NOT NULL REFERENCES share_links(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
        PRIMARY KEY (link_id, file_id)
    );
    CREATE TABLE access_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id TEXT NOT NULL,
        file_id TEXT,
        event TEXT NOT NULL CHECK (event IN ('view','preview','download')),
        at TEXT NOT NULL,
        ip_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_log_link ON access_log(link_id);
    """,
    # version 2: recoverable links and app settings
    """
    ALTER TABLE share_links ADD COLUMN token_enc TEXT;
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        conn = self._connect()
        try:
            return conn.execute(sql, params).rowcount
        finally:
            conn.close()

    # --- settings --------------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- migrations ----------------------------------------------------------
    def schema_version(self) -> int:
        conn = self._connect()
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    def migrate(self, backups_dir: Path) -> None:
        current = self.schema_version()
        target = len(MIGRATIONS)
        if current >= target:
            return
        if current > 0:
            # Snapshot before touching an existing database.
            backups_dir.mkdir(parents=True, exist_ok=True)
            snap = backups_dir / f"pre-migration-v{current}-{int(time.time())}.sqlite3"
            self.backup_to(snap)
        conn = self._connect()
        try:
            for version in range(current, target):
                conn.executescript(MIGRATIONS[version])
                conn.execute(f"PRAGMA user_version = {version + 1}")
        finally:
            conn.close()

    def backup_to(self, dest: Path) -> None:
        """Consistent copy using SQLite's online backup API. Safe while the app is running."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self._connect()
        try:
            out = sqlite3.connect(dest)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
