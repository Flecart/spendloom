import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from receipt_ledger.api import startup
from receipt_ledger.config import get_settings
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import IngestionStatus
from receipt_ledger.services.ingestion import ingest_bytes
from receipt_ledger.services.storage import compress_receipt_image, prepare_visuals, sha256_bytes


def test_receipt_image_is_compressed_without_losing_stored_metadata() -> None:
    image = Image.new("RGB", (1200, 2000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    for index in range(65):
        draw.text(
            (40, 30 + index * 28),
            f"ITEM {index:02d}  1 x {index + 1}.50  TOTAL {index + 1}.50",
            font=font,
            fill="black",
        )
    upload = io.BytesIO()
    image.save(upload, format="JPEG", quality=94)
    original = upload.getvalue()

    startup()
    with SessionLocal() as db:
        ingestion = ingest_bytes(
            db,
            get_settings(),
            data=original,
            filename="detailed-receipt.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="compressed-receipt",
        )
        stored = Path(ingestion.receipt.storage_path).read_bytes()
        assert ingestion.receipt.sha256 == sha256_bytes(original)
        assert ingestion.receipt.mime_type == "image/webp"
        assert ingestion.receipt.original_filename == "detailed-receipt.webp"
        assert ingestion.receipt.size_bytes == len(stored)
        assert len(stored) < len(original) // 8
        with Image.open(io.BytesIO(stored)) as compressed:
            assert compressed.format == "WEBP"
            assert max(compressed.size) >= 1000
            assert compressed.convert("L").getextrema() == (0, 255)
        pages, preview_path, page_count, _text = prepare_visuals(
            get_settings(),
            ingestion.receipt_id,
            ingestion.receipt.storage_path,
            ingestion.receipt.mime_type,
        )
        assert page_count == 1
        assert pages[0][1] == "image/jpeg"
        assert preview_path is None
        assert not (get_settings().previews_dir / f"{ingestion.receipt_id}.jpg").exists()
        duplicate = ingest_bytes(
            db,
            get_settings(),
            data=original,
            filename="another-name.jpg",
            claimed_mime="image/jpeg",
            source="web",
            external_id="compressed-receipt-duplicate",
        )
        assert duplicate.status == IngestionStatus.duplicate
        assert duplicate.receipt_id == ingestion.receipt_id


def test_pdf_bytes_are_not_compressed() -> None:
    data = b"%PDF-1.4\n"
    assert compress_receipt_image(data, "application/pdf") == (data, "application/pdf")


def test_narrow_receipt_keeps_its_text_width() -> None:
    image = Image.new("RGB", (300, 2400), "white")
    draw = ImageDraw.Draw(image)
    for index in range(100):
        draw.text((10, index * 23), f"ITEM {index:03d}   12.50", fill="black")
    upload = io.BytesIO()
    image.save(upload, format="JPEG", quality=94)

    stored, mime_type = compress_receipt_image(upload.getvalue(), "image/jpeg")
    assert mime_type == "image/webp"
    with Image.open(io.BytesIO(stored)) as compressed:
        assert compressed.size == (300, 2400)
