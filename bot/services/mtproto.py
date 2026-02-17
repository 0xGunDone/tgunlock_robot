from __future__ import annotations

import asyncio
import os
import time
from typing import Iterable

import aiosqlite

from bot import dao
from bot.runtime import runtime
from bot.services.settings import get_bool_setting, get_int_setting
from bot.utils import generate_mtproto_secret


def _normalize_secrets(secrets: Iterable[str]) -> list[str]:
    cleaned = []
    for item in secrets:
        secret = (item or "").strip()
        if secret:
            cleaned.append(secret)
    return sorted(set(cleaned))


async def ensure_proxy_mtproto_secret(db: aiosqlite.Connection, proxy_id: int) -> str:
    proxy = await dao.get_proxy_by_id(db, proxy_id)
    if not proxy:
        return ""
    secret = proxy["mtproto_secret"] or ""
    if secret:
        return secret
    secret = generate_mtproto_secret()
    await dao.update_proxy_mtproto_secret(db, proxy_id, secret)
    return secret


async def reenable_proxies_for_user(db: aiosqlite.Connection, user_id: int) -> list[aiosqlite.Row]:
    mt_enabled = await get_bool_setting(db, "mtproto_enabled", True)
    if not mt_enabled:
        return []
    day_price = await get_int_setting(db, "proxy_day_price", 0)
    if day_price <= 0:
        return []

    user = await dao.get_user_by_id(db, user_id)
    if not user or user["deleted_at"] or user["blocked_at"]:
        return []

    if int(user["balance"]) < day_price:
        return []

    max_active = await get_int_setting(db, "max_active_proxies", 0)
    active_count = await dao.count_active_proxies(db, user_id=user_id)
    if max_active > 0:
        slots = max_active - active_count
        if slots <= 0:
            return []
    else:
        slots = 10**9

    cur = await db.execute(
        "SELECT * FROM proxies WHERE user_id = ? AND status = 'disabled' AND deleted_at IS NULL ORDER BY created_at",
        (user_id,),
    )
    disabled = await cur.fetchall()
    if not disabled:
        return []

    to_enable = disabled[:slots]
    for proxy in to_enable:
        await dao.set_proxy_status(db, proxy["id"], "active")
        await dao.update_proxy_last_billed(db, proxy["id"])

    await sync_mtproto_secrets(db)
    return to_enable


async def sync_mtproto_secrets(db: aiosqlite.Connection) -> None:
    config = runtime.config
    if config is None:
        return

    enabled = await get_bool_setting(db, "mtproto_enabled", False)
    secrets: list[str] = []
    if enabled:
        proxies = await dao.list_active_proxies(db)
        for proxy in proxies:
            secret = proxy["mtproto_secret"] or ""
            if not secret:
                secret = generate_mtproto_secret()
                await dao.update_proxy_mtproto_secret(db, proxy["id"], secret)
            secrets.append(secret)

    secrets = _normalize_secrets(secrets)
    file_path = config.mtproxy_secrets_file
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    current: list[str] = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as fh:
            current = _normalize_secrets([line.strip() for line in fh.readlines()])

    if not enabled or not secrets:
        if current:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write("")
        await _control_mtproxy_service(config.mtproxy_service, action="stop")
        runtime.mtproxy_restart_required = False
        return

    if current == secrets:
        return

    with open(file_path, "w", encoding="utf-8") as fh:
        for secret in secrets:
            fh.write(secret + "\n")
    now_ts = time.time()
    last_restart = runtime.mtproxy_last_restart_ts or 0.0
    cooldown = max(1, int(config.mtproxy_restart_cooldown_sec))
    if now_ts - last_restart < cooldown:
        runtime.mtproxy_restart_required = True
        return
    await _control_mtproxy_service(config.mtproxy_service, action="restart")
    runtime.mtproxy_last_restart_ts = now_ts
    runtime.mtproxy_restart_required = False


async def maybe_restart_mtproxy_service() -> bool:
    config = runtime.config
    if config is None or not runtime.mtproxy_restart_required:
        return False
    now_ts = time.time()
    last_restart = runtime.mtproxy_last_restart_ts or 0.0
    cooldown = max(1, int(config.mtproxy_restart_cooldown_sec))
    if now_ts - last_restart < cooldown:
        return False
    await _control_mtproxy_service(config.mtproxy_service, action="restart")
    runtime.mtproxy_last_restart_ts = now_ts
    runtime.mtproxy_restart_required = False
    return True


async def _control_mtproxy_service(service_name: str | None, action: str) -> None:
    if not service_name:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            action,
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception:
        return
