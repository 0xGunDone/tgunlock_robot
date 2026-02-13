from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, LabeledPrice
from html import escape as html_escape
from datetime import datetime, timedelta

from bot import dao
from bot.db import get_db
from bot.handlers.states import UserStates
from bot.keyboards import (
    main_menu_inline_kb,
    proxies_list_kb,
    proxy_detail_kb,
    proxies_empty_kb,
    proxy_delete_confirm_kb,
    topup_quick_kb,
    help_kb,
    help_detail_kb,
)
from bot.runtime import runtime
from bot.ui import send_or_edit_bg_message
from bot.services.settings import (
    get_int_setting,
    get_decimal_setting,
    get_bool_setting,
    convert_rub_to_stars,
)
from bot.services.mtproto import sync_mtproto_secrets, ensure_proxy_mtproto_secret, reenable_proxies_for_user
from bot.utils import (
    generate_login,
    generate_password,
    generate_ref_code,
    generate_mtproto_secret,
    extract_ref_code,
)

router = Router()


async def _ensure_unique_ref_code(db, length: int = 8) -> str:
    while True:
        code = generate_ref_code(length)
        existing = await dao.get_user_by_ref_code(db, code)
        link = await dao.get_referral_link(db, code)
        if not existing and not link:
            return code


def _get_start_args(message: Message) -> str | None:
    text = message.text or ""
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if not parts:
        return None
    cmd = parts[0].lower()
    if not (cmd == "/start" or cmd.startswith("/start@")):
        return None
    if len(parts) == 1:
        return None
    return parts[1].strip() or None


def _is_admin(tg_id: int) -> bool:
    config = runtime.config
    if config is None:
        return False
    return tg_id in config.admin_tg_ids


