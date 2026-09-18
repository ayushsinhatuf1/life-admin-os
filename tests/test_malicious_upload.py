"""Tests for Malicious Upload Defence (P6.2).

Verifies:
1. Rejection of PDFs containing JavaScript, embedded files, or launch actions.
2. Rejection of PDFs exceeding page limits or decompressed size (zip bombs).
3. EXIF metadata stripping from uploaded JPEG images.
4. ClamAV scanning integration (detects malware, fails open in dev, fails closed in prod).
5. User upload rate limiting sliding window enforcement.
"""
import struct
import sys
import uuid
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.upload_security import (
    check_pdf_active_content,
    check_pdf_limits,
    check_rate_limit,
    reset_rate_limits_for_testing,
    scan_clamav,
    strip_exif,
)


# ------------------------------------------------------------------ Crafted Fixtures

CLEAN_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\nxref\n0 4\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

PDF_WITH_JAVASCRIPT = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Names << /JavaScript 2 0 R >> >>\nendobj\n2 0 obj\n<< /JS (app.alert('PWNED');) >>\nendobj\n%%EOF"

PDF_WITH_EMBEDDED_FILES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Names << /EmbeddedFiles 2 0 R >> >>\nendobj\n2 0 obj\n<< /EF << /F 3 0 R >> >>\nendobj\n%%EOF"

PDF_WITH_LAUNCH_ACTION = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /OpenAction << /Type /Action /S /Launch /F (calc.exe) >> >>\nendobj\n%%EOF"

# Simulated JPEG with APP1 EXIF segment (0xFFE1) containing GPS metadata
SAMPLE_JPEG_WITH_EXIF = (
    b"\xff\xd8"
    + b"\xff\xe1\x00\x18"
    + b"Exif\x00\x00II*\x00\x08\x00\x00\x00"
    + b"GPS_TAGS_LAT_LON"
    + b"\xff\xdb\x00\x43\x00" + (b"\x00" * 64)
    + b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    + b"\xff\xd9"
)


def test_clean_pdf_passes():
    violations = check_pdf_active_content(CLEAN_PDF)
    assert violations == [], f"Clean PDF should have no violations, got: {violations}"


def test_reject_pdf_with_javascript():
    violations = check_pdf_active_content(PDF_WITH_JAVASCRIPT)
    assert any("JavaScript" in v for v in violations), f"Expected JavaScript violation, got: {violations}"


def test_reject_pdf_with_embedded_files():
    violations = check_pdf_active_content(PDF_WITH_EMBEDDED_FILES)
    assert any("Embedded Files" in v for v in violations), f"Expected Embedded Files violation, got: {violations}"


def test_reject_pdf_with_launch_action():
    violations = check_pdf_active_content(PDF_WITH_LAUNCH_ACTION)
    assert any("Launch Action" in v for v in violations), f"Expected Launch Action violation, got: {violations}"


def test_pdf_page_limits():
    # Clean PDF has 1 page, should pass limit of 100
    pages, _ = check_pdf_limits(CLEAN_PDF, max_pages=100)
    assert pages >= 1

    # Over limit test: construct PDF with 105 page markers
    crafted_oversized = b"%PDF-1.4\n" + (b"/Type /Page\n" * 105) + b"%%EOF"
    try:
        check_pdf_limits(crafted_oversized, max_pages=100)
        assert False, "Should have raised ValueError for exceeding 100 pages"
    except ValueError as exc:
        assert "exceeds page limit" in str(exc)


def test_pdf_decompressed_zip_bomb_cap():
    # If decompressed size exceeds max_decompressed_bytes, it must fail
    try:
        check_pdf_limits(CLEAN_PDF, max_pages=100, max_decompressed_bytes=10)
        assert False, "Should have raised ValueError for exceeding decompressed size limit"
    except ValueError as exc:
        assert "decompressed size limit" in str(exc)


def test_strip_exif_from_image():
    cleaned, was_stripped = strip_exif(SAMPLE_JPEG_WITH_EXIF, "image/jpeg")
    assert was_stripped is True
    # Verify APP1 marker (0xFFE1) was removed
    assert b"\xff\xe1" not in cleaned


def test_clamav_scanner_behaviour():
    # Test 1: No clamav_host configured -> returns None (clean)
    assert scan_clamav(b"clean content", host=None) is None

    # Test 2: Unreachable host in dev -> fails open (returns None)
    res = scan_clamav(b"content", host="127.0.0.1", port=65534, fail_closed=False, timeout=0.1)
    assert res is None

    # Test 3: Unreachable host in prod -> fails closed (raises RuntimeError)
    try:
        scan_clamav(b"content", host="127.0.0.1", port=65534, fail_closed=True, timeout=0.1)
        assert False, "Should have raised RuntimeError when scanner unreachable in production"
    except RuntimeError as exc:
        assert "Malware scanner is currently unavailable" in str(exc)


def test_user_upload_rate_limiting():
    reset_rate_limits_for_testing()
    test_user_id = uuid.uuid4()

    # Allowed up to 5 uploads in test window
    for _ in range(5):
        allowed = check_rate_limit(test_user_id, max_count=5, window_seconds=60)
        assert allowed is True

    # 6th upload must be blocked
    blocked = check_rate_limit(test_user_id, max_count=5, window_seconds=60)
    assert blocked is False

    # Different user should not be blocked
    other_user = uuid.uuid4()
    assert check_rate_limit(other_user, max_count=5, window_seconds=60) is True


def run_all():
    test_clean_pdf_passes()
    test_reject_pdf_with_javascript()
    test_reject_pdf_with_embedded_files()
    test_reject_pdf_with_launch_action()
    test_pdf_page_limits()
    test_pdf_decompressed_zip_bomb_cap()
    test_strip_exif_from_image()
    test_clamav_scanner_behaviour()
    test_user_upload_rate_limiting()
    print("All 9 malicious upload defence tests PASSED.")


if __name__ == "__main__":
    run_all()
