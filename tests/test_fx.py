from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import delete

from receipt_ledger.api import startup
from receipt_ledger.database import SessionLocal
from receipt_ledger.models import FxRate
from receipt_ledger.services import fx


def _ecb_csv(rows: list[tuple[str, str]]) -> str:
    lines = ["KEY,TIME_PERIOD,OBS_VALUE"]
    for period, value in rows:
        lines.append(f"EXR.D.USD.EUR.SP00.A,{period},{value}")
    return "\n".join(lines) + "\n"


class FakeEcb:
    def __init__(self, body: str | None = None, error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls = 0

    def __call__(self, url: str, **_kwargs: object) -> httpx.Response:
        self.calls += 1
        if self.error:
            raise self.error
        return httpx.Response(200, text=self.body, request=httpx.Request("GET", url))


@pytest.fixture()
def db():
    startup()
    with SessionLocal() as session:
        session.execute(delete(FxRate))
        session.commit()
        yield session


def test_older_cached_rate_does_not_shadow_published_rate(db, monkeypatch) -> None:
    db.add(FxRate(currency="USD", rate_date=date(2026, 9, 28), eur_per_unit=Decimal("0.8")))
    db.commit()
    ecb = FakeEcb(_ecb_csv([("2026-09-28", "1.25"), ("2026-09-30", "1.1355")]))
    monkeypatch.setattr(fx.httpx, "get", ecb)

    rate, rate_date = fx.get_eur_rate(db, "USD", date(2026, 9, 30))

    assert ecb.calls == 1
    assert rate_date == date(2026, 9, 30)
    assert rate == Decimal("1") / Decimal("1.1355")


def test_exact_cached_rate_skips_network(db, monkeypatch) -> None:
    db.add(FxRate(currency="USD", rate_date=date(2026, 9, 30), eur_per_unit=Decimal("0.88")))
    db.commit()
    ecb = FakeEcb(error=AssertionError("ECB should not be called"))
    monkeypatch.setattr(fx.httpx, "get", ecb)

    rate, rate_date = fx.get_eur_rate(db, "usd", date(2026, 9, 30))

    assert ecb.calls == 0
    assert rate == Decimal("0.88")
    assert rate_date == date(2026, 9, 30)


def test_weekend_uses_previous_published_rate(db, monkeypatch) -> None:
    ecb = FakeEcb(_ecb_csv([("2026-09-24", "1.1367"), ("2026-09-25", "1.1403")]))
    monkeypatch.setattr(fx.httpx, "get", ecb)

    rate, rate_date = fx.get_eur_rate(db, "USD", date(2026, 9, 27))

    assert rate_date == date(2026, 9, 25)
    assert rate == Decimal("1") / Decimal("1.1403")
    stored = db.query(FxRate).filter_by(currency="USD", rate_date=date(2026, 9, 25)).one()
    assert Decimal(stored.eur_per_unit) == pytest.approx(rate)


def test_unreachable_ecb_falls_back_to_recent_cache(db, monkeypatch) -> None:
    db.add(FxRate(currency="USD", rate_date=date(2026, 9, 28), eur_per_unit=Decimal("0.8")))
    db.commit()
    monkeypatch.setattr(fx.httpx, "get", FakeEcb(error=httpx.ConnectError("offline")))

    assert fx.get_eur_rate(db, "USD", date(2026, 9, 30)) == (Decimal("0.8"), date(2026, 9, 28))


def test_unreachable_ecb_without_recent_cache_returns_no_rate(db, monkeypatch) -> None:
    db.add(FxRate(currency="USD", rate_date=date(2026, 9, 1), eur_per_unit=Decimal("0.8")))
    db.commit()
    monkeypatch.setattr(fx.httpx, "get", FakeEcb(error=httpx.ConnectError("offline")))

    assert fx.get_eur_rate(db, "USD", date(2026, 9, 30)) == (None, None)