async def _send_or_edit_main_message(
    message: Message,
    db,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
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


async def _send_bg_no_db(
    message: Message, text: str, reply_markup=None, parse_mode: str | None = None
) -> None:
    await send_or_edit_bg_message(
        message.bot,
        message.chat.id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        message_id=None,
    )


async def _get_user_and_header(db, tg_id: int) -> tuple[object | None, str | None]:
    user = await dao.get_user_by_tg_id(db, tg_id)
    if not user:
        return None, None
    active = await dao.count_active_proxies(db, user_id=user["id"])
    header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
    return user, header


async def _safe_edit(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    msg_id = await send_or_edit_bg_message(
        call.message.bot,
        call.message.chat.id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        message_id=call.message.message_id,
    )
    await _remember_menu_message(call.from_user.id, msg_id)


async def _remember_menu_message(tg_id: int, message_id: int) -> None:
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await dao.update_user_last_menu_message_id(db, tg_id, message_id)
    finally:
        await db.close()


def _normalize_login(login: str, prefix: str) -> str:
    return f"{prefix}{login}".lower()


async def _create_proxy_for_user(db, user_id: int, is_free: int) -> dict:
    login = _normalize_login(generate_login(), "tgunlockrobot_")
    password = generate_password()
    mtproto_secret = generate_mtproto_secret()
    host = (await dao.get_setting(db, "mtproto_host", "")) or runtime.config.proxy_default_ip
    port_raw = await dao.get_setting(db, "mtproto_port", "9443") or "9443"
    try:
        port = int(port_raw)
    except Exception:
        port = 9443
    ip = host
    proxy_id = await dao.create_proxy(
        db,
        user_id=user_id,
        login=login,
        password=password,
        ip=ip,
        port=port,
        status="active",
        is_free=is_free,
        mtproto_secret=mtproto_secret,
    )
    return {
        "id": proxy_id,
        "login": login,
        "password": password,
        "ip": ip,
        "port": port,
        "mtproto_secret": mtproto_secret,
    }


async def _apply_referral(db, ref_arg: str | None, user_id: int) -> None:
    if not ref_arg:
        return
    referral_enabled = await get_bool_setting(db, "referral_enabled", True)
    if not referral_enabled:
        return

    inviter_user_id = None
    bonus_inviter = 0
    bonus_invited = 0

    link = await dao.get_referral_link(db, ref_arg)
    if link:
        inviter_user_id = link["owner_user_id"]
        bonus_inviter = int(link["bonus_inviter"])
        bonus_invited = int(link["bonus_invited"])
        total_used = await dao.count_referral_events(db, ref_arg)
        limit_total = link["limit_total"]
        limit_per_user = link["limit_per_user"]
        if limit_total is not None and total_used >= limit_total:
            bonus_inviter = 0
            bonus_invited = 0
        if inviter_user_id and limit_per_user is not None:
            used_by_inviter = await dao.count_referral_events_for_inviter(
                db, ref_arg, inviter_user_id
            )
            if used_by_inviter >= limit_per_user:
                bonus_inviter = 0
                bonus_invited = 0
    else:
        inviter = await dao.get_user_by_ref_code(db, ref_arg)
        if inviter:
            inviter_user_id = inviter["id"]
            bonus_inviter = await get_int_setting(db, "ref_bonus_inviter", 0)
            bonus_invited = await get_int_setting(db, "ref_bonus_invited", 0)

    if inviter_user_id and inviter_user_id != user_id:
        if bonus_inviter:
            await dao.add_user_balance(db, inviter_user_id, bonus_inviter)
        if bonus_invited:
            await dao.add_user_balance(db, user_id, bonus_invited)
        await dao.create_referral_event(
            db,
            inviter_user_id=inviter_user_id,
            invited_user_id=user_id,
            link_code=ref_arg,
            bonus_inviter=bonus_inviter,
            bonus_invited=bonus_invited,
        )


async def _build_proxy_links_text(db, proxy) -> str:
    lines = []
    mtproto_enabled = await get_bool_setting(db, "mtproto_enabled", True)

    if mtproto_enabled:
        host = (await dao.get_setting(db, "mtproto_host", "")) or runtime.config.proxy_default_ip
        port = await dao.get_setting(db, "mtproto_port", "9443") or "9443"
        if isinstance(proxy, dict):
            secret = proxy.get("mtproto_secret", "") or ""
            proxy_id = proxy.get("id")
        else:
            try:
                secret = proxy["mtproto_secret"] or ""
            except Exception:
                secret = ""
            try:
                proxy_id = proxy["id"]
            except Exception:
                proxy_id = None
        if not secret and proxy_id:
            secret = await ensure_proxy_mtproto_secret(db, proxy_id)
            await sync_mtproto_secrets(db)
        if secret:
            mt_link = f"https://t.me/proxy?server={host}&port={port}&secret={secret}"
            lines.append(f"MTProto:\n{mt_link}")

    if not lines:
        return "MTProto отключён админом."
    return "\n\n".join(lines)


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")).date()
    except Exception:
        return None


async def _issue_invoice(bot: Bot, chat_id: int, db, user_id: int, rub: int) -> None:
    rate = await get_decimal_setting(db, "stars_rate", "1")
    stars = convert_rub_to_stars(rub, rate)
    payload = f"topup:{user_id}:{rub}:{stars}"
    payment_id = await dao.create_payment(db, user_id=user_id, amount=rub, status="pending", payload=payload)
    payload = f"{payload}:{payment_id}"
    await dao.update_payment_payload(db, payment_id, payload)

    prices = [LabeledPrice(label="Пополнение баланса", amount=stars)]
    await bot.send_invoice(
        chat_id=chat_id,
        title="Пополнение баланса",
        description=f"Пополнение на {rub} ₽",
        payload=payload,
        currency="XTR",
        prices=prices,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    config = runtime.config
    if config is None:
        await _send_bg_no_db(message, "Бот не настроен.")
        return
    await state.clear()

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id_any(db, message.from_user.id)
        if user and user["deleted_at"]:
            await dao.delete_user(db, user["id"])
            await sync_mtproto_secrets(db)
            user = None

        if user:
            if user["blocked_at"]:
                await _send_or_edit_main_message(message, db, "Ваш аккаунт заблокирован.")
                return
            await db.execute(
                "UPDATE users SET username = ? WHERE tg_id = ?",
                (message.from_user.username, message.from_user.id),
            )
            await db.commit()
            await dao.update_user_last_seen(db, message.from_user.id)
            user_row, header = await _get_user_and_header(db, message.from_user.id)
            text = f"{header}\n\nГлавное меню" if header else "Главное меню"
            await _send_or_edit_main_message(
                message,
                db,
                text,
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
            return

        ref_arg = extract_ref_code(_get_start_args(message))
        free_credit = await get_int_setting(db, "free_credit", 0)

        ref_code = await _ensure_unique_ref_code(db)
        referred_by = ref_arg if ref_arg else None

        user_id = await dao.create_user(
            db,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            ref_code=ref_code,
            referred_by=referred_by,
            balance=free_credit,
        )

        await _apply_referral(db, ref_arg, user_id)

        try:
            proxy = await _create_proxy_for_user(db, user_id, is_free=1)
            await sync_mtproto_secrets(db)
            links_text = await _build_proxy_links_text(db, proxy)
            user_row, header = await _get_user_and_header(db, message.from_user.id)
            prefix = f"{header}\n\n" if header else ""
            await _send_or_edit_main_message(
                message,
                db,
                prefix
                + "Добро пожаловать! Ваш MTProto-прокси готов:\n"
                f"{links_text}\n\n"
                "Нажмите на ссылку — Telegram сам добавит прокси.\n"
                "Включайте/выключайте в настройках Telegram.\n"
                "Если ссылка не открывается — введите host/port/secret вручную.",
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
        except Exception:
            await _send_or_edit_main_message(
                message,
                db,
                "Сервис временно недоступен. Попробуйте позже.",
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
    finally:
        await db.close()


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        text = f"{header}\n\nГлавное меню"
        await _safe_edit(call, text, reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
    finally:
        await db.close()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, message.from_user.id)
        prefix = f"{header}\n\n" if header else ""
        await _send_or_edit_main_message(
            message,
            db,
            prefix
            + "Инструкция:\n"
            "1) Нажмите на ссылку — Telegram сам добавит прокси.\n"
            "2) Включайте/выключайте в настройках Telegram.\n"
            "Если ссылка не открывается — введите host/port/secret вручную.",
            reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "menu:help")
async def menu_help(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Инструкция:\n"
            "1) Нажмите на ссылку — Telegram сам добавит прокси.\n"
            "2) Включайте/выключайте в настройках Telegram.\n"
            "Если ссылка не открывается — введите host/port/secret вручную.",
            reply_markup=help_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("help:"))
async def help_detail(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    key = call.data.split(":", 1)[1]
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        if key == "toggle":
            text = (
                f"{header}\n\n"
                "Как включить/выключить:\n"
                "Telegram → Настройки → Данные и память → Прокси.\n"
                "Нажмите на прокси и переключите тумблер."
            )
        elif key == "fail":
            text = (
                f"{header}\n\n"
                "Не подключается:\n"
                "1) Проверьте, что прокси активен в разделе «Мои прокси».\n"
                "2) Если ссылка не открывается — введите host/port/secret вручную.\n"
                "3) Попробуйте включить/выключить прокси в настройках."
            )
        elif key == "pay":
            text = (
                f"{header}\n\n"
                "Как оплатить:\n"
                "Нажмите «⭐ Пополнить» и выберите сумму.\n"
                "После оплаты прокси включатся автоматически."
            )
        else:
            text = f"{header}\n\nРаздел помощи."
        await _safe_edit(call, text, reply_markup=help_detail_kb())
    finally:
        await db.close()


@router.callback_query(F.data == "menu:check")
async def menu_check(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        proxies = await dao.list_proxies_by_user(db, user["id"])
        active = await dao.count_active_proxies(db, user_id=user["id"])
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        if not proxies:
            await _safe_edit(call, f"{header}\n\nУ вас нет прокси.")
            return

        day_price = await get_int_setting(db, "proxy_day_price", 0)
        lines = [header, "", "Статус прокси:"]
        today = datetime.utcnow().date()
        for p in proxies:
            status = "активен" if p["status"] == "active" else "отключён"
            next_charge = "не списывается"
            if p["status"] == "active" and day_price > 0:
                last_billed = _parse_date(p["last_billed_at"])
                if last_billed:
                    next_charge = (last_billed + timedelta(days=1)).isoformat()
                else:
                    next_charge = today.isoformat()
            lines.append(f"{p['login']} — {status}, списание: {next_charge}")
        await _safe_edit(call, "\n".join(lines), reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
    finally:
        await db.close()


@router.callback_query(F.data == "menu:proxies")
async def my_proxies(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start", reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
            return
        proxies = await dao.list_proxies_by_user(db, user["id"])
        if not proxies:
            header = f"Баланс: {user['balance']} ₽ | Активных прокси: 0"
            await _safe_edit(call, f"{header}\n\nУ вас пока нет прокси.", reply_markup=proxies_empty_kb())
            return

        proxy_dicts = [
            {"id": p["id"], "login": p["login"]} for p in proxies
        ]
        active = await dao.count_active_proxies(db, user_id=user["id"])
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        lines = [f"{header}", "", "Ваши прокси:", "Нажмите на имя, чтобы получить ссылку."]
        for idx, p in enumerate(proxies, 1):
            lines.append(f"{idx}. {p['login']}")
        await _safe_edit(call, "\n".join(lines), reply_markup=proxies_list_kb(proxy_dicts))
    finally:
        await db.close()


@router.callback_query(F.data == "proxy:list")
async def proxy_list_cb(call: CallbackQuery) -> None:
    await call.answer()
    await my_proxies(call)


@router.callback_query(F.data == "proxy:buy")
async def proxy_buy_cb(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start", reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
            return
        if user["blocked_at"]:
            await _safe_edit(call, "Ваш аккаунт заблокирован.")
            return

        max_active = await get_int_setting(db, "max_active_proxies", 10)
        active_count = await dao.count_active_proxies(db, user_id=user["id"])
        if max_active > 0 and active_count >= max_active:
            await _safe_edit(call, "Достигнут лимит активных прокси.")
            return

        price = await get_int_setting(db, "proxy_create_price", 0)
        if user["balance"] < price:
            await _safe_edit(call, "Недостаточно средств. Пополните баланс.")
            return

        await dao.add_user_balance(db, user["id"], -price)
        proxy = await _create_proxy_for_user(db, user["id"], is_free=0)
        await sync_mtproto_secrets(db)
        links_text = await _build_proxy_links_text(db, proxy)
        active = await dao.count_active_proxies(db, user_id=user["id"])
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Новый прокси создан:\n"
            f"{links_text}",
            reply_markup=proxy_detail_kb(),
        )
    finally:
        await db.close()

@router.callback_query(F.data.startswith("proxy:show:"))
async def proxy_show(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    proxy_id = int(call.data.split(":")[-1])
    db = await get_db(config.db_path)
    try:
        proxy = await dao.get_proxy_by_id(db, proxy_id)
        if not proxy:
            await _safe_edit(call, "Прокси не найден.", reply_markup=proxy_detail_kb())
            return
        links_text = await _build_proxy_links_text(db, proxy)
        user = await dao.get_user_by_id(db, proxy["user_id"])
        active = await dao.count_active_proxies(db, user_id=proxy["user_id"]) if user else 0
        balance = user["balance"] if user else 0
        header = f"Баланс: {balance} ₽ | Активных прокси: {active}"
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Ссылка на прокси:\n"
            f"{links_text}",
            reply_markup=proxy_detail_kb(),
        )
    finally:
        await db.close()

@router.callback_query(F.data.startswith("proxy:delete:"))
async def proxy_delete_prepare(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    proxy_id = int(call.data.split(":")[-1])
    db = await get_db(config.db_path)
    try:
        proxy = await dao.get_proxy_by_id(db, proxy_id)
        if not proxy:
            await _safe_edit(call, "Прокси не найден.", reply_markup=proxy_detail_kb())
            return
        links_text = await _build_proxy_links_text(db, proxy)
        await _safe_edit(
            call,
            "Удалить прокси?\n"
            f"{links_text}\n\n"
            "Это действие нельзя отменить.",
            reply_markup=proxy_delete_confirm_kb(proxy_id),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("proxy:delete_confirm:"))
async def proxy_delete_apply(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return

    proxy_id = int(call.data.split(":")[-1])
    db = await get_db(config.db_path)
    try:
        proxy = await dao.get_proxy_by_id(db, proxy_id)
        if not proxy:
            await _safe_edit(call, "Прокси не найден.", reply_markup=proxy_detail_kb())
            return
        await dao.mark_proxy_deleted(db, proxy_id)
        await sync_mtproto_secrets(db)
        await my_proxies(call)
    finally:
        await db.close()


@router.callback_query(F.data == "menu:referrals")
async def referral_info(call: CallbackQuery) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start", reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
            return
        active = await dao.count_active_proxies(db, user_id=user["id"])
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Ваша реферальная ссылка:\n"
            f"https://t.me/{(await call.bot.get_me()).username}?start=ref_{user['ref_code']}",
            reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "menu:topup")
async def topup_start(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        hint_enabled = await get_bool_setting(db, "stars_buy_hint_enabled", False)
        stars_url = await dao.get_setting(db, "stars_buy_url", "") or ""
        hint = ""
        if hint_enabled and stars_url:
            safe_url = html_escape(stars_url, quote=True)
            hint = f"\n\nЗВЕЗДЫ МОЖНО КУПИТЬ <a href=\"{safe_url}\">ТУТ</a>"
        await state.clear()
        await _safe_edit(
            call,
            f"{header}\n\nВыберите сумму пополнения или нажмите «Ввести сумму».{hint}",
            parse_mode="HTML",
            reply_markup=topup_quick_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "topup:custom")
async def topup_custom(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(UserStates.waiting_topup_amount)
    await _safe_edit(
        call,
        "Введите сумму пополнения в рублях (целое число).",
        reply_markup=topup_quick_kb(),
    )


@router.callback_query(F.data.startswith("topup:amount:"))
async def topup_quick_amount(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    try:
        rub = int(parts[2])
    except Exception:
        return
    if rub <= 0:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        await _issue_invoice(call.bot, call.from_user.id, db, user["id"], rub)
        await state.clear()
        await _safe_edit(call, f"Счёт выставлен на {rub} ₽. Оплатите, чтобы баланс пополнился.")
    finally:
        await db.close()


@router.callback_query(F.data.startswith("topup:days:"))
async def topup_days(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    try:
        days = int(parts[2])
    except Exception:
        return
    if days <= 0:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return

        day_price = await get_int_setting(db, "proxy_day_price", 0)
        if day_price <= 0:
            await _safe_edit(call, "Дневная цена = 0. Пополнение не требуется.")
            return

        proxies = await dao.list_proxies_by_user(db, user["id"])
        total = len(proxies)
        if total == 0:
            await _safe_edit(call, "У вас нет прокси.")
            return

        max_active = await get_int_setting(db, "max_active_proxies", 0)
        desired = min(total, max_active) if max_active > 0 else total

        required = day_price * desired * days
        if user["balance"] >= required:
            await _safe_edit(
                call,
                f"Баланса уже хватает на {days} дней для {desired} прокси.\n"
                "Если хотите, можете пополнить дополнительно.",
                reply_markup=topup_quick_kb(),
            )
            return

        need = required - int(user["balance"])
        await _issue_invoice(call.bot, call.from_user.id, db, user["id"], need)
        await state.clear()
        await _safe_edit(
            call,
            f"Счёт выставлен на {need} ₽.\n"
            f"Расчёт на {days} дней для {desired} прокси.",
            reply_markup=topup_quick_kb(),
        )
    finally:
        await db.close()


@router.message(UserStates.waiting_topup_amount)
async def topup_amount(message: Message, state: FSMContext) -> None:
    config = runtime.config
    if config is None:
        return
    try:
        rub = int(message.text.strip())
    except Exception:
        db = await get_db(config.db_path)
        try:
            await _send_or_edit_main_message(message, db, "Введите целое число.", reply_markup=topup_quick_kb())
        finally:
            await db.close()
        return

    if rub <= 0:
        db = await get_db(config.db_path)
        try:
            await _send_or_edit_main_message(message, db, "Сумма должна быть больше 0.", reply_markup=topup_quick_kb())
        finally:
            await db.close()
        return

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, message.from_user.id)
        if not user:
            await _send_or_edit_main_message(message, db, "Нажмите /start")
            return
        await _issue_invoice(message.bot, message.from_user.id, db, user["id"], rub)
        await state.clear()
    finally:
        await db.close()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        sp = message.successful_payment
        provider_payment_id = sp.telegram_payment_charge_id
        existing = await dao.get_payment_by_provider_id(db, provider_payment_id)
        if existing:
            return

        payload = sp.invoice_payload
        parts = payload.split(":")
        if len(parts) < 5:
            return
        user_id = int(parts[1])
        rub = int(parts[2])
        stars = int(parts[3])
        payment_id = int(parts[4])

        if sp.total_amount != stars:
            await dao.update_payment_status(db, payment_id, "failed", provider_payment_id)
            return

        payment = await dao.get_payment_by_id(db, payment_id)
        if not payment or payment["user_id"] != user_id:
            return

        await dao.update_payment_status(db, payment_id, "paid", provider_payment_id)
        await dao.add_user_balance(db, user_id, rub)
        reenabled = await reenable_proxies_for_user(db, user_id)
        user = await dao.get_user_by_id(db, user_id)
        active = await dao.count_active_proxies(db, user_id=user_id) if user else 0
        balance = user["balance"] if user else 0
        header = f"Баланс: {balance} ₽ | Активных прокси: {active}"
        if reenabled:
            await _send_or_edit_main_message(
                message,
                db,
                f"{header}\n\nБаланс пополнен на {rub} ₽.\n"
                "Прокси снова активны. Откройте «Мои прокси» для ссылок.",
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
        else:
            await _send_or_edit_main_message(
                message,
                db,
                f"{header}\n\nБаланс пополнен на {rub} ₽.",
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
    finally:
        await db.close()
