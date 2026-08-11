from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from ..config import Settings

register_heif_opener()

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_MIMES = ALLOWED_IMAGE_MIMES | {"application/pdf"}


class InvalidReceiptFile(ValueError):
    pass


def safe_filename(filename: str) -> str:
    name = Path(filename or "receipt").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return name[:180] or "receipt"


def sniff_mime(data: bytes, claimed: str | None, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").upper()
        mapping = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "HEIF": "image/heif", "HEIC": "image/heic"}
        if fmt in mapping:
            return mapping[fmt]
    except Exception:
        pass
    if claimed in ALLOWED_MIMES and Path(filename).suffix.lower() in {".heic", ".heif"}:
        return claimed
    raise InvalidReceiptFile("The file is not a supported image or PDF")


def save_original(settings: Settings, receipt_id: str, filename: str, data: bytes) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    folder = settings.receipts_dir / f"{now:%Y}" / f"{now:%m}" / receipt_id
    folder.mkdir(parents=True, exist_ok=True)
    clean_name = safe_filename(filename)
    destination = folder / clean_name
    fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(destination.resolve()), clean_name


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_visuals(settings: Settings, receipt_id: str, storage_path: str, mime_type: str) -> tuple[list[tuple[bytes, str]], str | None, int, str]:
    """Return model-ready page images, preview path, page count, and embedded PDF text."""
    source = Path(storage_path)
    preview = settings.previews_dir / f"{receipt_id}.jpg"
    pages: list[tuple[bytes, str]] = []
    extracted_text = ""

    if mime_type == "application/pdf":
        with tempfile.TemporaryDirectory(prefix="receipt-pdf-") as tmp:
            prefix = Path(tmp) / "page"
            result = subprocess.run(
                ["pdftoppm", "-jpeg", "-r", "150", "-f", "1", "-l", str(settings.max_pdf_pages + 1), storage_path, str(prefix)],
                capture_output=True,
                check=False,
                timeout=90,
            )
            if result.returncode != 0:
                raise InvalidReceiptFile("Unable to render PDF")
            rendered = sorted(Path(tmp).glob("page-*.jpg"))
            if len(rendered) > settings.max_pdf_pages:
                raise InvalidReceiptFile(f"PDF exceeds {settings.max_pdf_pages} pages")
            if not rendered:
                raise InvalidReceiptFile("PDF has no renderable pages")
            for page in rendered:
                pages.append((page.read_bytes(), "image/jpeg"))
            preview.write_bytes(pages[0][0])
            text_result = subprocess.run(
                ["pdftotext", "-layout", storage_path, "-"], capture_output=True, check=False, timeout=30
            )
            if text_result.returncode == 0:
                extracted_text = text_result.stdout.decode("utf-8", errors="replace")[:20_000]
            return pages, str(preview.resolve()), len(rendered), extracted_text

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((2400, 2400))
        model_buffer = io.BytesIO()
        image.save(model_buffer, format="JPEG", quality=88, optimize=True)
        pages.append((model_buffer.getvalue(), "image/jpeg"))
        thumb = image.copy()
        thumb.thumbnail((1000, 1000))
        thumb.save(preview, format="JPEG", quality=82, optimize=True)
    return pages, str(preview.resolve()), 1, ""
