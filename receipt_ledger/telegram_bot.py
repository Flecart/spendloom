from __future__ import annotations

import html
import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal, init_database
from .models import AppSetting, ChatJob, Expense, Ingestion, IngestionStatus
from .services.chat import (
    attach_processed_expense,
    anchor_receipt,
    consume_pending_action,
    context_status,
    export_csv_bytes,
    queue_chat_job,
    reset_context,
)
from .services.ingestion import ingest_bytes
from .services.storage import ALLOWED_MIMES, InvalidReceiptFile

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        self.base_url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        self.file_url = f"https://api.telegram.org/file/bot{self.settings.telegram_bot_token}"
        self.client = httpx.Client(timeout=httpx.Timeout(45, connect=15))

    def api(self, method: str, payload: dict | None = None) -> dict:
        response = self.client.post(f"{self.base_url}/{method}", json=payload or {})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram method {method} failed")
        return body["result"]

    def send(self, chat_id: int | str, text: str, buttons: list[list[dict]] | None = None) -> None:
        """Escape model output and obey Telegram's 4096-character limit."""
        try:
            escaped = html.escape(text, quote=False)
            chunks: list[str] = []
            while escaped:
                if len(escaped) <= 4096:
                    chunks.append(escaped)
                    break
                cut = escaped.rfind("\n", 0, 4096)
                if cut < 1:
                    cut = 4096
                chunks.append(escaped[:cut])
                escaped = escaped[cut:].lstrip("\n")
            for index, chunk in enumerate(chunks or [" "]):
                payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
                if buttons and index == len(chunks) - 1:
                    payload["reply_markup"] = {"inline_keyboard": buttons}
                self.api("sendMessage", payload)
        except Exception:
            logger.exception("Unable to send Telegram acknowledgement")

    def send_document(self, chat_id: int | str, filename: str, content: bytes) -> None:
        try:
            response = self.client.post(
                f"{self.base_url}/sendDocument",
                data={"chat_id": str(chat_id)},
                files={"document": (filename, content, "text/csv")},
            )
            response.raise_for_status()
        except Exception:
            logger.exception("Unable to send Telegram CSV export")

    def answer_callback(self, callback_id: str) -> None:
        try:
            self.api("answerCallbackQuery", {"callback_query_id": callback_id})
        except Exception:
            logger.exception("Unable to answer Telegram callback")

    def run(self) -> None:
        init_database()
        self.api("deleteWebhook", {"drop_pending_updates": False})
        logger.info("Telegram receipt bot started in long-polling mode")
        while True:
            try:
                with SessionLocal() as db:
                    offset_setting = db.get(AppSetting, "telegram_update_offset")
                    offset = int(offset_setting.value) if offset_setting else 0
                updates = self.api("getUpdates", {
                    "offset": offset,
                    "timeout": self.settings.telegram_poll_timeout,
                    "allowed_updates": ["message", "callback_query"],
                })
                for update in updates:
                    self.handle_update(update)
                    self.save_offset(int(update["update_id"]) + 1)
            except httpx.HTTPError:
                logger.warning("Telegram connection failed; retrying")
                time.sleep(5)
            except Exception:
                logger.exception("Telegram polling loop failed; retrying")
                time.sleep(5)

    def save_offset(self, offset: int) -> None:
        with SessionLocal.begin() as db:
            item = db.get(AppSetting, "telegram_update_offset")
            if item:
                item.value = str(offset)
            else:
                db.add(AppSetting(key="telegram_update_offset", value=str(offset)))

    def handle_update(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            self.handle_callback(callback)
            return
        message = update.get("message")
        if not message:
            return
        chat = message.get("chat", {})
        sender = message.get("from", {})
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if chat.get("type") != "private" or not chat_id or not user_id:
            return
        text = (message.get("text") or "").strip()
        if text.split(maxsplit=1)[0] == "/id":
            self.send(chat_id, f"Your Telegram user ID is: {user_id}")
            return
        if text.startswith("/claim"):
            self.handle_claim(chat_id, user_id, text)
            return
        if not self.is_owner(user_id):
            self.send(chat_id, "This is a private Spendloom bot. Claim it from the local Spendloom settings page first.")
            return
        if text.startswith("/start") or text.startswith("/help"):
            self.send(chat_id, "Send a receipt photo or PDF and I’ll add it to Spendloom. You can also ask about spending or ask me to correct a receipt. Commands: /new, /context, /recent, /status <id>, /cancel <id>.")
            return
        if text.startswith("/new"):
            reset_context_for_chat(chat_id, user_id)
            self.send(chat_id, "Started a fresh conversation. Your expenses and receipts are unchanged.")
            return
        if text.startswith("/context"):
            self.handle_context(chat_id, user_id)
            return
        if text.startswith("/recent"):
            self.handle_recent(chat_id)
            return
        if text.startswith("/status"):
            self.handle_status(chat_id, text)
            return
        if text.startswith("/cancel"):
            self.handle_cancel(chat_id, text)
            return
        if text:
            self.handle_chat_message(chat_id, user_id, message)
            return
        self.handle_attachment(chat_id, user_id, message)

    def handle_callback(self, callback: dict) -> None:
        self.answer_callback(str(callback.get("id") or ""))
        message, sender = callback.get("message") or {}, callback.get("from") or {}
        chat_id, user_id = (message.get("chat") or {}).get("id"), sender.get("id")
        if not chat_id or not user_id or not self.is_owner(user_id):
            return
        data = str(callback.get("data") or "")
        parts = data.split(":", 2)
        if len(parts) != 3 or parts[0] != "spendloom" or parts[1] not in {"confirm", "cancel"}:
            self.send(chat_id, "That action is no longer available.")
            return
        with SessionLocal() as db:
            result = consume_pending_action(db, parts[2], chat_id, user_id, parts[1] == "confirm")
        self.send(chat_id, result)

    def is_owner(self, user_id: int) -> bool:
        if not self.is_allowed_user(user_id):
            return False
        with SessionLocal() as db:
            owner = db.get(AppSetting, "telegram_owner_id")
            return bool(owner and secrets.compare_digest(owner.value, str(user_id)))

    def is_allowed_user(self, user_id: int) -> bool:
        allowed = (self.settings.telegram_allowed_user_id or "").strip()
        return not allowed or secrets.compare_digest(allowed.strip(), str(user_id))

    def handle_claim(self, chat_id: int, user_id: int, text: str) -> None:
        supplied = text.partition(" ")[2].strip().upper()
        if not self.is_allowed_user(user_id):
            self.send(chat_id, "This bot is restricted to its configured Telegram account.")
            return
        with SessionLocal.begin() as db:
            owner = db.get(AppSetting, "telegram_owner_id")
            claim = db.get(AppSetting, "telegram_claim_code")
            if owner:
                # An explicit allowlist is authoritative. This also recovers a
                # database copied from a host where the bot was claimed by the
                # wrong account; no unlisted Telegram account can trigger it.
                if self.settings.telegram_allowed_user_id and not secrets.compare_digest(owner.value, str(user_id)):
                    owner.value = str(user_id)
                    if claim:
                        claim.value = secrets.token_hex(3).upper()
                    else:
                        db.add(AppSetting(key="telegram_claim_code", value=secrets.token_hex(3).upper()))
                    self.send(chat_id, "Spendloom access has been reassigned to your allowlisted Telegram account.")
                    return
                self.send(chat_id, "This Spendloom bot has already been claimed.")
                return
            # A configured Telegram ID is stronger than a shareable setup code:
            # Telegram authenticates the sender ID for every update, and this
            # branch never accepts another account's claim even if it learns a
            # stale claim code.
            if self.settings.telegram_allowed_user_id:
                db.add(AppSetting(key="telegram_owner_id", value=str(user_id)))
                if claim:
                    claim.value = secrets.token_hex(3).upper()
                else:
                    db.add(AppSetting(key="telegram_claim_code", value=secrets.token_hex(3).upper()))
                self.send(chat_id, "Spendloom is linked to your allowlisted Telegram account.")
                return
            if not supplied or not claim or not secrets.compare_digest(supplied, claim.value.upper()):
                self.send(chat_id, "Invalid claim code. Get the current code from Spendloom Settings → Telegram, or configure TELEGRAM_ALLOWED_USER_ID and send /claim.")
                return
            db.add(AppSetting(key="telegram_owner_id", value=str(user_id)))
            claim.value = secrets.token_hex(3).upper()
        self.send(chat_id, "Spendloom is now linked to this Telegram account. Send a photo or PDF whenever you have a receipt.")

    def handle_chat_message(self, chat_id: int, user_id: int, message: dict) -> None:
        text = str(message.get("text") or "").strip()
        if not text:
            return
        with SessionLocal() as db:
            job = queue_chat_job(db, chat_id, user_id, message.get("message_id"), text)
        if job.status == "queued":
            self.send(chat_id, "Thinking…")

    def handle_context(self, chat_id: int, user_id: int) -> None:
        with SessionLocal() as db:
            state = context_status(db, chat_id, user_id)
        active = state["expense_id"] or state["ingestion_id"] or "none"
        self.send(chat_id, f"Active receipt/expense: {active}\nRetained messages: {state['retained_messages']} of {16} maximum.")

    def handle_attachment(self, chat_id: int, user_id: int, message: dict) -> None:
        document = message.get("document")
        photos = message.get("photo") or []
        if document:
            file_id = document.get("file_id")
            unique_id = document.get("file_unique_id")
            filename = document.get("file_name") or "receipt"
            mime = document.get("mime_type") or "application/octet-stream"
            size = int(document.get("file_size") or 0)
        elif photos:
            photo = max(photos, key=lambda item: int(item.get("file_size") or 0))
            file_id = photo.get("file_id")
            unique_id = photo.get("file_unique_id")
            filename = f"telegram-{message.get('message_id')}.jpg"
            mime = "image/jpeg"
            size = int(photo.get("file_size") or 0)
        else:
            if message.get("text"):
                self.send(chat_id, "I support receipt photos (JPEG, PNG, WebP, HEIC) and PDFs. Voice notes and other documents aren’t supported yet.")
            else:
                self.send(chat_id, "I support receipt photos (JPEG, PNG, WebP, HEIC) and PDFs. Voice notes and other documents aren’t supported yet.")
            return
        if mime not in ALLOWED_MIMES:
            self.send(chat_id, "Unsupported file. Please send JPEG, PNG, WebP, HEIC, or PDF.")
            return
        if size > 20 * 1024 * 1024:
            self.send(chat_id, "Telegram bots can only download files up to 20 MB. Upload this receipt through the web app instead.")
            return
        try:
            file_info = self.api("getFile", {"file_id": file_id})
            response = self.client.get(f"{self.file_url}/{file_info['file_path']}", timeout=45)
            response.raise_for_status()
            external_id = f"{chat_id}:{message.get('message_id')}:{unique_id}"
            with SessionLocal() as db:
                ingestion = ingest_bytes(
                    db,
                    self.settings,
                    data=response.content,
                    filename=filename,
                    claimed_mime=mime,
                    source="telegram",
                    external_id=external_id,
                    caption=message.get("caption"),
                    source_user_id=str(user_id),
                    source_chat_id=str(chat_id),
                )
                anchor_receipt(db, chat_id, user_id, ingestion.id, ingestion.expense_id)
            if ingestion.status == IngestionStatus.duplicate:
                self.send(chat_id, f"Already saved — duplicate receipt ({ingestion.id}).")
            else:
                self.send(chat_id, f"Receipt saved and queued. ID: {ingestion.id}\nI’ve started a fresh receipt context, so follow-ups like “make that business” will apply to this receipt once it finishes.")
        except InvalidReceiptFile as exc:
            self.send(chat_id, f"I couldn’t save that receipt: {exc}")
        except Exception:
            logger.exception("Telegram attachment ingestion failed")
            self.send(chat_id, "I couldn’t save that receipt. Please try again or use the web upload.")

    def _find_ingestion(self, db, token: str) -> Ingestion | None:
        token = token.strip()
        if not token:
            return None
        return db.scalar(select(Ingestion).where(Ingestion.id.like(f"{token}%")).order_by(Ingestion.received_at.desc()))

    def handle_status(self, chat_id: int, text: str) -> None:
        token = text.partition(" ")[2]
        with SessionLocal() as db:
            item = self._find_ingestion(db, token)
            if not item:
                self.send(chat_id, "Receipt ID not found. Use /status <id>.")
                return
            detail = f" — {item.error_message}" if item.error_message else ""
            self.send(chat_id, f"{item.id}: {item.status.value}{detail}")

    def handle_recent(self, chat_id: int) -> None:
        with SessionLocal() as db:
            items = db.scalars(select(Ingestion).where(Ingestion.source == "telegram").order_by(Ingestion.received_at.desc()).limit(5)).all()
            if not items:
                self.send(chat_id, "No Telegram receipts yet.")
                return
            self.send(chat_id, "Recent receipts:\n" + "\n".join(f"{item.id[:8]} — {item.status.value}" for item in items))

    def handle_cancel(self, chat_id: int, text: str) -> None:
        token = text.partition(" ")[2]
        with SessionLocal.begin() as db:
            item = self._find_ingestion(db, token)
            if not item:
                self.send(chat_id, "Receipt ID not found.")
                return
            if item.status != IngestionStatus.queued:
                self.send(chat_id, f"Cannot cancel a receipt in state {item.status.value}.")
                return
            item.status = IngestionStatus.cancelled
        self.send(chat_id, "Receipt processing cancelled. The original remains safely stored.")


def notify_completed(ingestion_id: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    with SessionLocal() as db:
        item = db.get(Ingestion, ingestion_id)
        if not item or item.source != "telegram" or not item.source_chat_id or item.notification_sent_at:
            return
        expense = db.get(Expense, item.expense_id) if item.expense_id else None
        attach_processed_expense(db, item)
        if item.status == IngestionStatus.accepted and expense:
            text = receipt_summary(item, expense)
        elif item.status in {IngestionStatus.needs_review, IngestionStatus.duplicate}:
            text = receipt_summary(item, expense) if expense else f"Receipt {item.id[:8]} needs review in Spendloom ({item.status.value.replace('_', ' ')})."
        elif item.status == IngestionStatus.failed:
            text = f"Receipt {item.id[:8]} failed to process. The original is stored; review it in Spendloom."
        else:
            return
        bot = TelegramBot()
        bot.send(item.source_chat_id, text)
        item.notification_sent_at = time_to_datetime()
        db.commit()


def reset_context_for_chat(chat_id: int, user_id: int) -> None:
    with SessionLocal() as db:
        reset_context(db, chat_id, user_id)


def receipt_summary(item: Ingestion, expense: Expense) -> str:
    category = expense.category.name if expense.category else "Uncategorized"
    payment = expense.payment_method.name if expense.payment_method else "Not set"
    original = f"{expense.original_amount} {expense.original_currency}" if expense.original_amount is not None else "unknown"
    eur = f"€{expense.amount}" if expense.amount is not None else "unknown"
    reason = expense.category_reason or "No category reason provided."
    source = {"ai": "AI", "merchant_rule": "merchant rule", "manual": "manual"}.get(expense.categorization_source, expense.categorization_source)
    confidence = f"{float(expense.confidence or 0):.0%}"
    return (
        f"Receipt {item.status.value.replace('_', ' ')}\n"
        f"Merchant: {expense.merchant or 'Unknown'}\nDate: {expense.expense_date.isoformat() if expense.expense_date else 'Unknown'}\n"
        f"Original: {original}\nEUR: {eur}\nCategory: {category}\nScope: {expense.scope.value}\n"
        f"Payment: {payment}\nConfidence: {confidence}\nCategorized by: {source}\nReason: {reason}\nReceipt ID: {item.id}"
    )


def notify_chat_completed(job_id: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    with SessionLocal() as db:
        job = db.get(ChatJob, job_id)
        if not job or job.status not in {"completed", "failed"} or job.response_sent_at:
            return
        bot = TelegramBot()
        buttons = None
        if job.pending_action_token:
            buttons = [[
                {"text": "Confirm", "callback_data": f"spendloom:confirm:{job.pending_action_token}"},
                {"text": "Cancel", "callback_data": f"spendloom:cancel:{job.pending_action_token}"},
            ]]
        bot.send(job.telegram_chat_id, job.response_text or "Done.", buttons)
        if job.export_request:
            content, filename = export_csv_bytes(db, job.export_request)
            bot.send_document(job.telegram_chat_id, filename, content)
        job.response_sent_at = datetime.now(timezone.utc)
        db.commit()


def time_to_datetime():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    TelegramBot().run()


if __name__ == "__main__":
    main()
