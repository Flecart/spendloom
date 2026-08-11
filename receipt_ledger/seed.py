from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting, Category, ExpenseScope, PaymentMethod


PERSONAL_CATEGORIES = [
    ("P-HOUSING", "Housing", "#6750A4", "home"),
    ("P-UTIL", "Utilities", "#625B71", "bolt"),
    ("P-GROC", "Groceries", "#386A20", "shopping_cart"),
    ("P-DINING", "Dining", "#9C4146", "restaurant"),
    ("P-TRANS", "Transport", "#006874", "directions_car"),
    ("P-TRAVEL", "Travel", "#7D5260", "flight"),
    ("P-HEALTH", "Health", "#006D3B", "health"),
    ("P-EDU", "Education", "#4F6354", "school"),
    ("P-SUB", "Subscriptions", "#735C00", "subscriptions"),
    ("P-SHOP", "Shopping", "#8E4E00", "shopping_bag"),
    ("P-ENT", "Entertainment", "#904A42", "movie"),
    ("P-GIFT", "Gifts & Donations", "#825500", "redeem"),
    ("P-FEES", "Fees", "#5F5E5E", "receipt"),
    ("P-OTHER", "Personal Other", "#777680", "category"),
]

BUSINESS_CATEGORIES = [
    ("B-COGS", "Cost of Sales", "#6750A4", "inventory"),
    ("B-OFFICE", "Office Supplies", "#006874", "work"),
    ("B-SOFTWARE", "Software & Subscriptions", "#735C00", "computer"),
    ("B-PRO", "Professional Services", "#4F6354", "business"),
    ("B-MKT", "Marketing", "#9C4146", "campaign"),
    ("B-TRAVEL", "Business Travel", "#7D5260", "flight"),
    ("B-MEALS", "Business Meals", "#8E4E00", "restaurant"),
    ("B-TRANS", "Business Transport", "#006D3B", "directions_car"),
    ("B-OCC", "Rent & Utilities", "#625B71", "home"),
    ("B-INS", "Insurance", "#386A20", "shield"),
    ("B-TRAIN", "Training", "#4F6354", "school"),
    ("B-TAX", "Taxes & Fees", "#5F5E5E", "account_balance"),
    ("B-OTHER", "Business Other", "#777680", "category"),
]


def seed_database(session: Session) -> None:
    if session.scalar(select(Category.id).limit(1)) is None:
        for code, name, color, icon in PERSONAL_CATEGORIES:
            session.add(Category(code=code, name=name, color=color, icon=icon, scope=ExpenseScope.personal))
        for code, name, color, icon in BUSINESS_CATEGORIES:
            session.add(Category(code=code, name=name, color=color, icon=icon, scope=ExpenseScope.business))

    if session.scalar(select(PaymentMethod.id).limit(1)) is None:
        session.add(PaymentMethod(name="Unknown / default", method_type="unknown", is_default=True))

    defaults = {
        "owner_name": "Owner",
        "owner_email": "",
        "review_mode": "uncertain",
        "confidence_threshold": "0.88",
        "telegram_claim_code": secrets.token_hex(3).upper(),
    }
    existing = set(session.scalars(select(AppSetting.key)).all())
    for key, value in defaults.items():
        if key not in existing:
            session.add(AppSetting(key=key, value=value))
