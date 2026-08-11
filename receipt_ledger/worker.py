from __future__ import annotations

import logging
import time

from .config import get_settings
from .database import SessionLocal, init_database
from .services.processing import process_next
from .services.chat import process_next_chat


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    init_database()
    logging.getLogger(__name__).info("Receipt worker started")
    while True:
        with SessionLocal() as db:
            processed = process_next(db, settings)
            chat_job = None if processed else process_next_chat(db, settings)
        if processed:
            try:
                from .telegram_bot import notify_completed

                notify_completed(processed.id)
            except Exception:
                logging.getLogger(__name__).exception("Unable to send Telegram completion notification")
        if chat_job and chat_job.status in {"completed", "failed"}:
            try:
                from .telegram_bot import notify_chat_completed

                notify_chat_completed(chat_job.id)
            except Exception:
                logging.getLogger(__name__).exception("Unable to send Telegram chat response")
        if not processed and not chat_job:
            time.sleep(2)


if __name__ == "__main__":
    main()
