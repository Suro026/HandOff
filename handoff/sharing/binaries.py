"""Download and verify the optional third-party helper used by Quick Share (cloudflared).

The helper is fetched only after the owner agrees, from a pinned release, and is refused unless its SHA-256 matches the
pinned value. Nothing is downloaded for same-Wi-Fi or custom-address sharing.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

PINS_PATH = Path(__file__).with_name("cloudflared_pins.json")


class HelperError(Exception):
    pass


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64" if machine in ("amd64", "x86_64", "x64") else machine
    return f"{system}-{arch}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


class HelperDownloader:
    def __init__(self, bin_dir: Path, pins: dict | None = None, opener: Callable = urllib.request.urlopen):
        self.bin_dir = Path(bin_dir)
        self.pins = pins or json.loads(PINS_PATH.read_text())
        self.opener = opener

    def asset(self) -> dict:
        key = platform_key()
        asset = self.pins["assets"].get(key)
        if not asset:
            raise HelperError(f"Quick Share has no helper for this computer ({key}). Use a custom address instead.")
        return asset

    @property
    def path(self) -> Path:
        return self.bin_dir / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")

    @property
    def _stamp(self) -> Path:
        return self.bin_dir / "cloudflared.sha256"

    def is_installed(self) -> bool:
        """True only if the installed file is exactly what we pinned (the check is a full hash, about a second)."""
        try:
            asset = self.asset()
        except HelperError:
            return False
        if not self.path.exists() or not self._stamp.exists():
            return False
        if self._stamp.read_text().strip() != asset["sha256"] or self.path.stat().st_size < 1_000_000:
            return False
        if asset["kind"] != "tgz":  # the pinned hash is of the program itself, so re-check it before every use
            return sha256_of(self.path) == asset["sha256"]
        return True

    def ensure(self, progress: Callable[[int, int], None] | None = None) -> Path:
        if self.is_installed():
            return self.path
        asset = self.asset()
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        url = self.pins["base_url"] + asset["name"]
        part = self.bin_dir / (asset["name"] + ".part")
        h = hashlib.sha256()
        try:
            with self.opener(url, timeout=60) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while block := resp.read(256 * 1024):
                    out.write(block)
                    h.update(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
        except Exception as e:
            part.unlink(missing_ok=True)
            raise HelperError(f"Download failed ({type(e).__name__}). Check your internet connection.") from e
        if h.hexdigest() != asset["sha256"]:
            part.unlink(missing_ok=True)
            raise HelperError("The downloaded helper did not match its expected fingerprint, so it was discarded.")
        if asset["kind"] == "tgz":
            self._extract_tgz(part)
        else:
            os.replace(part, self.path)
        if platform.system() != "Windows":
            self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self._stamp.write_text(asset["sha256"])
        return self.path

    def _extract_tgz(self, archive: Path) -> None:
        with tarfile.open(archive) as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "cloudflared"), None)
            if member is None:
                raise HelperError("The helper archive did not contain the expected program.")
            src = tar.extractfile(member)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "wb") as out:
                out.write(src.read())
            os.replace(tmp, self.path)
        archive.unlink(missing_ok=True)
