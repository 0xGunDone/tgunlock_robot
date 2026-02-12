from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import aiosqlite

from bot import dao


async def get_int_setting(db: aiosqlite.Connection, key: str, default: int) -> int:
    value = await dao.get_setting(db, key, str(default))
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


async def get_decimal_setting(db: aiosqlite.Connection, key: str, default: str) -> Decimal:
    value = await dao.get_setting(db, key, default)
    try:
        return Decimal(value)
    except Exception:
        return Decimal(default)


async def get_bool_setting(db: aiosqlite.Connection, key: str, default: bool) -> bool:
    value = await dao.get_setting(db, key, "1" if default else "0")
    return value == "1"


def convert_stars_to_rub(stars: int, rate: Decimal) -> int:
    amount = (Decimal(stars) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(amount)


def convert_rub_to_stars(rub: int, rate: Decimal) -> int:
    if rate == 0:
        return rub
    stars = (Decimal(rub) / rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(int(stars), 1)
