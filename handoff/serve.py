"""Serving stored originals with HTTP Range support. Bytes are streamed in small chunks, never loaded whole."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from fastapi import Response
from fastapi.responses import StreamingResponse

CHUNK = 256 * 1024


def parse_range(header: str | None, size: int):
    """None = no usable Range (serve everything). 'invalid' = 416. Otherwise (start, end) inclusive.
    Multiple ranges are not supported and are served as the whole file, which the spec allows."""
    if not header:
        return None
    header = header.strip()
    if not header.lower().startswith("bytes="):
        return None
    spec = header[6:]
    if "," in spec or "-" not in spec:
        return None
    a, b = spec.split("-", 1)
    try:
        if a == "":
            n = int(b)
            if n <= 0 or size == 0:
                return "invalid"
            return max(size - n, 0), size - 1
        start = int(a)
        end = int(b) if b else size - 1
    except ValueError:
        return None
    if start >= size or end < start:
        return "invalid"
    return start, min(end, size - 1)


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            block = f.read(min(CHUNK, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def file_response(
    path: Path,
    size: int,
    media_type: str,
    disposition: str,
    etag: str,
    range_header: str | None,
    if_range: str | None,
    extra_headers: dict[str, str],
) -> Response:
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{etag}"',
        "Content-Disposition": disposition,
        **extra_headers,
    }
    rng = parse_range(range_header, size)
    if if_range and if_range.strip('"') != etag:
        rng = None  # validator does not match: ignore Range and send the whole file
    if rng == "invalid":
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if rng is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(_iter_file(path, 0, size), status_code=200, media_type=media_type, headers=headers)
    start, end = rng
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_iter_file(path, start, length), status_code=206, media_type=media_type, headers=headers)
