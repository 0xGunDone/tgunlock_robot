from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
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
from bot.services.mtproto import sync_mtproto_secrets, reenable_proxies_for_user, maybe_restart_mtproxy_service
from bot.ui import send_bg_to_user
from bot.services.settings import get_int_setting
from bot.keyboards import main_menu_inline_kb
from bot.services.freekassa import verify_notification, get_order_status
from fastapi.responses import PlainTextResponse

config = load_config()
logger = logging.getLogger(__name__)

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


async def _build_user_header(db, user_row) -> str:
    if not user_row:
        return "Баланс: 0 ₽ | Активных прокси: 0\nСтоимость/день: 0 ₽ | Хватит: —"
    active = await dao.count_active_proxies(db, user_id=user_row["id"])
    day_price = await get_int_setting(db, "proxy_day_price", 0)
    daily_cost = max(day_price, 0) * active
    if daily_cost > 0:
        days_left = int(user_row["balance"]) // daily_cost
        days_str = f"{days_left} д."
    else:
        days_str = "∞" if active > 0 and day_price == 0 else "—"
    return (
        f"Баланс: {user_row['balance']} ₽ | Активных прокси: {active}\n"
        f"Стоимость/день: {daily_cost} ₽ | Хватит: {days_str}"
    )


def _fk_status_from_data(data: dict) -> str:
    if not data:
        return "unknown"
    order = data.get("order")
    if isinstance(order, dict) and order.get("status") is not None:
        data = {**data, "_order_status": order.get("status")}
    orders = data.get("orders")
    if isinstance(orders, list) and orders:
        first = orders[0]
        if isinstance(first, dict) and first.get("status") is not None:
            data = {**data, "_orders_status": first.get("status")}
    candidates = [
        data.get("status"),
        data.get("_order_status"),
        data.get("_orders_status"),
        data.get("state"),
        data.get("paymentStatus"),
    ]
    paid = {"paid", "success", "successful", "completed", "confirm", "confirmed", "1", "2"}
    pending = {"new", "created", "pending", "wait", "waiting", "processing", "process", "0"}
    canceled = {"canceled", "cancelled", "cancel", "aborted", "void", "9", "3"}
    failed = {"failed", "fail", "error", "declined", "rejected", "8", "4"}
    for raw in candidates:
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if value in paid:
            return "paid"
        if value in canceled:
            return "canceled"
        if value in failed:
            return "failed"
        if value in pending:
            return "pending"
    return "unknown"


async def _send_payment_status_message(
    db,
    payment,
    text: str,
) -> None:
    user = await dao.get_user_by_id(db, payment["user_id"])
    if not user:
        return
    is_admin = user["tg_id"] in (runtime.config.admin_tg_ids if runtime.config else [])
    try:
        await bot.send_message(
            user["tg_id"],
            text,
            reply_markup=main_menu_inline_kb(is_admin),
            disable_web_page_preview=True,
        )
    except Exception:
        pass


async def _credit_payment_and_notify(
    db,
    payment,
    provider_payment_id: str,
) -> None:
    if payment["status"] == "paid":
        return
    await dao.update_payment_status(
        db,
        payment["id"],
        "paid",
        provider_payment_id=provider_payment_id,
    )
    await dao.add_user_balance(db, payment["user_id"], payment["amount"])
    reenabled = await reenable_proxies_for_user(db, payment["user_id"])
    if reenabled:
        await sync_mtproto_secrets(db)

    user = await dao.get_user_by_id(db, payment["user_id"])
    header = await _build_user_header(db, user)
    text = (
        f"✅ Платёж #{payment['id']}: оплачен.\n"
        f"Баланс пополнен на {payment['amount']} ₽.\n"
        f"{header}\n"
        f"{'Прокси снова активны.' if reenabled else 'Статус: paid.'}"
    )
    await _send_payment_status_message(db, payment, text)


async def _set_payment_status_and_notify(
    db,
    payment,
    status: str,
    provider_payment_id: str,
) -> None:
    if payment["status"] == status:
        return
    await dao.update_payment_status(
        db,
        payment["id"],
        status,
        provider_payment_id=provider_payment_id,
    )
    status_text = {
        "failed": "❌ Платёж #{id}: отклонён.\nСтатус: failed.",
        "canceled": "⚪️ Платёж #{id}: отменён провайдером.\nСтатус: canceled.",
    }.get(status, "Платёж #{id}: статус обновлён.")
    await _send_payment_status_message(db, payment, status_text.format(id=payment["id"]))


@app.on_event("startup")
async def on_startup() -> None:
    db = await get_db(config.db_path)
    try:
        await init_db(db)
        await ensure_default_settings(db)
        await sync_mtproto_secrets(db)
        bg_enabled = await dao.get_setting(db, "bg_enabled", "1")
        runtime.bg_enabled = str(bg_enabled) == "1"
    finally:
        await db.close()

    await bot.set_webhook(
        url=config.webhook_url,
        secret_token=config.webhook_secret,
        drop_pending_updates=True,
    )

    asyncio.create_task(billing_loop())
    asyncio.create_task(freekassa_reconcile_loop())
    asyncio.create_task(mtproxy_watchdog_loop())
    asyncio.create_task(support_sla_loop())


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
        await _credit_payment_and_notify(db, payment, provider_payment_id=f"freekassa:{payment_id}")
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
        finally:
            await db.close()
        await asyncio.sleep(config.billing_interval_sec)


