from __future__ import annotations

import logging
import time

from .config import get_settings
from .database import SessionLocal, init_database
from .logging_config import configure_logging
from .services.codex_cli import validate_codex_runtime
from .services.processing import process_next
from .services.chat import process_next_chat
from .services.gmail import sync_due_connection

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    validate_codex_runtime(settings)
    init_database()
    logger.info("Receipt worker started")
    while True:
        with SessionLocal() as db:
            processed = process_next(db, settings)
            chat_job = None if processed else process_next_chat(db, settings)
            sync_due_connection(db, settings)
        if processed:
            try:
                from .telegram_bot import notify_completed

                notify_completed(processed.id)
            except Exception:
                logger.exception("Unable to send Telegram completion notification")
        if chat_job and chat_job.status in {"completed", "failed"}:
            try:
                from .telegram_bot import notify_chat_completed

                notify_chat_completed(chat_job.id)
            except Exception:
                logger.exception("Unable to send Telegram chat response")
        try:
            from .telegram_bot import notify_recurring_due

            notify_recurring_due()
        except Exception:
            logger.exception("Unable to send recurring Telegram reminder")
        if not processed and not chat_job:
            time.sleep(2)


if __name__ == "__main__":
    main()
