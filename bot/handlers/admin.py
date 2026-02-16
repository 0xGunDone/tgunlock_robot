from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
import asyncio
import os
import re
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from bot import dao
from bot.db import get_db
from bot.handlers.states import AdminStates
from bot.keyboards import (
    admin_menu_inline_kb,
    main_menu_inline_kb,
    broadcast_filters_kb,
    admin_user_actions_kb,
    admin_settings_kb,
    admin_referrals_kb,
    admin_referrals_list_kb,
    admin_ref_delete_confirm_kb,
    mtproxy_status_kb,
    freekassa_status_kb,
    admin_users_kb,
    admin_users_list_kb,
    admin_export_kb,
    support_admin_reply_kb,
    admin_user_proxies_kb,
    admin_support_list_kb,
    support_admin_ticket_kb_ext,
)
from bot.runtime import runtime
from bot.ui import send_or_edit_bg_message, send_bg_to_user
from bot.services.mtproto import sync_mtproto_secrets, reenable_proxies_for_user
from bot.services.freekassa import get_currencies
from bot.services.settings import get_int_setting

router = Router()


def _is_admin(user_id: int) -> bool:
    config = runtime.config
    if config is None:
        return False
    return user_id in config.admin_tg_ids


def _require_admin(message: Message) -> bool:
    if not _is_admin(message.from_user.id):
        return False
    return True


