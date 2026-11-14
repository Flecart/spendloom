from types import SimpleNamespace

from receipt_ledger.api import startup
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import AppSetting
from receipt_ledger.telegram_bot import TelegramBot


def make_bot(allowed_user_id: str) -> TelegramBot:
    bot = TelegramBot.__new__(TelegramBot)
    bot.settings = SimpleNamespace(telegram_allowed_user_id=allowed_user_id)
    bot.messages = []
    bot.send = lambda chat_id, message, **_kwargs: bot.messages.append((chat_id, message))
    return bot


def test_allowlist_claims_and_recovers_existing_owner() -> None:
    startup()
    with SessionLocal.begin() as db:
        for key in ("telegram_owner_id", "telegram_claim_code"):
            setting = db.get(AppSetting, key)
            if setting:
                db.delete(setting)

    bot = make_bot("42")
    bot.handle_claim(99, 7, "/claim ANYCODE")
    with SessionLocal() as db:
        assert db.get(AppSetting, "telegram_owner_id") is None

    bot.handle_claim(99, 42, "/claim")
    assert bot.is_owner(42)
    assert not bot.is_owner(7)

    # A copied database may contain a stale owner. The configured account can
    # reclaim it, while no other Telegram account can.
    with SessionLocal.begin() as db:
        db.get(AppSetting, "telegram_owner_id").value = "7"
    assert not bot.is_owner(7)
    bot.handle_claim(99, 42, "/claim")
    assert bot.is_owner(42)
    assert any("reassigned" in message for _, message in bot.messages)


def test_media_update_without_text_reaches_attachment_handler() -> None:
    bot = make_bot("42")
    attachments = []
    bot.is_owner = lambda user_id: user_id == 42
    bot.handle_attachment = lambda chat_id, user_id, message: attachments.append((chat_id, user_id, message))
    bot.handle_update({"message": {"chat": {"id": 99, "type": "private"}, "from": {"id": 42}, "photo": [{"file_id": "x"}]}})
    assert attachments == [(99, 42, {"chat": {"id": 99, "type": "private"}, "from": {"id": 42}, "photo": [{"file_id": "x"}]})]


def test_failed_update_notifies_chat_and_advances_offset() -> None:
    bot = make_bot("42")
    saved_offsets = []
    bot.handle_update = lambda _update: (_ for _ in ()).throw(RuntimeError("broken update"))
    bot.save_offset = saved_offsets.append

    bot.process_update({"update_id": 12, "message": {"chat": {"id": 99, "type": "private"}}})

    assert saved_offsets == [13]
    assert bot.messages == [(99, "Sorry — Spendloom hit an error while handling that message. Please try again.")]


class FlakyTelegramClient:
    """Fake httpx client: fails the first `failures` getFile calls with a timeout."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[str] = []

    def post(self, url: str, **_kwargs):
        import httpx

        self.calls.append(url)
        if self.failures > 0:
            self.failures -= 1
            raise httpx.ReadTimeout("The read operation timed out")
        return httpx.Response(
            200,
            json={"ok": True, "result": {"file_path": "photos/receipt.jpg"}},
            request=httpx.Request("POST", url),
        )

    def get(self, url: str, **_kwargs):
        import httpx

        self.calls.append(url)
        return httpx.Response(200, content=b"receipt-bytes", request=httpx.Request("GET", url))


def make_download_bot(failures: int) -> TelegramBot:
    bot = make_bot("42")
    bot.base_url = "https://telegram.test/bot"
    bot.file_url = "https://telegram.test/file/bot"
    bot.client = FlakyTelegramClient(failures)
    bot.FILE_FETCH_RETRY_DELAYS = (0, 0)
    return bot


def test_file_download_retries_transient_timeouts() -> None:
    bot = make_download_bot(failures=2)

    assert bot.download_file("abc") == b"receipt-bytes"
    assert bot.client.calls == [
        "https://telegram.test/bot/getFile",
        "https://telegram.test/bot/getFile",
        "https://telegram.test/bot/getFile",
        "https://telegram.test/file/bot/photos/receipt.jpg",
    ]


def test_file_download_gives_up_after_last_attempt() -> None:
    import httpx
    import pytest

    bot = make_download_bot(failures=3)

    with pytest.raises(httpx.ReadTimeout):
        bot.download_file("abc")
    assert len(bot.client.calls) == 3
