from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FxRate


ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR"
LOOKBACK_DAYS = 7


def get_eur_rate(db: Session, currency: str, on_date: date) -> tuple[Decimal | None, date | None]:
    """Return the ECB reference rate (EUR per unit) for ``on_date``.

    A cached rate is reused only when it is for exactly ``on_date``. Otherwise
    ECB is queried so a newer published rate is never shadowed by an older
    cached one. When ECB is unreachable, the latest cached rate from the prior
    seven days is used instead.
    """
    currency = currency.upper()
    if currency == "EUR":
        return Decimal("1"), on_date
    cached = _latest_cached_rate(db, currency, on_date)
    if cached and cached.rate_date == on_date:
        return Decimal(cached.eur_per_unit), cached.rate_date

    try:
        observation = _fetch_latest_ecb_rate(currency, on_date)
    except (httpx.HTTPError, ValueError, ArithmeticError, csv.Error):
        observation = None
    if observation:
        rate_date, eur_per_unit = observation
        _store_rate(db, currency, rate_date, eur_per_unit)
        return eur_per_unit, rate_date
    if cached:
        return Decimal(cached.eur_per_unit), cached.rate_date
    return None, None


def _latest_cached_rate(db: Session, currency: str, on_date: date) -> FxRate | None:
    return db.scalar(
        select(FxRate)
        .where(
            FxRate.currency == currency,
            FxRate.rate_date <= on_date,
            FxRate.rate_date >= on_date - timedelta(days=LOOKBACK_DAYS),
        )
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )


def _fetch_latest_ecb_rate(currency: str, on_date: date) -> tuple[date, Decimal] | None:
    start = on_date - timedelta(days=LOOKBACK_DAYS)
    response = httpx.get(
        f"{ECB_URL}/D.{currency}.EUR.SP00.A",
        params={"startPeriod": start.isoformat(), "endPeriod": on_date.isoformat(), "format": "csvdata"},
        headers={"Accept": "text/csv"},
        timeout=15,
    )
    response.raise_for_status()
    observations: list[tuple[date, Decimal]] = []
    for row in csv.DictReader(io.StringIO(response.text)):
        if row.get("TIME_PERIOD") and row.get("OBS_VALUE"):
            observations.append((date.fromisoformat(row["TIME_PERIOD"]), Decimal(row["OBS_VALUE"])))
    if not observations:
        return None
    rate_date, foreign_per_eur = max(observations, key=lambda item: item[0])
    return rate_date, Decimal("1") / foreign_per_eur


def _store_rate(db: Session, currency: str, rate_date: date, eur_per_unit: Decimal) -> None:
    existing = db.scalar(select(FxRate).where(FxRate.currency == currency, FxRate.rate_date == rate_date))
    if existing:
        return
    db.add(FxRate(currency=currency, rate_date=rate_date, eur_per_unit=eur_per_unit))
    db.commit()
