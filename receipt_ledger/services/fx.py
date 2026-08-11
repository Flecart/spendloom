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


def get_eur_rate(db: Session, currency: str, on_date: date) -> tuple[Decimal | None, date | None]:
    currency = currency.upper()
    if currency == "EUR":
        return Decimal("1"), on_date
    cached = db.scalar(
        select(FxRate)
        .where(FxRate.currency == currency, FxRate.rate_date <= on_date)
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    if cached and cached.rate_date >= on_date - timedelta(days=7):
        return Decimal(cached.eur_per_unit), cached.rate_date

    start = on_date - timedelta(days=7)
    url = f"{ECB_URL}/D.{currency}.EUR.SP00.A"
    try:
        response = httpx.get(
            url,
            params={"startPeriod": start.isoformat(), "endPeriod": on_date.isoformat(), "format": "csvdata"},
            headers={"Accept": "text/csv"},
            timeout=15,
        )
        response.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(response.text)))
        observations: list[tuple[date, Decimal]] = []
        for row in rows:
            if row.get("TIME_PERIOD") and row.get("OBS_VALUE"):
                observations.append((date.fromisoformat(row["TIME_PERIOD"]), Decimal(row["OBS_VALUE"])))
        if not observations:
            return None, None
        rate_date, foreign_per_eur = max(observations, key=lambda item: item[0])
        eur_per_unit = Decimal("1") / foreign_per_eur
        existing = db.scalar(select(FxRate).where(FxRate.currency == currency, FxRate.rate_date == rate_date))
        if not existing:
            db.add(FxRate(currency=currency, rate_date=rate_date, eur_per_unit=eur_per_unit))
            db.commit()
        return eur_per_unit, rate_date
    except (httpx.HTTPError, ValueError, ArithmeticError, csv.Error):
        return None, None
