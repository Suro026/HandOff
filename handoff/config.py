"""Settings, read from environment variables. Nothing here needs an external service."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

GiB = 1024**3
MiB = 1024**2


def _opt_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


@dataclass
class Settings:
    data_dir: Path
    public_base_url: str = ""
    owner_bind: str = "127.0.0.1"
    owner_port: int = 8080
    share_bind: str = "0.0.0.0"
    share_port: int = 8081
    # Upload safety. No fixed size cap by default; the disk reserve always applies.
    min_free_bytes: int | None = None  # default: max(2 GiB, 5% of the volume)
    max_upload_bytes: int | None = None  # optional cap, unset by default
    max_concurrent_uploads: int = 2
    upload_idle_timeout: float = 60.0
    stale_part_seconds: int = 24 * 3600
    trust_proxy_headers: bool = False
    owner_allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    chunk_size: int = MiB
    session_hours: int = 24 * 7
    key_dir_override: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        extra = tuple(h.strip().lower() for h in os.environ.get("OWNER_ALLOWED_HOSTS", "").split(",") if h.strip())
        base = cls(
            data_dir=Path(os.environ.get("DATA_DIR", "./data")).resolve(),
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/"),
            owner_bind=os.environ.get("OWNER_BIND", "127.0.0.1"),
            owner_port=int(os.environ.get("OWNER_PORT", "8080")),
            share_bind=os.environ.get("SHARE_BIND", "0.0.0.0"),
            share_port=int(os.environ.get("SHARE_PORT", "8081")),
            min_free_bytes=_opt_int("MIN_FREE_BYTES"),
            max_upload_bytes=_opt_int("MAX_UPLOAD_BYTES"),
            max_concurrent_uploads=int(os.environ.get("MAX_CONCURRENT_UPLOADS", "2")),
            upload_idle_timeout=float(os.environ.get("UPLOAD_IDLE_TIMEOUT", "60")),
            trust_proxy_headers=os.environ.get("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes"),
        )
        base.owner_allowed_hosts = base.owner_allowed_hosts + extra
        if os.environ.get("KEY_DIR", "").strip():
            base.key_dir_override = Path(os.environ["KEY_DIR"]).resolve()
        return base

    # --- paths -------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "handoff.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def key_dir(self) -> Path:
        """Encryption and signing keys. Never included in backups. Desktop installs put this outside the data folder."""
        return self.key_dir_override or (self.data_dir / "keys")

    @property
    def secret_path(self) -> Path:
        return self.key_dir / "secret.key"

    @property
    def legacy_secret_path(self) -> Path:
        return self.data_dir / "db" / "secret.key"

    def ensure_dirs(self) -> None:
        for p in (self.db_path.parent, self.files_dir, self.incoming_dir, self.backups_dir, self.key_dir):
            p.mkdir(parents=True, exist_ok=True)

    # --- helpers -----------------------------------------------------------
    def reserve_bytes(self) -> int:
        if self.min_free_bytes is not None:
            return self.min_free_bytes
        total = shutil.disk_usage(self.data_dir).total
        return max(2 * GiB, total // 20)

    def share_base(self) -> str:
        return self.public_base_url or f"http://localhost:{self.share_port}"

    def is_local_only(self) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(self.share_base()).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1", "") or host.endswith(".localhost")