async def _safe_edit(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    await send_or_edit_bg_message(
        call.message.bot,
        call.message.chat.id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        message_id=call.message.message_id,
    )


async def _admin_send_or_edit(message: Message, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    config = runtime.config
    if config is None:
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id_any(db, message.from_user.id)
        last_id = user["last_menu_message_id"] if user and user["last_menu_message_id"] else None
        msg_id = await send_or_edit_bg_message(
            message.bot,
            message.chat.id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            message_id=last_id,
        )
        await dao.update_user_last_menu_message_id(db, message.from_user.id, msg_id)
    finally:
        await db.close()


def _settings_text(settings_map: dict[str, str]) -> str:
    def val(key: str, default: str = "") -> str:
        return settings_map.get(key, default)

    def onoff(key: str, default: str = "0") -> str:
        return "Вкл" if val(key, default) == "1" else "Выкл"

    lines = [
        "Настройки:",
        f"Цена создания: {val('proxy_create_price', '0')} ₽",
        f"Цена в день: {val('proxy_day_price', '0')} ₽",
        f"Free credit: {val('free_credit', '0')} ₽",
        f"Лимит прокси: {val('max_active_proxies', '0')}",
        f"Курс Stars: {val('stars_rate', '1')} ₽/⭐",
        f"Stars: {onoff('stars_enabled', '1')}",
        f"FreeKassa: {onoff('freekassa_enabled', '0')}",
        f"Фон: {onoff('bg_enabled', '1')}",
        f"Оферта: {onoff('offer_enabled', '1')}",
        f"Политика: {onoff('policy_enabled', '1')}",
        f"FK СБП: {onoff('freekassa_method_44_enabled', '1')}",
        f"FK Карта: {onoff('freekassa_method_36_enabled', '1')}",
        f"FK SberPay: {onoff('freekassa_method_43_enabled', '1')}",
        f"Подсказка Stars: {onoff('stars_buy_hint_enabled', '0')}",
        f"URL Stars: {val('stars_buy_url', '') or '—'}",
        f"URL Оферта: {val('offer_url', '') or '—'}",
        f"URL Политика: {val('policy_url', '') or '—'}",
        f"Рефералка: {onoff('referral_enabled', '1')}",
        f"Бонус пригл.: {val('ref_bonus_inviter', '0')} ₽",
        f"Бонус приглаш.: {val('ref_bonus_invited', '0')} ₽",
        f"MTProto: {onoff('mtproto_enabled', '1')}",
        f"MTProto host: {val('mtproto_host', '') or '—'}",
        f"MTProto port: {val('mtproto_port', '9443')}",
    ]
    return "\n".join(lines)


def _pick_val(item: dict, *keys: str, default: str = "—") -> str:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return str(item[key])
    return default


def _support_user_label(username: str | None, tg_id: int) -> str:
    if username:
        return f"@{username}"
    return f"tg:{tg_id}"


async def _user_header(db, user_row) -> str:
    if not user_row:
        return "Баланс: 0 ₽"
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


async def _freekassa_status_text(db) -> str:
    config = runtime.config
    if config is None:
        return "FreeKassa: конфиг не загружен."
    settings_map = await dao.get_settings_map(db)
    enabled = settings_map.get("freekassa_enabled", "0")
    lines = [
        "FreeKassa:",
        f"Включено: {'да' if enabled == '1' else 'нет'}",
        f"Shop ID: {config.freekassa_shop_id or '—'}",
        f"API base: {config.freekassa_api_base or '—'}",
    ]
    if not config.freekassa_shop_id or not config.freekassa_api_key:
        lines.append("API ключ или Shop ID не заданы.")
        return "\n".join(lines)

    data = await get_currencies(
        api_base=config.freekassa_api_base,
        api_key=config.freekassa_api_key,
        shop_id=config.freekassa_shop_id,
    )
    if data.get("error"):
        lines.append(f"Ошибка /currencies: {data['error']}")
        return "\n".join(lines)

    items = data.get("currencies") or data.get("data") or []
    if not items:
        lines.append("Список методов пуст.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Методы (id | currency | enabled | name | fields):")
    max_items = 20
    for item in items[:max_items]:
        item_id = _pick_val(item, "id", "currency_id", "method_id")
        currency = _pick_val(item, "currency", "cur")
        enabled = _pick_val(item, "is_enabled", "enabled")
        name = _pick_val(item, "name", "title", "method")
        fields = item.get("fields") or []
        fields_count = len(fields) if isinstance(fields, list) else (1 if fields else 0)
        lines.append(f"{item_id} | {currency} | {enabled} | {name} | fields={fields_count}")
    if len(items) > max_items:
        lines.append(f"... ещё {len(items) - max_items}")
    return "\n".join(lines)


async def _systemctl_props(service: str) -> dict[str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "show",
            service,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "Result",
            "-p",
            "ExecMainStatus",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception:
        return {}
    out, _ = await proc.communicate()
    text = out.decode().strip()
    props: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value
    return props


async def _get_mtproxy_logs(service: str, lines: int = 50) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl",
            "-u",
            service,
            "-n",
            str(lines),
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception:
        return "journalctl недоступен."
    out, err = await proc.communicate()
    if proc.returncode != 0:
        msg = err.decode().strip() or "Не удалось получить логи."
        return msg
    text = out.decode().strip()
    return text or "Логи пустые."


async def _mtproxy_status_text(db) -> str:
    config = runtime.config
    if config is None:
        return "Конфигурация не загружена."

    mt_enabled = await dao.get_setting(db, "mtproto_enabled", "1")
    host = await dao.get_setting(db, "mtproto_host", "") or config.proxy_default_ip
    port = await dao.get_setting(db, "mtproto_port", "9443")

    secrets_file = config.mtproxy_secrets_file
    secrets_count = 0
    if os.path.exists(secrets_file):
        with open(secrets_file, "r", encoding="utf-8") as fh:
            secrets_count = len([line for line in fh.readlines() if line.strip()])

    active_proxies = await dao.count_active_proxies(db)

    service = config.mtproxy_service or ""
    props = await _systemctl_props(service) if service else {}
    state = props.get("ActiveState", "unknown") if props else "unknown"
    substate = props.get("SubState", "")
    result = props.get("Result", "")
    exec_status = props.get("ExecMainStatus", "")

    lines = [
        "MTProxy статус:",
        f"Сервис: {service or 'не задан'}",
        f"Состояние: {state}{f' / {substate}' if substate else ''}",
    ]
    if state != "active":
        extra = []
        if result:
            extra.append(f"Result={result}")
        if exec_status and exec_status != "0":
            extra.append(f"Exit={exec_status}")
        if extra:
            lines.append("Ошибка: " + ", ".join(extra))

    lines += [
        f"MTProto в боте: {'Вкл' if mt_enabled == '1' else 'Выкл'}",
        f"Host: {host}",
        f"Port: {port}",
        f"Файл секретов: {secrets_file}",
        f"Секретов в файле: {secrets_count}",
        f"Активных прокси в БД: {active_proxies}",
    ]
    if mt_enabled == "1" and secrets_count != active_proxies:
        lines.append("Внимание: число секретов не совпадает с активными прокси.")
    return "\n".join(lines)


async def _admin_proxy_links_text(db, proxy) -> str:
    mt_enabled = await dao.get_setting(db, "mtproto_enabled", "1")
    if mt_enabled != "1":
        return "MTProto отключён."
    host = await dao.get_setting(db, "mtproto_host", "") or runtime.config.proxy_default_ip
    port = await dao.get_setting(db, "mtproto_port", "9443")
    secret = proxy["mtproto_secret"] or ""
    if not secret:
        return "Secret отсутствует."
    return f"https://t.me/proxy?server={host}&port={port}&secret={secret}"


@router.message(Command("admin"))
async def admin_start(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    await state.clear()
    await _admin_send_or_edit(message, "Админка", reply_markup=admin_menu_inline_kb())


@router.callback_query(F.data == "menu:admin")
async def admin_menu(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    await _safe_edit(call, "Админка", reply_markup=admin_menu_inline_kb())


@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        total_users = await dao.count_users(db)
        active_7 = await dao.count_active_users(db, 7)
        active_proxies = await dao.count_active_proxies(db)

        since_day = (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat() + "Z"
        since_week = (datetime.utcnow() - timedelta(days=7)).replace(microsecond=0).isoformat() + "Z"
        since_month = (datetime.utcnow() - timedelta(days=30)).replace(microsecond=0).isoformat() + "Z"

        sum_day = await dao.get_payments_sum(db, since_day)
        sum_week = await dao.get_payments_sum(db, since_week)
        sum_month = await dao.get_payments_sum(db, since_month)

        avg_balance = 0
        cur = await db.execute("SELECT AVG(balance) AS avg_balance FROM users WHERE deleted_at IS NULL")
        row = await cur.fetchone()
        if row and row["avg_balance"] is not None:
            avg_balance = int(row["avg_balance"])

        cur = await db.execute(
            "SELECT COUNT(*) AS cnt FROM proxies WHERE status = 'disabled' AND deleted_at IS NULL"
        )
        row = await cur.fetchone()
        disabled_count = int(row["cnt"])
        cur = await db.execute(
            "SELECT COUNT(DISTINCT user_id) AS cnt FROM proxies WHERE status = 'active' AND deleted_at IS NULL"
        )
        row = await cur.fetchone()
        users_with_active = int(row["cnt"])

        await _safe_edit(
            call,
            "Статистика:\n"
            f"Всего пользователей: {total_users}\n"
            f"Активные за 7 дней: {active_7}\n"
            f"Пользователи с активными прокси: {users_with_active}\n"
            f"Активных прокси: {active_proxies}\n"
            f"Отключённых прокси: {disabled_count}\n"
            f"Средний баланс: {avg_balance} ₽\n\n"
            f"Пополнения: день {sum_day} ₽, неделя {sum_week} ₽, месяц {sum_month} ₽",
            reply_markup=admin_menu_inline_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "admin:users")
async def admin_users(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    await _safe_edit(call, "Пользователи: выберите фильтр или поиск.", reply_markup=admin_users_kb())


@router.callback_query(F.data == "admin_users:search")
async def admin_users_search(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_user_query)
    await _safe_edit(call, "Введите tg_id или username пользователя.")


async def _render_users_list(db, users) -> list[dict]:
    result = []
    for user in users:
        active = await dao.count_active_proxies(db, user_id=user["id"])
        uname = f"@{user['username']}" if user["username"] else f"tg:{user['tg_id']}"
        label = f"{uname} | баланс {user['balance']} ₽ | активных {active}"
        result.append({"id": user["id"], "label": label})
    return result


@router.callback_query(F.data.startswith("admin_users:"))
async def admin_users_filters(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "search":
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        users = []
        if action == "active_proxies":
            cur = await db.execute(
                "SELECT u.* FROM users u "
                "WHERE u.deleted_at IS NULL "
                "AND EXISTS (SELECT 1 FROM proxies p WHERE p.user_id = u.id AND p.status = 'active' AND p.deleted_at IS NULL) "
                "ORDER BY u.created_at DESC LIMIT 20"
            )
            users = await cur.fetchall()
        elif action == "zero_balance":
            cur = await db.execute(
                "SELECT * FROM users WHERE deleted_at IS NULL AND balance = 0 ORDER BY created_at DESC LIMIT 20"
            )
            users = await cur.fetchall()
        elif action == "disabled_proxies":
            cur = await db.execute(
                "SELECT u.* FROM users u "
                "WHERE u.deleted_at IS NULL "
                "AND EXISTS (SELECT 1 FROM proxies p WHERE p.user_id = u.id AND p.status = 'disabled' AND p.deleted_at IS NULL) "
                "ORDER BY u.created_at DESC LIMIT 20"
            )
            users = await cur.fetchall()
        elif action == "new24":
            since = (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat() + "Z"
            cur = await db.execute(
                "SELECT * FROM users WHERE deleted_at IS NULL AND created_at >= ? ORDER BY created_at DESC LIMIT 20",
                (since,),
            )
            users = await cur.fetchall()

        if not users:
            await _safe_edit(call, "Пользователей не найдено.", reply_markup=admin_users_kb())
            return
        items = await _render_users_list(db, users)
        await _safe_edit(call, "Список (до 20):", reply_markup=admin_users_list_kb(items))
    finally:
        await db.close()


@router.message(AdminStates.waiting_user_query)
async def admin_user_query(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    query = message.text.strip().lstrip("@").lower()

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        user = None
        if query.isdigit():
            user = await dao.get_user_by_tg_id(db, int(query))
        if user is None:
            user = await dao.get_user_by_username(db, query)

        if not user:
            await _admin_send_or_edit(message, "Пользователь не найден.")
            await state.clear()
            return

        await state.update_data(admin_user_id=user["id"])
        await _admin_send_or_edit(
            message,
            "Профиль:\n"
            f"ID: {user['id']}\n"
            f"tg_id: {user['tg_id']}\n"
            f"username: @{user['username']}\n"
            f"Баланс: {user['balance']} ₽\n"
            f"Заблокирован: {'да' if user['blocked_at'] else 'нет'}\n"
            f"Дата регистрации: {user['created_at']}"
        )
        await _admin_send_or_edit(
            message,
            "Действия через кнопки или текст:\n"
            "`+ сумма`, `- сумма`, `block`, `unblock`, `delete`",
            parse_mode=None,
            reply_markup=admin_user_actions_kb(user["id"], bool(user["blocked_at"])),
        )
        await state.set_state(AdminStates.waiting_user_action)
    finally:
        await db.close()

@router.message(AdminStates.waiting_user_action)
async def admin_user_actions(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return

    data = await state.get_data()
    user_id = data.get("admin_user_id")
    if not user_id:
        return

    text = message.text.strip().lower()
    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        if text.startswith("+") or text.startswith("-"):
            try:
                delta = int(text)
            except Exception:
                await _admin_send_or_edit(message, "Неверный формат суммы.")
                return
            await dao.add_user_balance(db, user_id, delta)
            if delta > 0:
                reenabled = await reenable_proxies_for_user(db, user_id)
                if reenabled:
                    try:
                        user_row = await dao.get_user_by_id(db, user_id)
                        if user_row:
                            header = await _user_header(db, user_row)
                            await send_bg_to_user(
                                message.bot,
                                db,
                                user_row,
                                f"{header}\n\nБаланс пополнен администратором. Прокси снова активны. Откройте «Мои прокси» для ссылок.",
                                reply_markup=main_menu_inline_kb(_is_admin(user_row["tg_id"])),
                            )
                    except Exception:
                        pass
            await _admin_send_or_edit(message, "Баланс обновлён.")
            return

        if text == "block":
            await dao.block_user(db, user_id)
            await _admin_send_or_edit(message, "Пользователь заблокирован.")
            return

        if text == "unblock":
            await dao.unblock_user(db, user_id)
            await _admin_send_or_edit(message, "Пользователь разблокирован.")
            return

        if text == "delete":
            await dao.delete_user(db, user_id)
            await sync_mtproto_secrets(db)
            await _admin_send_or_edit(message, "Пользователь удалён.")
            return

        await _admin_send_or_edit(message, "Неизвестная команда.")
    finally:
        await db.close()


async def _admin_user_profile(db, user_id: int) -> str:
    user = await dao.get_user_by_id(db, user_id)
    if not user:
        return "Пользователь не найден."
    return (
        "Профиль:\n"
        f"ID: {user['id']}\n"
        f"tg_id: {user['tg_id']}\n"
        f"username: @{user['username']}\n"
        f"Баланс: {user['balance']} ₽\n"
        f"Заблокирован: {'да' if user['blocked_at'] else 'нет'}\n"
        f"Дата регистрации: {user['created_at']}"
    )


@router.callback_query(F.data.startswith("admin_user:"))
async def admin_user_inline(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    parts = call.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    user_id = int(parts[2])

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        if action == "delta" and len(parts) == 4:
            delta = int(parts[3])
            await dao.add_user_balance(db, user_id, delta)
            if delta > 0:
                reenabled = await reenable_proxies_for_user(db, user_id)
                if reenabled:
                    try:
                        user = await dao.get_user_by_id(db, user_id)
                        if user:
                            header = await _user_header(db, user)
                            await send_bg_to_user(
                                call.message.bot,
                                db,
                                user,
                                f"{header}\n\nБаланс пополнен администратором. Прокси снова активны. Откройте «Мои прокси» для ссылок.",
                                reply_markup=main_menu_inline_kb(_is_admin(user["tg_id"])),
                            )
                    except Exception:
                        pass
        elif action == "custom":
            await state.set_state(AdminStates.waiting_balance_delta)
            await state.update_data(balance_user_id=user_id)
            await _safe_edit(call, "Введите сумму (можно со знаком -):")
            return
        elif action == "reset":
            await dao.set_user_balance(db, user_id, 0)
        elif action == "block":
            user = await dao.get_user_by_id(db, user_id)
            if user and user["blocked_at"]:
                await dao.unblock_user(db, user_id)
            else:
                await dao.block_user(db, user_id)
        elif action == "delete":
            await dao.delete_user(db, user_id)
            await sync_mtproto_secrets(db)
        elif action == "proxies":
            proxies = await dao.list_proxies_by_user(db, user_id)
            if not proxies:
                user = await dao.get_user_by_id(db, user_id)
                blocked = bool(user and user["blocked_at"])
                await _safe_edit(call, "У пользователя нет прокси.", reply_markup=admin_user_actions_kb(user_id, blocked))
                return
            items = [{"id": p["id"], "login": p["login"], "status": p["status"]} for p in proxies]
            await _safe_edit(call, "Прокси пользователя:", reply_markup=admin_user_proxies_kb(items, user_id))
            return
        elif action == "enable_all":
            await dao.set_proxies_status_by_user(db, user_id, "active")
            await dao.update_proxies_last_billed_by_user(db, user_id)
            await sync_mtproto_secrets(db)
        elif action == "disable_all":
            await dao.set_proxies_status_by_user(db, user_id, "disabled")
            await sync_mtproto_secrets(db)
        elif action == "open":
            pass

        user = await dao.get_user_by_id(db, user_id)
        if not user:
            await _safe_edit(call, "Пользователь не найден.", reply_markup=admin_menu_inline_kb())
            return
        text = await _admin_user_profile(db, user_id)
        await _safe_edit(call, text, reply_markup=admin_user_actions_kb(user_id, bool(user["blocked_at"])))
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_proxy:"))
async def admin_proxy_inline(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    parts = call.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    proxy_id = int(parts[2])
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        proxy = await dao.get_proxy_by_id(db, proxy_id)
        if not proxy:
            await _safe_edit(call, "Прокси не найден.", reply_markup=admin_menu_inline_kb())
            return
        user_id = proxy["user_id"]
        if action == "show":
            link = await _admin_proxy_links_text(db, proxy)
            await _safe_edit(
                call,
                f"Прокси: {proxy['login']}\n"
                f"Статус: {proxy['status']}\n"
                f"Ссылка:\n{link}",
                reply_markup=admin_user_proxies_kb(
                    [{"id": proxy["id"], "login": proxy["login"], "status": proxy["status"]}],
                    user_id,
                ),
            )
            return
        if action == "delete":
            await dao.mark_proxy_deleted(db, proxy_id)
            await sync_mtproto_secrets(db)
            proxies = await dao.list_proxies_by_user(db, user_id)
            items = [{"id": p["id"], "login": p["login"], "status": p["status"]} for p in proxies]
            await _safe_edit(call, "Прокси пользователя:", reply_markup=admin_user_proxies_kb(items, user_id))
            return
    finally:
        await db.close()


@router.message(AdminStates.waiting_balance_delta)
async def admin_user_custom_delta(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    data = await state.get_data()
    user_id = data.get("balance_user_id")
    if not user_id:
        await state.clear()
        return
    try:
        delta = int(message.text.strip())
    except Exception:
        await _admin_send_or_edit(message, "Введите целое число (можно со знаком -).")
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await dao.add_user_balance(db, user_id, delta)
        if delta > 0:
            reenabled = await reenable_proxies_for_user(db, user_id)
            if reenabled:
                try:
                    user = await dao.get_user_by_id(db, user_id)
                    if user:
                        header = await _user_header(db, user)
                        await send_bg_to_user(
                            message.bot,
                            db,
                            user,
                            f"{header}\n\nБаланс пополнен администратором. Прокси снова активны. Откройте «Мои прокси» для ссылок.",
                            reply_markup=main_menu_inline_kb(_is_admin(user["tg_id"])),
                        )
                except Exception:
                    pass
        user = await dao.get_user_by_id(db, user_id)
        if user:
            text = await _admin_user_profile(db, user_id)
            await _admin_send_or_edit(
                message,
                text,
                reply_markup=admin_user_actions_kb(user_id, bool(user["blocked_at"])),
            )
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data == "admin:proxies")
async def admin_proxies(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        cur = await db.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN status = 'disabled' THEN 1 ELSE 0 END) AS disabled, "
            "SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END) AS deleted "
            "FROM proxies"
        )
        row = await cur.fetchone()
        await _safe_edit(
            call,
            "Прокси:\n"
            f"Активные: {row['active'] or 0}\n"
            f"Отключённые: {row['disabled'] or 0}\n"
            f"Удалённые: {row['deleted'] or 0}\n\n"
            "Введите tg_id пользователя для списка его прокси.",
            reply_markup=admin_menu_inline_kb(),
        )
        await state.set_state(AdminStates.waiting_proxy_user)
    finally:
        await db.close()


@router.message(AdminStates.waiting_proxy_user)
async def admin_proxies_by_user(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    if not message.text.strip().isdigit():
        await _admin_send_or_edit(message, "Введите числовой tg_id.")
        return

    tg_id = int(message.text.strip())
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, tg_id)
        if not user:
            await _admin_send_or_edit(message, "Пользователь не найден.")
            return
        proxies = await dao.list_proxies_by_user(db, user["id"])
        if not proxies:
            await _admin_send_or_edit(message, "У пользователя нет прокси.")
            return
        lines = []
        for p in proxies:
            lines.append(f"{p['login']} {p['ip']}:{p['port']} статус={p['status']}")
        await _admin_send_or_edit(message, "Прокси пользователя:\n" + "\n".join(lines))
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data == "admin:payments")
async def admin_payments(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        cur = await db.execute(
            "SELECT id, user_id, amount, status, provider_payment_id, created_at "
            "FROM payments ORDER BY id DESC LIMIT 10"
        )
        rows = await cur.fetchall()
        if not rows:
            await _safe_edit(call, "Платежей нет.", reply_markup=admin_menu_inline_kb())
            return
        lines = [
            f"#{row['id']} user={row['user_id']} {row['amount']}₽ {row['status']} {row['created_at']}"
            for row in rows
        ]
        await _safe_edit(
            call,
            "Последние платежи:\n" + "\n".join(lines),
            reply_markup=admin_menu_inline_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "admin:support")
async def admin_support_list(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        tickets = await dao.list_support_tickets(db, status="open", limit=20)
        if not tickets:
            await _safe_edit(call, "Открытых тикетов нет.", reply_markup=admin_menu_inline_kb())
            return
        items = []
        for t in tickets:
            label = f"#{t['id']} {_support_user_label(t['username'], t['tg_id'])}"
            items.append({"id": t["id"], "label": label})
        await _safe_edit(
            call,
            f"Открытые тикеты: {len(tickets)}\nНажмите для просмотра.",
            reply_markup=admin_support_list_kb(items),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_support:open:"))
async def admin_support_open(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    ticket_id = int(parts[2])
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        ticket = await dao.get_support_ticket(db, ticket_id)
        if not ticket:
            await _safe_edit(call, "Тикет не найден.", reply_markup=admin_support_list_kb([]))
            return
        user = await dao.get_user_by_id(db, ticket["user_id"])
        username = user["username"] if user else None
        tg_id = user["tg_id"] if user else 0
        status = ticket["status"]
        messages = await dao.list_support_messages(db, ticket_id, limit=10)
        lines = [
            f"Тикет #{ticket_id} ({status})",
            f"Пользователь: {_support_user_label(username, tg_id)} (tg_id: {tg_id})",
            "",
            "История:",
        ]
        if not messages:
            lines.append("— сообщений нет —")
        else:
            for msg in messages:
                role = "👤" if msg["sender_role"] == "user" else "🛠"
                ts = (msg["created_at"] or "").replace("T", " ").replace("Z", "")
                body = (msg["message"] or "").strip()
                if len(body) > 200:
                    body = body[:200] + "..."
                lines.append(f"{role} {ts}: {body}")

        text = "\n".join(lines)
        await _safe_edit(
            call,
            text,
            reply_markup=support_admin_ticket_kb_ext(ticket_id, show_back=True, show_refresh=True),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "admin:settings")
async def admin_settings(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        settings_map = await dao.get_settings_map(db)
        await _safe_edit(
            call,
            _settings_text(settings_map) + "\n\nЧтобы изменить значение, нажмите кнопку.",
            reply_markup=admin_settings_kb(settings_map),
        )
        await state.set_state(AdminStates.waiting_setting_input)
    finally:
        await db.close()


@router.callback_query(F.data == "admin:mtproxy")
async def admin_mtproxy(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        text = await _mtproxy_status_text(db)
        await _safe_edit(call, text, reply_markup=mtproxy_status_kb())
    finally:
        await db.close()


@router.callback_query(F.data == "admin:freekassa")
async def admin_freekassa(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        text = await _freekassa_status_text(db)
        await _safe_edit(call, text, reply_markup=freekassa_status_kb())
    finally:
        await db.close()


@router.callback_query(F.data == "admin:freekassa_refresh")
async def admin_freekassa_refresh(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        text = await _freekassa_status_text(db)
        await _safe_edit(call, text, reply_markup=freekassa_status_kb())
    finally:
        await db.close()


@router.callback_query(F.data == "admin:mtproxy_refresh")
async def admin_mtproxy_refresh(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        text = await _mtproxy_status_text(db)
        await _safe_edit(call, text, reply_markup=mtproxy_status_kb())
    finally:
        await db.close()


@router.callback_query(F.data == "admin:mtproxy_logs")
async def admin_mtproxy_logs(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None or not config.mtproxy_service:
        await _safe_edit(call, "MTProxy service не задан.", reply_markup=mtproxy_status_kb())
        return
    text = await _get_mtproxy_logs(config.mtproxy_service, lines=50)
    if len(text) > 3500:
        text = text[-3500:]
        text = "...\n" + text
    await _safe_edit(call, f"Логи MTProxy:\n{text}", reply_markup=mtproxy_status_kb())


@router.message(AdminStates.waiting_setting_input)
async def admin_settings_set(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return

    data = await state.get_data()
    selected_key = data.get("setting_key")
    if not selected_key:
        await _admin_send_or_edit(message, "Нажмите кнопку нужной настройки.")
        return
    key = selected_key
    value = message.text.strip()
    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        await dao.set_setting(db, key, value)
        if key == "mtproto_enabled":
            await sync_mtproto_secrets(db)
        settings_map = await dao.get_settings_map(db)
        await _admin_send_or_edit(message, "Настройка обновлена.")
        await _admin_send_or_edit(
            message,
            _settings_text(settings_map),
            reply_markup=admin_settings_kb(settings_map),
        )
        await state.update_data(setting_key=None)
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_settings_edit:"))
async def admin_settings_pick(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    key = call.data.split(":", 1)[1]
    if key == "bg_image":
        await state.set_state(AdminStates.waiting_bg_image)
        await _safe_edit(call, "Отправьте новую картинку фона (фото).")
        return
    await state.update_data(setting_key=key)
    await _safe_edit(call, f"Введите значение для `{key}`:", parse_mode=None)


@router.message(AdminStates.waiting_bg_image)
async def admin_bg_image(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    config = runtime.config
    if config is None:
        return
    if not message.photo:
        await _admin_send_or_edit(message, "Пожалуйста, отправьте фото.")
        return
    db = await get_db(config.db_path)
    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        dest = Path(__file__).resolve().parents[2] / "bg.jpg"
        await message.bot.download_file(file.file_path, destination=dest)
        await dao.set_setting(db, "bg_enabled", "1")
        runtime.bg_enabled = True
        settings_map = await dao.get_settings_map(db)
        await _admin_send_or_edit(
            message,
            "Фон обновлён.",
        )
        await _admin_send_or_edit(
            message,
            _settings_text(settings_map),
            reply_markup=admin_settings_kb(settings_map),
        )
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_settings_toggle:"))
async def admin_settings_toggle(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    key = call.data.split(":", 1)[1]
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        current = await dao.get_setting(db, key, "0")
        new_value = "0" if (current or "0") == "1" else "1"
        await dao.set_setting(db, key, new_value)
        if key == "mtproto_enabled":
            await sync_mtproto_secrets(db)
        if key == "bg_enabled":
            runtime.bg_enabled = new_value == "1"
        settings_map = await dao.get_settings_map(db)
        await _safe_edit(call, _settings_text(settings_map), reply_markup=admin_settings_kb(settings_map))
        await state.update_data(setting_key=None)
    finally:
        await db.close()


@router.callback_query(F.data.startswith("support:reply:"))
async def admin_support_reply_pick(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    ticket_id = int(parts[2])
    await state.update_data(support_ticket_id=ticket_id)
    await state.set_state(AdminStates.waiting_support_reply)
    await _safe_edit(call, f"Введите ответ для тикета #{ticket_id}:", reply_markup=support_admin_reply_kb())


@router.callback_query(F.data.startswith("support:close:"))
async def admin_support_close(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return
    ticket_id = int(parts[2])
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        ticket = await dao.get_support_ticket(db, ticket_id)
        if not ticket:
            await _safe_edit(call, "Тикет не найден.")
            return
        await dao.set_support_ticket_status(db, ticket_id, "closed")
        user = await dao.get_user_by_id(db, ticket["user_id"])
        if user:
            header = await _user_header(db, user)
            await send_bg_to_user(
                call.message.bot,
                db,
                user,
                f"{header}\n\nВаш тикет #{ticket_id} закрыт. Если нужно — напишите снова.",
                reply_markup=main_menu_inline_kb(_is_admin(user["tg_id"])),
            )
        for admin_id in (runtime.config.admin_tg_ids if runtime.config else []):
            try:
                await call.message.bot.send_message(admin_id, f"Тикет #{ticket_id} закрыт.")
            except Exception:
                pass
        await _safe_edit(call, f"Тикет #{ticket_id} закрыт.")
    finally:
        await db.close()


@router.callback_query(F.data == "support:reply_cancel")
async def admin_support_reply_cancel(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    await _safe_edit(call, "Отменено.", reply_markup=admin_menu_inline_kb())


@router.message(AdminStates.waiting_support_reply)
async def admin_support_reply_send(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text:
        await _admin_send_or_edit(message, "Ответ должен быть текстом.", reply_markup=support_admin_reply_kb())
        return
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    if not ticket_id:
        await _admin_send_or_edit(message, "Тикет не найден.")
        await state.clear()
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        ticket = await dao.get_support_ticket(db, int(ticket_id))
        if not ticket:
            await _admin_send_or_edit(message, "Тикет не найден.")
            await state.clear()
            return
        await dao.add_support_message(db, int(ticket_id), "admin", message.from_user.id, text)
        if ticket["status"] != "open":
            await dao.set_support_ticket_status(db, int(ticket_id), "open")
        user = await dao.get_user_by_id(db, ticket["user_id"])
        if user:
            header = await _user_header(db, user)
            await send_bg_to_user(
                message.bot,
                db,
                user,
                f"{header}\n\nОтвет поддержки:\n{text}",
                reply_markup=main_menu_inline_kb(_is_admin(user["tg_id"])),
            )
        admin_tag = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
        notify_text = f"Ответ по тикету #{ticket_id} от {admin_tag}:\n{text}"
        for admin_id in (runtime.config.admin_tg_ids if runtime.config else []):
            try:
                await message.bot.send_message(admin_id, notify_text)
            except Exception:
                pass
        await _admin_send_or_edit(message, "Ответ отправлен.")
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data == "admin:export")
async def admin_export(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await _safe_edit(call, "Экспорт CSV:", reply_markup=admin_export_kb())


async def _send_export_csv(kind: str, message: Message | CallbackQuery, db) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    if kind == "users":
        rows = await db.execute("SELECT id, tg_id, username, created_at FROM users WHERE deleted_at IS NULL")
        writer.writerow(["id", "tg_id", "username", "created_at"])
        for row in await rows.fetchall():
            writer.writerow([row["id"], row["tg_id"], row["username"], row["created_at"]])

    if kind == "users_balances":
        rows = await db.execute("SELECT id, tg_id, username, balance FROM users WHERE deleted_at IS NULL")
        writer.writerow(["id", "tg_id", "username", "balance"])
        for row in await rows.fetchall():
            writer.writerow([row["id"], row["tg_id"], row["username"], row["balance"]])

    if kind == "proxies":
        rows = await db.execute(
            "SELECT id, user_id, login, ip, port, status, created_at FROM proxies WHERE deleted_at IS NULL"
        )
        writer.writerow(["id", "user_id", "login", "ip", "port", "status", "created_at"])
        for row in await rows.fetchall():
            writer.writerow(
                [row["id"], row["user_id"], row["login"], row["ip"], row["port"], row["status"], row["created_at"]]
            )

    if kind == "payments":
        rows = await db.execute(
            "SELECT id, user_id, amount, status, provider_payment_id, created_at FROM payments"
        )
        writer.writerow(["id", "user_id", "amount", "status", "provider_payment_id", "created_at"])
        for row in await rows.fetchall():
            writer.writerow(
                [row["id"], row["user_id"], row["amount"], row["status"], row["provider_payment_id"], row["created_at"]]
            )

    if kind == "referrals":
        rows = await db.execute(
            "SELECT id, inviter_user_id, invited_user_id, link_code, bonus_inviter, bonus_invited, created_at FROM referral_events"
        )
        writer.writerow(["id", "inviter_user_id", "invited_user_id", "link_code", "bonus_inviter", "bonus_invited", "created_at"])
        for row in await rows.fetchall():
            writer.writerow(
                [
                    row["id"],
                    row["inviter_user_id"],
                    row["invited_user_id"],
                    row["link_code"],
                    row["bonus_inviter"],
                    row["bonus_invited"],
                    row["created_at"],
                ]
            )

    data = buffer.getvalue().encode("utf-8")
    file = BufferedInputFile(data, filename=f"{kind}.csv")
    if isinstance(message, CallbackQuery):
        await message.message.answer_document(file)
    else:
        await message.answer_document(file)


@router.message(StateFilter(None), F.text)
async def admin_export_csv(message: Message) -> None:
    if not _require_admin(message):
        return

    kind = message.text.strip().lower()
    if kind not in {"users", "users_balances", "proxies", "payments", "referrals"}:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await _send_export_csv(kind, message, db)
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_export:"))
async def admin_export_cb(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    kind = call.data.split(":", 1)[1]
    if kind not in {"users", "users_balances", "proxies", "payments", "referrals"}:
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await _send_export_csv(kind, call, db)
    finally:
        await db.close()


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_broadcast_text)
    await _safe_edit(call, "Введите текст рассылки.")


@router.message(AdminStates.waiting_broadcast_text)
async def admin_broadcast_text(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    await state.update_data(broadcast_text=message.text)
    await _admin_send_or_edit(message, "Выберите аудиторию:", reply_markup=broadcast_filters_kb())


@router.callback_query(F.data.startswith("broadcast:"))
async def admin_broadcast_send(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return

    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await _safe_edit(call, "Рассылка отменена.")
        return

    data = await state.get_data()
    text = data.get("broadcast_text")
    if not text:
        await _safe_edit(call, "Текст рассылки не задан.")
        return

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        query = "SELECT * FROM users WHERE deleted_at IS NULL"
        params = []

        if action == "active7":
            since = (datetime.utcnow() - timedelta(days=7)).replace(microsecond=0).isoformat() + "Z"
            query += " AND last_seen_at >= ?"
            params.append(since)
        elif action == "active_proxies":
            query = (
                "SELECT DISTINCT u.* FROM users u "
                "JOIN proxies p ON p.user_id = u.id "
                "WHERE u.deleted_at IS NULL AND p.status = 'active'"
            )
        elif action == "balance_pos":
            query += " AND balance > 0"

        cur = await db.execute(query, params)
        rows = await cur.fetchall()

        await _safe_edit(call, f"Начинаю рассылку. Получателей: {len(rows)}")
        delay = config.broadcast_delay_ms / 1000.0

        sent = 0
        failed = 0
        for row in rows:
            try:
                is_admin = row["tg_id"] in (runtime.config.admin_tg_ids if runtime.config else [])
                await send_bg_to_user(
                    call.message.bot,
                    db,
                    row,
                    text,
                    reply_markup=main_menu_inline_kb(is_admin),
                )
                sent += 1
            except Exception:
                failed += 1
                continue
            if delay:
                await asyncio.sleep(delay)

        await _safe_edit(call, f"Рассылка завершена. Успешно: {sent}, ошибок: {failed}.")
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data == "admin:referrals")
async def admin_referrals(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        links = await dao.list_referral_links(db)
        cur = await db.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(bonus_inviter + bonus_invited), 0) AS total "
            "FROM referral_events"
        )
        totals = await cur.fetchone()
        total_cnt = int(totals["cnt"]) if totals else 0
        total_bonus = int(totals["total"]) if totals else 0
        top_lines = []
        cur = await db.execute(
            "SELECT inviter_user_id, COUNT(*) AS cnt, COALESCE(SUM(bonus_inviter), 0) AS bonus "
            "FROM referral_events GROUP BY inviter_user_id ORDER BY cnt DESC LIMIT 5"
        )
        rows = await cur.fetchall()
        for row in rows:
            inviter = await dao.get_user_by_id(db, row["inviter_user_id"])
            name = f"@{inviter['username']}" if inviter and inviter["username"] else f"id:{row['inviter_user_id']}"
            top_lines.append(f"{name} — {row['cnt']} приглашений, бонус {row['bonus']} ₽")
        if links:
            lines = []
            bot_info = await call.bot.get_me()
            for link in links:
                cur = await db.execute(
                    "SELECT COUNT(*) AS cnt, COALESCE(SUM(bonus_inviter + bonus_invited), 0) AS total "
                    "FROM referral_events WHERE link_code = ?",
                    (link["code"],),
                )
                stats = await cur.fetchone()
                uses = int(stats["cnt"])
                total_bonus = int(stats["total"])
                url = f"https://t.me/{bot_info.username}?start={link['code']}"
                lines.append(
                    f"{link['code']} — {url}\n"
                    f"owner={link['owner_user_id']} "
                    f"bonus({link['bonus_inviter']}/{link['bonus_invited']}) "
                    f"uses={uses} total_bonus={total_bonus}₽"
                )
            header = f"Рефералы: всего {total_cnt}, начислено {total_bonus} ₽"
            top_block = "\n".join(top_lines) if top_lines else "Нет данных"
            codes = [link["code"] for link in links]
            await _safe_edit(
                call,
                header + "\n\nТоп приглашений:\n" + top_block + "\n\nСсылки:\n" + "\n".join(lines),
                reply_markup=admin_referrals_list_kb(codes),
            )
        else:
            header = f"Рефералы: всего {total_cnt}, начислено {total_bonus} ₽"
            top_block = "\n".join(top_lines) if top_lines else "Нет данных"
            await _safe_edit(
                call,
                header + "\n\nТоп приглашений:\n" + top_block + "\n\nАктивных ссылок нет.",
                reply_markup=admin_referrals_kb(),
            )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_ref_del:"))
async def admin_ref_delete(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    code = call.data.split("admin_ref_del:", 1)[-1]
    if not code:
        return
    await _safe_edit(
        call,
        f"Удалить ссылку `{code}`?\n"
        "Ссылка будет выключена и исчезнет из списка.",
        reply_markup=admin_ref_delete_confirm_kb(code),
        parse_mode=None,
    )


@router.callback_query(F.data.startswith("admin_ref_del_confirm:"))
async def admin_ref_delete_confirm(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    code = call.data.split("admin_ref_del_confirm:", 1)[-1]
    if not code:
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await dao.disable_referral_link(db, code)
    finally:
        await db.close()
    await _safe_edit(call, f"Ссылка `{code}` удалена.", reply_markup=admin_referrals_kb(), parse_mode=None)


@router.callback_query(F.data == "admin:ref_create")
async def admin_ref_create(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(AdminStates.ref_code)
    await _safe_edit(call, "Шаг 1/2. Введите код ссылки (латиница/цифры без пробелов).")


@router.message(AdminStates.ref_code)
async def admin_ref_code(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    code = message.text.strip()
    if not re.match(r"^[A-Za-z0-9]+$", code):
        await _admin_send_or_edit(message, "Код должен состоять из латиницы и цифр, без пробелов.")
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        if await dao.get_user_by_ref_code(db, code) or await dao.get_referral_link(db, code):
            await _admin_send_or_edit(message, "Код уже используется. Введите другой.")
            return
    finally:
        await db.close()
    await state.update_data(ref_code=code)
    await state.set_state(AdminStates.ref_bonuses)
    await _admin_send_or_edit(
        message,
        "Шаг 2/2. Введите бонус приглашенному (руб).\n"
        "Можно вторым числом указать бонус приглашающему.\n"
        "Примеры: `100` или `100 50`.",
        parse_mode=None,
    )


@router.message(AdminStates.ref_bonuses)
async def admin_ref_bonuses(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    data = await state.get_data()
    code = data.get("ref_code")
    if not code:
        await _admin_send_or_edit(message, "Не удалось создать ссылку. Начните заново.")
        await state.clear()
        return

    parts = message.text.strip().split()
    if not parts:
        await _admin_send_or_edit(message, "Введите одно или два числа.")
        return
    try:
        bonus_invited = int(parts[0])
        bonus_inviter = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        await _admin_send_or_edit(message, "Введите одно или два числа.")
        return
    if bonus_invited < 0 or bonus_inviter < 0:
        await _admin_send_or_edit(message, "Бонусы не могут быть отрицательными.")
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        owner = await dao.get_user_by_tg_id(db, message.from_user.id)
        if not owner:
            await _admin_send_or_edit(message, "Сначала откройте бота и нажмите /start.")
            await state.clear()
            return
        owner_user_id = owner["id"]
        await dao.create_referral_link(
            db,
            code=code,
            name=None,
            owner_user_id=owner_user_id,
            bonus_inviter=bonus_inviter,
            bonus_invited=bonus_invited,
            limit_total=None,
            limit_per_user=None,
        )
        bot_info = await message.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={code}"
        await _admin_send_or_edit(message, "Ссылка создана.")
        await _admin_send_or_edit(message, f"Ссылка для распространения:\n{link}")
        await state.clear()
    finally:
        await db.close()
