from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Dict, List

import aiosqlite

from bot import dao
from bot.services.settings import get_int_setting


@dataclass
class BillingResult:
    changed: bool
    disabled_by_balance: Dict[int, List[aiosqlite.Row]]
    low_balance_warnings: Dict[int, dict]

def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")).date()
    except Exception:
        return None


async def run_billing_once(db: aiosqlite.Connection) -> BillingResult:
    day_price = await get_int_setting(db, "proxy_day_price", 0)
    if day_price <= 0:
        return BillingResult(changed=False, disabled_by_balance={}, low_balance_warnings={})

    today = datetime.utcnow().date()
    proxies = await dao.get_active_proxies_for_billing(db)
    changed = False
    disabled_by_balance: Dict[int, List[aiosqlite.Row]] = {}
    user_state: Dict[int, dict] = {}
    for proxy in proxies:
        user_balance = int(proxy["user_balance"])
        user_blocked = proxy["user_blocked"] is not None
        user_deleted = proxy["user_deleted"] is not None
        state = user_state.setdefault(
            proxy["user_id"],
            {
                "balance": user_balance,
                "blocked": user_blocked,
                "deleted": user_deleted,
                "warn_at": proxy["user_warn_at"],
                "active_count": 0,
            },
        )
        state["active_count"] += 1

        if user_deleted or user_blocked:
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
            await dao.set_proxy_status(db, proxy["id"], "disabled")
            await dao.update_proxy_last_billed(db, proxy["id"])
            changed = True
            disabled_by_balance.setdefault(proxy["user_id"], []).append(proxy)

    low_balance_warnings: Dict[int, dict] = {}
    today_key = datetime.utcnow().date().isoformat()
    for user_id, state in user_state.items():
        if state["deleted"] or state["blocked"]:
            continue
        active_count = state["active_count"]
        if active_count <= 0:
            continue
        required = day_price * active_count
        if state["balance"] >= required:
            continue
        if state["warn_at"] == today_key:
            continue
        await dao.update_user_low_balance_warn_at(db, user_id, today_key)
        low_balance_warnings[user_id] = {
            "balance": state["balance"],
            "required": required,
            "active_count": active_count,
        }

    return BillingResult(
        changed=changed,
        disabled_by_balance=disabled_by_balance,
        low_balance_warnings=low_balance_warnings,
    )
