from __future__ import annotations

import argparse
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings


def create_backup(output_dir: Path) -> Path:
    settings = get_settings()
    if not settings.resolved_database_url.startswith("sqlite:///"):
        raise RuntimeError("The built-in backup command currently supports SQLite only")
    source_db = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    if not source_db.is_file():
        raise RuntimeError(f"Database does not exist: {source_db}")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    temporary_db = output_dir / f"spendloom-{stamp}.db"
    with sqlite3.connect(source_db) as source, sqlite3.connect(temporary_db) as target:
        source.backup(target)
    archive = output_dir / f"spendloom-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(temporary_db, arcname="receipt-ledger.db")
        if settings.receipts_dir.is_dir():
            bundle.add(settings.receipts_dir, arcname="receipts")
        if settings.previews_dir.is_dir():
            bundle.add(settings.previews_dir, arcname="previews")
    temporary_db.unlink()
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a consistent Spendloom backup")
    parser.add_argument("output", nargs="?", default="./backups")
    args = parser.parse_args()
    destination = create_backup(Path(args.output))
    print(destination)


if __name__ == "__main__":
    main()
