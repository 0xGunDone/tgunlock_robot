from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, Header

from bot import dao
from bot.config import load_config
from bot.db import get_db, init_db, ensure_default_settings
from bot.handlers import routers
from bot.runtime import runtime
from bot.services.proxy_provider import MockProxyProvider, CommandProxyProvider, DantedPamProxyProvider
from bot.services.billing import run_billing_once

config = load_config()

runtime.config = config

if config.proxy_provider == "danted":
    runtime.proxy_provider = DantedPamProxyProvider(
        default_ip=config.proxy_default_ip,
        default_port=config.proxy_default_port,
        cmd_prefix=config.proxy_cmd_prefix,
    )
elif config.proxy_provider == "command" and (
    config.proxy_cmd_create and config.proxy_cmd_update_password and config.proxy_cmd_disable
):
    runtime.proxy_provider = CommandProxyProvider(
        default_ip=config.proxy_default_ip,
        default_port=config.proxy_default_port,
        cmd_create=config.proxy_cmd_create,
        cmd_update=config.proxy_cmd_update_password,
        cmd_disable=config.proxy_cmd_disable,
    )
else:
    runtime.proxy_provider = MockProxyProvider(
        default_ip=config.proxy_default_ip,
        default_port=config.proxy_default_port,
    )

bot = Bot(token=config.bot_token)

# Dispatcher

dp = Dispatcher()
for router in routers:
    dp.include_router(router)

def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip()
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    if prefix != "/" and prefix.endswith("/"):
        prefix = prefix[:-1]
    return prefix


APP_PREFIX = _normalize_prefix(config.app_prefix)
WEBHOOK_PATH = f"{APP_PREFIX}/webhook" if APP_PREFIX else "/webhook"
HEALTH_PATH = f"{APP_PREFIX}/health" if APP_PREFIX else "/health"

app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    db = await get_db(config.db_path)
    try:
        await init_db(db)
        await ensure_default_settings(db)
    finally:
        await db.close()

    await bot.set_webhook(
        url=config.webhook_url,
        secret_token=config.webhook_secret,
        drop_pending_updates=True,
    )

    asyncio.create_task(billing_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()


@app.post(WEBHOOK_PATH)
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> Response:
    if config.webhook_secret and x_telegram_bot_api_secret_token != config.webhook_secret:
        return Response(status_code=401)

    data = await request.json()
    update = Update.model_validate(data)

    if update.update_id is not None:
        db = await get_db(config.db_path)
        try:
            inserted = await dao.insert_processed_update(db, update.update_id)
            if not inserted:
                return Response(status_code=200)
        finally:
            await db.close()

    await dp.feed_update(bot, update)
    return Response(status_code=200)


@app.get(HEALTH_PATH)
async def health() -> dict:
    return {"ok": True}


async def billing_loop() -> None:
    while True:
        db = await get_db(config.db_path)
        try:
            provider = runtime.proxy_provider
            if provider:
                await run_billing_once(db, provider)
        finally:
            await db.close()
        await asyncio.sleep(config.billing_interval_sec)
