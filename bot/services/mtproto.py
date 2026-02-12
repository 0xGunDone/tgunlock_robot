from __future__ import annotations

import asyncio
import os
from typing import Iterable

import aiosqlite

from bot import dao
from bot.runtime import runtime
from bot.services.settings import get_bool_setting
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
        return

    if current == secrets:
        return

    with open(file_path, "w", encoding="utf-8") as fh:
        for secret in secrets:
            fh.write(secret + "\n")

    await _control_mtproxy_service(config.mtproxy_service, action="restart")


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
