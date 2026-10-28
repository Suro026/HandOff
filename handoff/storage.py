"""Streamed uploads to local disk, with integrity hashing and disk-safety limits.

Memory use is about one chunk regardless of file size. The bytes written are exactly the bytes received.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import AsyncIterator, BinaryIO

import anyio

from .config import MiB, Settings

_RECHECK_EVERY = 64 * MiB


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def file_path(settings: Settings, project_id: str, file_id: str) -> Path:
    # Opaque ids only. The original filename never touches the filesystem.
    return settings.files_dir / project_id / file_id


def _write(f: BinaryIO, h, chunk: bytes) -> None:
    h.update(chunk)
    f.write(chunk)


def _free(settings: Settings) -> int:
    return shutil.disk_usage(settings.data_dir).free


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return  # not supported on this platform
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


async def stream_to_disk(
    stream: AsyncIterator[bytes],
    settings: Settings,
    part_path: Path,
    final_path: Path,
    declared_len: int | None,
) -> tuple[int, str, bytes]:
    """Returns (size, sha256 hex, first 4 KiB). Raises UploadError; always removes the partial file on failure."""
    reserve = settings.reserve_bytes()
    cap = settings.max_upload_bytes
    if cap is not None and declared_len is not None and declared_len > cap:
        raise UploadError(413, "File is larger than this server's configured upload limit.")
    if declared_len is not None and _free(settings) - declared_len < reserve:
        raise UploadError(507, "Not enough free disk space. The server keeps a reserve free and refused this upload.")

    h = hashlib.sha256()
    size = 0
    head = bytearray()
    next_check = _RECHECK_EVERY
    part_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(part_path, "wb")
    try:
        it = stream.__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(it.__anext__(), settings.upload_idle_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise UploadError(408, "Upload stalled and was cancelled.")
            if not chunk:
                continue
            size += len(chunk)
            if cap is not None and size > cap:
                raise UploadError(413, "File is larger than this server's configured upload limit.")
            if declared_len is not None and size > declared_len:
                raise UploadError(400, "Received more data than Content-Length declared.")
            if size >= next_check:
                next_check += _RECHECK_EVERY
                if _free(settings) < reserve:
                    raise UploadError(507, "Disk space fell below the reserve during upload. Upload cancelled.")
            if len(head) < 4096:
                head.extend(chunk[: 4096 - len(head)])
            await anyio.to_thread.run_sync(_write, f, h, chunk)
        if declared_len is not None and size != declared_len:
            raise UploadError(400, "Upload ended before Content-Length bytes were received.")
        f.flush()
        os.fsync(f.fileno())
    except BaseException:
        f.close()
        part_path.unlink(missing_ok=True)
        raise
    f.close()
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part_path, final_path)  # atomic: same filesystem by layout
    _fsync_dir(final_path.parent)
    return size, h.hexdigest(), bytes(head)


def sha256_file(path: Path, chunk: int = MiB) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def cleanup_stale_parts(settings: Settings) -> int:
    removed = 0
    cutoff = time.time() - settings.stale_part_seconds
    for p in settings.incoming_dir.glob("*.part"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed
