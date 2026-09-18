"""Malicious upload defence service (P6.2, Section 18).

Controls:
1. Rejects PDFs containing JavaScript, embedded files, or launch actions.
2. Caps page count and decompressed stream size to stop zip bombs.
3. Strips EXIF metadata from images before S3 storage.
4. Scans payloads via ClamAV if configured (fails closed in prod, open in dev).
5. Enforces per-user sliding window upload rate limiting.
"""
from __future__ import annotations

import io
import logging
import re
import socket
import struct
import threading
import time
import uuid
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

log = logging.getLogger(__name__)

# Disallowed PDF action/content tokens
FORBIDDEN_PDF_TOKENS = [
    (re.compile(rb"/JavaScript\b", re.IGNORECASE), "JavaScript"),
    (re.compile(rb"/JS\b", re.IGNORECASE), "JavaScript"),
    (re.compile(rb"/EmbeddedFiles\b", re.IGNORECASE), "Embedded Files"),
    (re.compile(rb"/EF\b", re.IGNORECASE), "Embedded Files"),
    (re.compile(rb"/Launch\b", re.IGNORECASE), "Launch Action"),
]

# In-memory sliding window rate limiter
_RATE_LIMIT_LOCK = threading.Lock()
_USER_UPLOAD_HISTORY: dict[uuid.UUID, list[float]] = {}


def check_pdf_active_content(data: bytes) -> list[str]:
    """Scan PDF for forbidden active elements (JS, embedded files, launch actions)."""
    violations: list[str] = []

    # 1. Structural PyMuPDF inspection if available
    if fitz:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            # Check embedded files
            if hasattr(doc, "embfile_count") and doc.embfile_count() > 0:
                violations.append("Embedded Files")

            # Check page actions / annotations
            for page in doc:
                # Check annotations for launch or JS actions
                for annot in page.annots():
                    info = annot.info or {}
                    content_str = str(info).lower()
                    if "javascript" in content_str or "launch" in content_str:
                        violations.append("Active Action Annotation")
            doc.close()
        except Exception as exc:
            log.debug("PyMuPDF inspection error: %s", exc)

    # 2. Byte token scanning
    for pattern, label in FORBIDDEN_PDF_TOKENS:
        if pattern.search(data):
            if label not in violations:
                violations.append(label)

    return violations


def check_pdf_limits(
    data: bytes,
    max_pages: int = 100,
    max_decompressed_bytes: int = 100 * 1024 * 1024,
) -> tuple[int, int]:
    """Verify page count and decompressed size limits to stop zip bombs.
    
    Returns: (page_count, total_decompressed_bytes)
    """
    total_decompressed = len(data)
    page_count = 0

    if fitz:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            page_count = len(doc)
            decompressed_sum = 0
            for i in range(len(doc)):
                page = doc[i]
                text = page.get_text()
                decompressed_sum += len(text.encode("utf-8"))
            doc.close()
            total_decompressed = max(total_decompressed, decompressed_sum)
        except Exception as exc:
            log.debug("PyMuPDF limit inspection error: %s", exc)

    if page_count == 0:
        # Fallback byte count for page markers
        page_matches = re.findall(rb"/Type\s*/Page\b", data)
        page_count = len(page_matches) if page_matches else 1

    if page_count > max_pages:
        raise ValueError(
            f"PDF exceeds page limit ({page_count} pages; maximum allowed is {max_pages})."
        )

    if total_decompressed > max_decompressed_bytes:
        raise ValueError(
            f"PDF exceeds decompressed size limit ({total_decompressed // (1024*1024)} MB; "
            f"maximum allowed is {max_decompressed_bytes // (1024*1024)} MB)."
        )

    return page_count, total_decompressed


def strip_exif(data: bytes, mime_type: str) -> tuple[bytes, bool]:
    """Strip EXIF metadata from JPEG, PNG, or WebP images to prevent privacy leakage."""
    if not mime_type.startswith("image/"):
        return data, False

    if Image:
        try:
            with Image.open(io.BytesIO(data)) as img:
                # Check if image has EXIF or metadata
                has_exif = bool(getattr(img, "_getexif", lambda: None)()) or bool(img.info)
                if not has_exif:
                    return data, False

                # Strip by recreating clean image data without metadata
                out_buf = io.BytesIO()
                format_map = {
                    "image/jpeg": "JPEG",
                    "image/png": "PNG",
                    "image/webp": "WEBP",
                }
                save_fmt = format_map.get(mime_type, img.format or "JPEG")

                # If image mode is P or RGBA, keep compatibility
                if img.mode in ("RGBA", "LA") and save_fmt == "JPEG":
                    clean_img = img.convert("RGB")
                else:
                    clean_img = img.copy()

                clean_img.save(out_buf, format=save_fmt)
                return out_buf.getvalue(), True
        except Exception as exc:
            log.warning("Pillow EXIF strip error: %s", exc)

    # Fallback byte-level EXIF stripping for JPEG (APP1 segment marker 0xFFE1)
    if mime_type == "image/jpeg" and b"\xff\xe1" in data[:1024]:
        # Simple APP1 stripping
        try:
            pos = data.find(b"\xff\xe1")
            if pos != -1 and pos + 4 < len(data):
                seg_len = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
                cleaned = data[:pos] + data[pos + 2 + seg_len :]
                return cleaned, True
        except Exception:
            pass

    return data, False


def scan_clamav(
    data: bytes,
    host: str | None,
    port: int = 3310,
    fail_closed: bool = False,
    timeout: float = 3.0,
) -> str | None:
    """Scan byte payload using ClamAV daemon via INSTREAM protocol.
    
    Returns:
        Virus name if malware detected, None if clean.
    Raises:
        RuntimeError if ClamAV is unreachable and fail_closed is True.
    """
    if not host:
        return None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            # Send INSTREAM command
            s.sendall(b"zINSTREAM\0")

            # Stream chunks with 4-byte network endian length
            chunk_size = 4096
            idx = 0
            while idx < len(data):
                chunk = data[idx : idx + chunk_size]
                s.sendall(struct.pack(">I", len(chunk)) + chunk)
                idx += len(chunk)

            # End of stream (0-length chunk)
            s.sendall(struct.pack(">I", 0))

            response = s.recv(1024).decode("utf-8", errors="replace").strip()
            if "FOUND" in response:
                match = re.search(r"stream:\s*(.+)\s+FOUND", response)
                virus_name = match.group(1) if match else "Malicious content"
                return virus_name
            return None
    except Exception as exc:
        log.warning("ClamAV scan connection error to %s:%s: %s", host, port, exc)
        if fail_closed:
            raise RuntimeError(
                "Malware scanner is currently unavailable. Upload blocked by security policy."
            ) from exc
        # Fail open in development
        return None


def check_rate_limit(
    user_id: uuid.UUID,
    max_count: int = 20,
    window_seconds: int = 600,
) -> bool:
    """Enforce per-user upload rate limiting using a sliding window.
    
    Returns True if permitted, False if rate limited.
    """
    now = time.time()
    cutoff = now - window_seconds

    with _RATE_LIMIT_LOCK:
        history = _USER_UPLOAD_HISTORY.setdefault(user_id, [])
        # Prune older than window
        _USER_UPLOAD_HISTORY[user_id] = [t for t in history if t > cutoff]
        if len(_USER_UPLOAD_HISTORY[user_id]) >= max_count:
            return False
        _USER_UPLOAD_HISTORY[user_id].append(now)
        return True


def reset_rate_limits_for_testing() -> None:
    """Reset rate limiting tracking (test helper)."""
    with _RATE_LIMIT_LOCK:
        _USER_UPLOAD_HISTORY.clear()
