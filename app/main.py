from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs

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
from bot.services.mtproto import sync_mtproto_secrets, reenable_proxies_for_user
from bot.ui import send_bg_to_user
from bot.keyboards import main_menu_inline_kb
from bot.services.freekassa import verify_notification, amount_matches
from fastapi.responses import PlainTextResponse

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
WEBHOOK_ROOT = APP_PREFIX if APP_PREFIX else None
HEALTH_PATH = f"{APP_PREFIX}/health" if APP_PREFIX else "/health"
FREEKASSA_PATH = f"{APP_PREFIX}/freekassa" if APP_PREFIX else "/freekassa"

app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    db = await get_db(config.db_path)
    try:
        await init_db(db)
        await ensure_default_settings(db)
        await sync_mtproto_secrets(db)
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


async def _handle_webhook(
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


@app.post(WEBHOOK_PATH)
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> Response:
    return await _handle_webhook(request, x_telegram_bot_api_secret_token)


if WEBHOOK_ROOT:
    @app.post(WEBHOOK_ROOT)
    async def webhook_root(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(None),
    ) -> Response:
        return await _handle_webhook(request, x_telegram_bot_api_secret_token)


@app.get(HEALTH_PATH)
async def health() -> dict:
    return {"ok": True}


@app.post(FREEKASSA_PATH)
async def freekassa_webhook(request: Request) -> Response:
    if not (config.freekassa_shop_id and config.freekassa_secret2):
        return PlainTextResponse("NO", status_code=400)
    data: dict[str, str] = {}
    try:
        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
    except Exception:
        body = await request.body()
        raw = body.decode("utf-8") if body else ""
        parsed = parse_qs(raw, keep_blank_values=True)
        data = {k: v[0] for k, v in parsed.items()}
    if not verify_notification(data, config.freekassa_shop_id, config.freekassa_secret2):
        return PlainTextResponse("NO", status_code=400)

    order_id = data.get("MERCHANT_ORDER_ID") or data.get("merchant_order_id")
    amount = data.get("AMOUNT") or data.get("amount") or ""
    if not order_id or not order_id.isdigit():
        return PlainTextResponse("NO", status_code=400)

    payment_id = int(order_id)
    db = await get_db(config.db_path)
    try:
        payment = await dao.get_payment_by_id(db, payment_id)
        if not payment:
            return PlainTextResponse("NO", status_code=404)
        if payment["status"] == "paid":
            return PlainTextResponse("YES")
        if not amount_matches(payment["amount"], amount):
            await dao.update_payment_status(
                db, payment_id, "failed", provider_payment_id=f"freekassa:{payment_id}"
            )
            return PlainTextResponse("NO", status_code=400)

        await dao.update_payment_status(
            db, payment_id, "paid", provider_payment_id=f"freekassa:{payment_id}"
        )
        await dao.add_user_balance(db, payment["user_id"], payment["amount"])
        reenabled = await reenable_proxies_for_user(db, payment["user_id"])
        if reenabled:
            await sync_mtproto_secrets(db)

        user = await dao.get_user_by_id(db, payment["user_id"])
        if user:
            active = await dao.count_active_proxies(db, user_id=user["id"])
            header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
            text = (
                f"{header}\n\nБаланс пополнен на {payment['amount']} ₽.\nПрокси снова активны."
                if reenabled
                else f"{header}\n\nБаланс пополнен на {payment['amount']} ₽."
            )
            try:
                is_admin = user["tg_id"] in (runtime.config.admin_tg_ids if runtime.config else [])
                await send_bg_to_user(
                    bot,
                    db,
                    user,
                    text,
                    reply_markup=main_menu_inline_kb(is_admin),
                )
            except Exception:
                pass
    finally:
        await db.close()
    return PlainTextResponse("YES")


@app.get(FREEKASSA_PATH)
async def freekassa_webhook_status() -> Response:
    # Для проверки доступности URL со стороны FreeKassa
    return PlainTextResponse("OK")


async def billing_loop() -> None:
    while True:
        db = await get_db(config.db_path)
        try:
            result = await run_billing_once(db)
            if result.changed:
                await sync_mtproto_secrets(db)
            if result.disabled_by_balance:
                await _notify_disabled_proxies(bot, db, result.disabled_by_balance)
            if result.low_balance_warnings:
                await _notify_low_balance(bot, db, result.low_balance_warnings)
            await _check_mtproxy_health(bot)
        finally:
            await db.close()
        await asyncio.sleep(config.billing_interval_sec)


async def _check_mtproxy_health(bot: Bot) -> None:
    if not runtime.config or not runtime.config.mtproxy_service:
        return
    service = runtime.config.mtproxy_service
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "show",
            service,
            "-p",
            "ActiveState",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception:
        return
    out, _ = await proc.communicate()
    text = out.decode().strip()
    state = "unknown"
    if "=" in text:
        state = text.split("=", 1)[1].strip()

    last_state = runtime.mtproxy_last_state
    now_ts = time.time()
    last_alert = runtime.mtproxy_last_alert_ts or 0

    if state != "active":
        if last_state != state or (now_ts - last_alert) > 3600:
            runtime.mtproxy_last_state = state
            runtime.mtproxy_last_alert_ts = now_ts
            for admin_id in runtime.config.admin_tg_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"MTProxy проблема: {service} state={state}",
                        disable_notification=True,
                    )
                except Exception:
                    continue
    else:
        runtime.mtproxy_last_state = state


async def _notify_disabled_proxies(bot: Bot, db, disabled_map: dict[int, list]) -> None:
    for user_id, proxies in disabled_map.items():
        user = await dao.get_user_by_id(db, user_id)
        if not user or user["blocked_at"] or user["deleted_at"]:
            continue
        active = await dao.count_active_proxies(db, user_id=user_id)
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        lines = [header, "", "Прокси отключены из-за нехватки средств."]
        names = [p["login"] for p in proxies]
        if names:
            lines.append("Отключены: " + ", ".join(names))
        lines.append("Пополните баланс — прокси включатся автоматически.")
        try:
            await send_bg_to_user(bot, db, user, "\n".join(lines))
        except Exception:
            continue


async def _notify_low_balance(bot: Bot, db, warnings: dict[int, dict]) -> None:
    for user_id, info in warnings.items():
        user = await dao.get_user_by_id(db, user_id)
        if not user or user["blocked_at"] or user["deleted_at"]:
            continue
        active = await dao.count_active_proxies(db, user_id=user_id)
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        text = (
            f"{header}\n\n"
            "⚠️ Баланс может не хватить на следующий день.\n"
            f"Нужно: {info['required']} ₽, сейчас: {info['balance']} ₽.\n"
            "Пополните баланс, чтобы прокси не отключились."
        )
        try:
            await send_bg_to_user(bot, db, user, text)
        except Exception:
            continue
