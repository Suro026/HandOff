"""Content sniffing and the inline-preview allowlist. Used only to decide how to SHOW a file; the file is never modified."""
from __future__ import annotations

import re
from urllib.parse import quote

# Only these sniffed types are ever rendered inline. HTML and SVG are deliberately absent:
# they would run uploaded code on the app's origin. They fall under text/plain or download-only.
PREVIEW_KINDS = {
    "image/png": "image", "image/jpeg": "image", "image/gif": "image", "image/webp": "image", "image/avif": "image",
    "video/mp4": "video", "video/webm": "video",
    "audio/mpeg": "audio", "audio/ogg": "audio", "audio/wav": "audio", "audio/flac": "audio", "audio/mp4": "audio",
    "application/pdf": "pdf",
    "text/plain": "text",
}
TEXT_PREVIEW_MAX_BYTES = 2 * 1024 * 1024


def sniff_mime(head: bytes) -> str:
    h = head
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "audio/wav"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        if brand in (b"heic", b"heix", b"hevc", b"mif1"):
            return "image/heic"
        return "video/mp4"
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in h[:64] else "video/x-matroska"
    if h.startswith(b"%PDF-"):
        return "application/pdf"
    if h.startswith(b"OggS"):
        return "audio/ogg"
    if h.startswith(b"fLaC"):
        return "audio/flac"
    if h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if h.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "application/zip"
    if h.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if h.startswith(b"Rar!"):
        return "application/vnd.rar"
    if h.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if h and b"\x00" not in h:
        try:
            h.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            # A multi-byte character may be cut at the end of the sample.
            try:
                h[:-3].decode("utf-8")
                return "text/plain"
            except UnicodeDecodeError:
                pass
    return "application/octet-stream"


def preview_kind(mime_sniffed: str, size_bytes: int) -> str | None:
    kind = PREVIEW_KINDS.get(mime_sniffed)
    if kind == "text" and size_bytes > TEXT_PREVIEW_MAX_BYTES:
        return None
    return kind


_BAD = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]")


def clean_name(name: str) -> str:
    """Display name only. It is never used to build a path."""
    name = _BAD.sub("_", name or "").strip().strip(".")
    return (name[:255] or "file")


def content_disposition(name: str, inline: bool) -> str:
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name).strip() or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
