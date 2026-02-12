from __future__ import annotations

from datetime import datetime, date
from typing import Optional

import aiosqlite

from bot import dao
from bot.services.settings import get_int_setting
from bot.services.proxy_provider import ProxyProvider


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")).date()
    except Exception:
        return None


async def run_billing_once(db: aiosqlite.Connection, provider: ProxyProvider) -> bool:
    day_price = await get_int_setting(db, "proxy_day_price", 0)
    if day_price <= 0:
        return False

    today = datetime.utcnow().date()
    proxies = await dao.get_active_proxies_for_billing(db)
    changed = False
    for proxy in proxies:
        user_balance = int(proxy["user_balance"])
        user_blocked = proxy["user_blocked"] is not None
        user_deleted = proxy["user_deleted"] is not None

        if user_deleted or user_blocked:
            await provider.disable_proxy(proxy["login"])
            await dao.set_proxy_status(db, proxy["id"], "disabled")
            changed = True
            continue

        last_billed = _parse_date(proxy["last_billed_at"])
        if last_billed == today:
            continue

        if user_balance >= day_price:
            await dao.add_user_balance(db, proxy["user_id"], -day_price)
            await dao.update_proxy_last_billed(db, proxy["id"])
        else:
            await provider.disable_proxy(proxy["login"])
            await dao.set_proxy_status(db, proxy["id"], "disabled")
            await dao.update_proxy_last_billed(db, proxy["id"])
            changed = True
    return changed