async def freekassa_reconcile_loop() -> None:
    while True:
        interval = max(30, int(config.freekassa_reconcile_interval_sec))
        db = await get_db(config.db_path)
        try:
            await _reconcile_pending_freekassa(db)
        finally:
            await db.close()
        await asyncio.sleep(interval)


async def mtproxy_watchdog_loop() -> None:
    while True:
        try:
            await maybe_restart_mtproxy_service()
            await _check_mtproxy_health(bot)
        except Exception:
            pass
        await asyncio.sleep(60)


async def support_sla_loop() -> None:
    while True:
        db = await get_db(config.db_path)
        try:
            await _check_support_sla(db)
        finally:
            await db.close()
        await asyncio.sleep(300)


async def _reconcile_pending_freekassa(db) -> None:
    if not (config.freekassa_shop_id and config.freekassa_api_key):
        return
    pending = await dao.list_pending_freekassa_payments(db, limit=100)
    for payment in pending:
        try:
            data = await get_order_status(
                api_base=config.freekassa_api_base,
                api_key=config.freekassa_api_key,
                shop_id=config.freekassa_shop_id,
                payment_id=int(payment["id"]),
            )
            if data.get("error"):
                logger.warning("FreeKassa poll error payment_id=%s: %s", payment["id"], data.get("error"))
                continue
            status = _fk_status_from_data(data)
            if status == "paid":
                await _credit_payment_and_notify(
                    db,
                    payment,
                    provider_payment_id=f"freekassa:{payment['id']}",
                )
            elif status in {"failed", "canceled"}:
                await _set_payment_status_and_notify(
                    db,
                    payment,
                    status,
                    provider_payment_id=f"freekassa:{payment['id']}",
                )
        except Exception:
            logger.exception("FreeKassa reconcile failed payment_id=%s", payment["id"])
            continue
    runtime.last_freekassa_reconcile_ts = time.time()


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
            last_restart = runtime.mtproxy_last_restart_ts or 0.0
            cooldown = max(1, int(config.mtproxy_restart_cooldown_sec))
            if now_ts - last_restart >= cooldown:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "systemctl",
                        "restart",
                        service,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    runtime.mtproxy_last_restart_ts = now_ts
                except Exception:
                    pass
    else:
        runtime.mtproxy_last_state = state


async def _check_support_sla(db) -> None:
    minutes = await get_int_setting(db, "support_sla_minutes", 30)
    minutes = max(5, minutes)
    threshold = (datetime.utcnow() - timedelta(minutes=minutes)).replace(microsecond=0).isoformat() + "Z"
    now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    tickets = await dao.list_overdue_support_tickets(db, threshold)
    for ticket in tickets:
        last_alert = ticket["last_sla_alert_at"] or ""
        if last_alert:
            try:
                last_dt = datetime.fromisoformat(last_alert.replace("Z", ""))
                if datetime.utcnow() - last_dt < timedelta(hours=1):
                    continue
            except Exception:
                pass
        user_label = f"@{ticket['username']}" if ticket["username"] else f"tg:{ticket['tg_id']}"
        text = (
            f"SLA: тикет #{ticket['id']} без ответа {minutes}+ мин.\n"
            f"Пользователь: {user_label}"
        )
        targets: list[int] = []
        assigned = ticket["assigned_admin_tg_id"]
        if assigned:
            targets = [int(assigned)]
        else:
            targets = list(runtime.config.admin_tg_ids if runtime.config else [])
        for admin_id in targets:
            try:
                await bot.send_message(admin_id, text, disable_notification=True)
            except Exception:
                continue
        await dao.update_support_ticket_sla_alert_at(db, int(ticket["id"]), now_iso)


async def _notify_disabled_proxies(bot: Bot, db, disabled_map: dict[int, list]) -> None:
    for user_id, proxies in disabled_map.items():
        user = await dao.get_user_by_id(db, user_id)
        if not user or user["blocked_at"] or user["deleted_at"]:
            continue
        header = await _build_user_header(db, user)
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
        header = await _build_user_header(db, user)
        level = info.get("level", "24h")
        if level == "6h":
            title = "Критично: баланса хватит примерно на 6 часов."
        else:
            title = "Предупреждение: баланса хватит примерно на 24 часа."
        text = (
            f"{header}\n\n"
            f"{title}\n"
            f"Нужно в сутки: {info['required']} ₽, сейчас: {info['balance']} ₽.\n"
            "Пополните баланс, чтобы прокси не отключились."
        )
        try:
            await send_bg_to_user(bot, db, user, text)
        except Exception:
            continue
