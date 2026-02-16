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
    topup_method_kb,
    freekassa_pay_kb,
    freekassa_method_kb,
    freekassa_amount_kb,
    back_main_kb,
    support_cancel_kb,
    support_admin_ticket_kb,
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
from bot.services.freekassa import create_order

FREEKASSA_FEE_PERCENT = 12.5
FREEKASSA_METHOD_OPTIONS = [
    {"key": "sbp_qr", "value": 44, "label": "СБП QR (НСПК)"},
    {"key": "card_rub", "value": 36, "label": "Банковская карта РФ"},
    {"key": "sberpay", "value": 43, "label": "СберPay"},
]
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
    force_new: bool = False,
) -> None:
    user = await dao.get_user_by_tg_id_any(db, message.from_user.id)
    last_id = None
    if not force_new:
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
    day_price = await get_int_setting(db, "proxy_day_price", 0)
    daily_cost = max(day_price, 0) * active
    if daily_cost > 0:
        days_left = int(user["balance"]) // daily_cost
        days_str = f"{days_left} д."
    else:
        days_str = "∞" if active > 0 and day_price == 0 else "—"
    header = (
        f"Баланс: {user['balance']} ₽ | Активных прокси: {active}\n"
        f"Стоимость/день: {daily_cost} ₽ | Хватит: {days_str}"
    )
    return user, header


async def _freekassa_method_flags(db) -> tuple[bool, bool, bool]:
    enable_44 = await get_bool_setting(db, "freekassa_method_44_enabled", True)
    enable_36 = await get_bool_setting(db, "freekassa_method_36_enabled", True)
    enable_43 = await get_bool_setting(db, "freekassa_method_43_enabled", True)
    return enable_44, enable_36, enable_43


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


def _fk_fee_amount(amount: int) -> str:
    total = amount * (1 + FREEKASSA_FEE_PERCENT / 100)
    return f"{total:.2f}".rstrip("0").rstrip(".")


def _fk_method_label(method_value: int) -> str:
    for item in FREEKASSA_METHOD_OPTIONS:
        if int(item["value"]) == int(method_value):
            return item["label"]
    return f"Метод {method_value}"


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


async def _start_freekassa_payment(db, user_id: int, tg_id: int, rub: int, method: int) -> dict:
    config = runtime.config
    if config is None:
        return {"error": "FreeKassa не настроена."}
    if not config.freekassa_shop_id or not config.freekassa_api_key:
        return {"error": "FreeKassa не настроена у администратора."}
    if not method:
        return {"error": "Ошибка FreeKassa: не удалось определить способ оплаты."}
    currency = "RUB"
    email = f"{tg_id}@telegram.org"
    ip = config.freekassa_ip or config.proxy_default_ip or "127.0.0.1"
    payment_id = await dao.create_payment(
        db,
        user_id=user_id,
        amount=rub,
        status="pending",
        payload=f"freekassa:{user_id}:{rub}",
    )
    total_amount = rub * (1 + FREEKASSA_FEE_PERCENT / 100)
    result = await create_order(
        api_base=config.freekassa_api_base,
        api_key=config.freekassa_api_key,
        shop_id=config.freekassa_shop_id,
        amount_rub=total_amount,
        method=method,
        email=email,
        ip=ip,
        payment_id=payment_id,
        currency=currency,
    )
    if result.get("error"):
        await dao.update_payment_status(db, payment_id, "failed", provider_payment_id=f"freekassa:{payment_id}")
        return {"error": f"Ошибка FreeKassa: {result['error']}"}
    pay_url = result.get("payment_link")
    if not pay_url:
        await dao.update_payment_status(db, payment_id, "failed", provider_payment_id=f"freekassa:{payment_id}")
        return {"error": "Ошибка FreeKassa: не получена ссылка на оплату."}
    return {"payment_id": payment_id, "pay_url": pay_url}




