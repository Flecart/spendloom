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
