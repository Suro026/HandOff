"""Encryption of stored share-link secrets (recoverable links).

Why: a link's secret part is only ever shown to the owner. Storing just a hash is safest, but then a changed
public address (for example a temporary tunnel address) means the owner can't copy the link again. Handoff stores the
secret encrypted so the app can rebuild the full link, and still looks links up by hash.

Honest limits: the key sits on the same computer as the database. This protects a copied database or backup, not a
computer that is already compromised. The key directory is never included in `handoff backup`.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class KeyStore:
    def __init__(self, key_dir: Path):
        self.dir = Path(key_dir)
        self._fernet: Fernet | None = None

    @property
    def path(self) -> Path:
        return self.dir / "link.key"

    def _load(self) -> Fernet:
        if self._fernet is None:
            if self.path.exists():
                key = self.path.read_bytes().strip()
            else:
                self.dir.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key()
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key)
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt_token(self, token: str) -> str:
        return self._load().encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted: str | None) -> str | None:
        """The token, or None when it was never stored or this install has a different key (for example after a restore)."""
        if not encrypted:
            return None
        try:
            return self._load().decrypt(encrypted.encode()).decode()
        except (InvalidToken, ValueError):
            return None