@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    config = runtime.config
    if config is None:
        await _send_bg_no_db(message, "Бот не настроен.")
        return
    await state.clear()

    db = await get_db(config.db_path)
    try:
        offer_enabled = await get_bool_setting(db, "offer_enabled", True)
        policy_enabled = await get_bool_setting(db, "policy_enabled", True)
        offer_url = await dao.get_setting(db, "offer_url", "") or ""
        policy_url = await dao.get_setting(db, "policy_url", "") or ""
        docs_lines = []
        if offer_enabled and offer_url:
            safe_offer = html_escape(offer_url, quote=True)
            docs_lines.append(f"📋 <a href=\"{safe_offer}\">Публичная оферта</a>")
        if policy_enabled and policy_url:
            safe_policy = html_escape(policy_url, quote=True)
            docs_lines.append(f"📋 <a href=\"{safe_policy}\">Политика конфиденциальности</a>")
        docs_text = ("\n\n" + "\n".join(docs_lines)) if docs_lines else ""

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
        text += docs_text
        await _send_or_edit_main_message(
            message,
            db,
            text,
            reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            parse_mode="HTML" if docs_text else None,
            force_new=True,
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
                "Если ссылка не открывается — введите host/port/secret вручную."
                + docs_text,
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
                parse_mode="HTML",
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


@router.callback_query(F.data == "menu:support")
async def menu_support(call: CallbackQuery, state: FSMContext) -> None:
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
        await state.set_state(UserStates.waiting_support_message)
        await _safe_edit(
            call,
            f"{header}\n\nОпишите проблему одним сообщением — мы ответим.",
            reply_markup=support_cancel_kb(),
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
            stars_enabled = await get_bool_setting(db, "stars_enabled", True)
            freekassa_enabled = await get_bool_setting(db, "freekassa_enabled", False)
            if stars_enabled and freekassa_enabled:
                pay_line = "Нажмите «⭐ Пополнить» и выберите Stars или FreeKassa."
            elif freekassa_enabled:
                pay_line = "Нажмите «⭐ Пополнить» и выберите FreeKassa."
            else:
                pay_line = "Нажмите «⭐ Пополнить» и выберите сумму."
            text = (
                f"{header}\n\n"
                "Как оплатить:\n"
                f"{pay_line}\n"
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
        _, header = await _get_user_and_header(db, call.from_user.id)
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
            _, header = await _get_user_and_header(db, call.from_user.id)
            await _safe_edit(call, f"{header}\n\nУ вас пока нет прокси.", reply_markup=proxies_empty_kb())
            return

        proxy_dicts = [
            {"id": p["id"], "login": p["login"]} for p in proxies
        ]
        _, header = await _get_user_and_header(db, call.from_user.id)
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
        _, header = await _get_user_and_header(db, call.from_user.id)
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
        _, header = await _get_user_and_header(db, user["tg_id"]) if user else (None, "Баланс: 0 ₽")
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
        _, header = await _get_user_and_header(db, call.from_user.id)
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
        stars_enabled = await get_bool_setting(db, "stars_enabled", True)
        freekassa_enabled = await get_bool_setting(db, "freekassa_enabled", False)
        if freekassa_enabled:
            enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)
            if not (enable_44 or enable_36 or enable_43):
                freekassa_enabled = False
        if not stars_enabled and not freekassa_enabled:
            await _safe_edit(call, f"{header}\n\nСпособы пополнения временно отключены.")
            return
        hint_enabled = await get_bool_setting(db, "stars_buy_hint_enabled", False)
        stars_url = await dao.get_setting(db, "stars_buy_url", "") or ""
        hint = ""
        if hint_enabled and stars_url:
            safe_url = html_escape(stars_url, quote=True)
            hint = f"\n\nЗВЕЗДЫ МОЖНО КУПИТЬ <a href=\"{safe_url}\">ТУТ</a>"
        await state.clear()
        await state.set_state(UserStates.waiting_topup_amount)
        await _safe_edit(
            call,
            f"{header}\n\nВведите сумму пополнения в рублях (целое число).{hint}",
            parse_mode="HTML" if hint else None,
            reply_markup=back_main_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("topup:method:"))
async def topup_method_select(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    method = parts[2]
    if method not in {"stars", "freekassa"}:
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        stars_enabled = await get_bool_setting(db, "stars_enabled", True)
        freekassa_enabled = await get_bool_setting(db, "freekassa_enabled", False)
        if method == "stars" and not stars_enabled:
            await _safe_edit(call, "Оплата Stars отключена.")
            return
        if method == "freekassa" and not freekassa_enabled:
            await _safe_edit(call, "Оплата FreeKassa отключена.")
            return
        data = await state.get_data()
        rub = data.get("topup_amount")
        if not rub:
            await state.set_state(UserStates.waiting_topup_amount)
            await _safe_edit(
                call,
                f"{header}\n\nВведите сумму пополнения в рублях (целое число).",
                reply_markup=back_main_kb(),
            )
            return

        if method == "freekassa":
            enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)
            if not (enable_44 or enable_36 or enable_43):
                await _safe_edit(call, "Способы оплаты FreeKassa отключены.")
                return
            await state.update_data(topup_method="freekassa", fk_amount=int(rub), fk_note=None)
            await _safe_edit(
                call,
                f"{header}\n\nСумма пополнения: {rub} ₽\nВыберите способ оплаты.",
                reply_markup=freekassa_method_kb(
                    int(rub),
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return

        hint = ""
        hint_enabled = await get_bool_setting(db, "stars_buy_hint_enabled", False)
        stars_url = await dao.get_setting(db, "stars_buy_url", "") or ""
        if hint_enabled and stars_url:
            safe_url = html_escape(stars_url, quote=True)
            hint = f"\n\nЗВЕЗДЫ МОЖНО КУПИТЬ <a href=\"{safe_url}\">ТУТ</a>"

        await state.update_data(topup_method=method)
        await _issue_invoice(call.bot, call.from_user.id, db, user["id"], int(rub))
        await state.clear()
        await _safe_edit(
            call,
            f"{header}\n\nСчёт выставлен на {rub} ₽. Оплатите, чтобы баланс пополнился.{hint}",
            parse_mode="HTML" if hint else None,
            reply_markup=back_main_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data == "fk:amounts_back")
async def freekassa_amounts_back(call: CallbackQuery, state: FSMContext) -> None:
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
        await state.update_data(topup_method="freekassa", fk_amount=None, fk_note=None)
        await state.set_state(UserStates.waiting_topup_amount)
        await _safe_edit(
            call,
            f"{header}\n\nВведите сумму пополнения в рублях (целое число).",
            reply_markup=back_main_kb(),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("fk:pay:"))
async def freekassa_pay(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    if not parts[2].isdigit():
        return
    method_value = int(parts[2])
    if method_value not in {44, 36, 43}:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        if not await get_bool_setting(db, "freekassa_enabled", False):
            await _safe_edit(call, "Оплата FreeKassa отключена.")
            return
        enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)

        data = await state.get_data()
        rub = data.get("fk_amount")
        note = data.get("fk_note") or ""
        if not rub:
            await _safe_edit(
                call,
                f"{header}\n\nВведите сумму пополнения в рублях (целое число).",
                reply_markup=back_main_kb(),
            )
            await state.set_state(UserStates.waiting_topup_amount)
            return

        rub_value = int(rub)
        if method_value == 44 and not enable_44:
            await _safe_edit(
                call,
                "СБП QR отключён в настройках.",
                reply_markup=freekassa_method_kb(
                    rub_value,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return
        if method_value == 36 and not enable_36:
            await _safe_edit(
                call,
                "Оплата картой отключена в настройках.",
                reply_markup=freekassa_method_kb(
                    rub_value,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return
        if method_value == 43 and not enable_43:
            await _safe_edit(
                call,
                "SberPay отключён в настройках.",
                reply_markup=freekassa_method_kb(
                    rub_value,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return
        fk = await _start_freekassa_payment(db, user["id"], call.from_user.id, rub_value, method_value)
        if fk.get("error"):
            await _safe_edit(
                call,
                fk["error"],
                reply_markup=freekassa_method_kb(
                    int(rub),
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return

        pay_url = fk["pay_url"]
        payment_id = fk["payment_id"]
        fee_total = _fk_fee_amount(rub_value)
        await state.clear()
        extra = f"\n{note}" if note else ""
        await _safe_edit(
            call,
            f"Оплата FreeKassa на {rub_value} ₽ (к оплате {fee_total} ₽)\n"
            f"{pay_url}\n\nПлатёж обработается автоматически после оплаты.{extra}",
            reply_markup=freekassa_pay_kb(payment_id, pay_url),
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("topup:custom"))
async def topup_custom(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(topup_method="stars", fk_amount=None, fk_note=None)
    await state.set_state(UserStates.waiting_topup_amount)
    await _safe_edit(
        call,
        "Введите сумму пополнения в рублях (целое число).",
        reply_markup=back_main_kb(),
    )


@router.callback_query(F.data.startswith("topup:amount:"))
async def topup_quick_amount(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) not in {3, 4}:
        return
    if len(parts) == 4:
        method = parts[2]
        amount_part = parts[3]
    else:
        method = "stars"
        amount_part = parts[2]
    if method not in {"stars", "freekassa"}:
        return
    try:
        rub = int(amount_part)
    except Exception:
        return
    if rub <= 0:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        if method == "freekassa":
            if not await get_bool_setting(db, "freekassa_enabled", False):
                await _safe_edit(call, "Оплата FreeKassa отключена.")
                return
            enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)
            if not (enable_44 or enable_36 or enable_43):
                await _safe_edit(call, "Способы оплаты FreeKassa отключены.")
                return
            await state.update_data(topup_method="freekassa", fk_amount=rub, fk_note=None)
            await state.set_state(None)
            await _safe_edit(
                call,
                f"{header}\n\nСумма пополнения: {rub} ₽\nВыберите способ оплаты.",
                reply_markup=freekassa_method_kb(
                    rub,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return

        if not await get_bool_setting(db, "stars_enabled", True):
            await _safe_edit(call, "Оплата Stars отключена.")
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
    if len(parts) not in {3, 4}:
        return
    if len(parts) == 4:
        method = parts[2]
        days_part = parts[3]
    else:
        method = "stars"
        days_part = parts[2]
    if method not in {"stars", "freekassa"}:
        return
    try:
        days = int(days_part)
    except Exception:
        return
    if days <= 0:
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user, header = await _get_user_and_header(db, call.from_user.id)
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
                reply_markup=freekassa_amount_kb(FREEKASSA_FEE_PERCENT)
                if method == "freekassa"
                else topup_quick_kb(method, show_method_back=True),
            )
            return

        need = required - int(user["balance"])
        if method == "freekassa":
            if not await get_bool_setting(db, "freekassa_enabled", False):
                await _safe_edit(call, "Оплата FreeKassa отключена.")
                return
            enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)
            if not (enable_44 or enable_36 or enable_43):
                await _safe_edit(call, "Способы оплаты FreeKassa отключены.")
                return
            note = f"Расчёт на {days} дней для {desired} прокси."
            await state.update_data(topup_method="freekassa", fk_amount=need, fk_note=note)
            await state.set_state(None)
            await _safe_edit(
                call,
                f"{header}\n\nСумма пополнения: {need} ₽\n{note}\nВыберите способ оплаты.",
                reply_markup=freekassa_method_kb(
                    need,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return

        if not await get_bool_setting(db, "stars_enabled", True):
            await _safe_edit(call, "Оплата Stars отключена.")
            return
        await _issue_invoice(call.bot, call.from_user.id, db, user["id"], need)
        await state.clear()
        await _safe_edit(
            call,
            f"Счёт выставлен на {need} ₽.\n"
            f"Расчёт на {days} дней для {desired} прокси.",
            reply_markup=topup_quick_kb(method, show_method_back=True),
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
            await _send_or_edit_main_message(
                message,
                db,
                "Введите целое число.",
                reply_markup=back_main_kb(),
            )
        finally:
            await db.close()
        return

    if rub <= 0:
        db = await get_db(config.db_path)
        try:
            await _send_or_edit_main_message(
                message,
                db,
                "Сумма должна быть больше 0.",
                reply_markup=back_main_kb(),
            )
        finally:
            await db.close()
        return

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, message.from_user.id)
        if not user:
            await _send_or_edit_main_message(message, db, "Нажмите /start")
            return
        stars_enabled = await get_bool_setting(db, "stars_enabled", True)
        freekassa_enabled = await get_bool_setting(db, "freekassa_enabled", False)
        enable_44 = enable_36 = enable_43 = False
        if freekassa_enabled:
            enable_44, enable_36, enable_43 = await _freekassa_method_flags(db)
            if not (enable_44 or enable_36 or enable_43):
                freekassa_enabled = False

        if not stars_enabled and not freekassa_enabled:
            await _send_or_edit_main_message(message, db, "Способы пополнения отключены.")
            return

        user_row, header = await _get_user_and_header(db, message.from_user.id)
        if stars_enabled and freekassa_enabled:
            hint = ""
            hint_enabled = await get_bool_setting(db, "stars_buy_hint_enabled", False)
            stars_url = await dao.get_setting(db, "stars_buy_url", "") or ""
            if hint_enabled and stars_url:
                safe_url = html_escape(stars_url, quote=True)
                hint = f"\n\nЗВЕЗДЫ МОЖНО КУПИТЬ <a href=\"{safe_url}\">ТУТ</a>"
            await state.update_data(topup_amount=rub)
            await state.set_state(None)
            await _send_or_edit_main_message(
                message,
                db,
                f"{header}\n\nСумма пополнения: {rub} ₽\nВыберите способ оплаты.{hint}",
                parse_mode="HTML" if hint else None,
                reply_markup=topup_method_kb(True, True),
            )
            return

        if freekassa_enabled:
            await state.update_data(topup_method="freekassa", fk_amount=rub, fk_note=None)
            await state.set_state(None)
            await _send_or_edit_main_message(
                message,
                db,
                f"{header}\n\nСумма пополнения: {rub} ₽\nВыберите способ оплаты.",
                reply_markup=freekassa_method_kb(
                    rub,
                    FREEKASSA_FEE_PERCENT,
                    enable_44,
                    enable_36,
                    enable_43,
                ),
            )
            return

        await _issue_invoice(message.bot, message.from_user.id, db, user["id"], rub)
        await state.clear()
        await _send_or_edit_main_message(
            message,
            db,
            f"{header}\n\nСчёт выставлен на {rub} ₽. Оплатите, чтобы баланс пополнился.",
            reply_markup=back_main_kb(),
        )
    finally:
        await db.close()


@router.message(UserStates.waiting_support_message)
async def support_message(message: Message, state: FSMContext) -> None:
    config = runtime.config
    if config is None:
        return
    text = (message.text or "").strip()
    if not text:
        db = await get_db(config.db_path)
        try:
            await _send_or_edit_main_message(
                message,
                db,
                "Напишите текстом, пожалуйста.",
                reply_markup=support_cancel_kb(),
            )
        finally:
            await db.close()
        return

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, message.from_user.id)
        if not user:
            await _send_or_edit_main_message(message, db, "Нажмите /start")
            return

        ticket = await dao.get_open_support_ticket_by_user(db, user["id"])
        if ticket:
            ticket_id = ticket["id"]
        else:
            ticket_id = await dao.create_support_ticket(db, user["id"])

        await dao.add_support_message(db, ticket_id, "user", message.from_user.id, text)

        # notify admins
        admin_ids = runtime.config.admin_tg_ids if runtime.config else []
        user_tag = f"@{message.from_user.username}" if message.from_user.username else "—"
        admin_text = (
            f"🆕 Поддержка #{ticket_id}\n"
            f"От: {user_tag} (tg_id: {message.from_user.id})\n\n"
            f"{text}"
        )
        for admin_id in admin_ids:
            try:
                await message.bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=support_admin_ticket_kb(ticket_id),
                )
            except Exception:
                pass

        user_row, header = await _get_user_and_header(db, message.from_user.id)
        await _send_or_edit_main_message(
            message,
            db,
            f"{header}\n\nСообщение отправлено в поддержку. Мы ответим здесь.",
            reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
        )
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data.startswith("fk:cancel:"))
async def freekassa_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    if not parts[2].isdigit():
        return
    payment_id = int(parts[2])

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, call.from_user.id)
        if not user:
            await _safe_edit(call, "Нажмите /start")
            return
        payment = await dao.get_payment_by_id(db, payment_id)
        if not payment or payment["user_id"] != user["id"]:
            await _safe_edit(call, "Платёж не найден.")
            return
        if payment["status"] == "paid":
            await _safe_edit(call, "Платёж уже оплачен.", reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
            return
        if payment["status"] != "canceled":
            await dao.update_payment_status(db, payment_id, "canceled", provider_payment_id=f"freekassa:{payment_id}")

        user_row, header = await _get_user_and_header(db, call.from_user.id)
        text = f"{header}\n\nПлатёж отменён." if header else "Платёж отменён."
        await _safe_edit(call, text, reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)))
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
        _, header = await _get_user_and_header(db, user["tg_id"]) if user else (None, "Баланс: 0 ₽")
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
