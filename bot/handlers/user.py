from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, LabeledPrice

from bot import dao
from bot.db import get_db
from bot.handlers.states import UserStates
from bot.keyboards import main_menu_inline_kb, proxies_list_kb, proxy_detail_kb, proxies_empty_kb, proxy_delete_confirm_kb
from bot.runtime import runtime
from bot.services.settings import (
    get_int_setting,
    get_decimal_setting,
    get_bool_setting,
    convert_rub_to_stars,
)
from bot.utils import (
    generate_login,
    generate_password,
    generate_ref_code,
    build_proxy_link,
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


async def _get_user_and_header(db, tg_id: int) -> tuple[object | None, str | None]:
    user = await dao.get_user_by_tg_id(db, tg_id)
    if not user:
        return None, None
    active = await dao.count_active_proxies(db, user_id=user["id"])
    header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
    return user, header


async def _safe_edit(call: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await call.message.answer(text, reply_markup=reply_markup)


def _normalize_login(login: str, prefix: str) -> str:
    return f"{prefix}{login}".lower()


async def _create_proxy_for_user(db, user_id: int, is_free: int) -> dict:
    provider = runtime.proxy_provider
    if provider is None:
        raise RuntimeError("Proxy provider not initialized")

    login = _normalize_login(generate_login(), "tgunlockrobot_")
    password = generate_password()
    ip, port = await provider.create_proxy(login, password)
    await dao.create_proxy(
        db,
        user_id=user_id,
        login=login,
        password=password,
        ip=ip,
        port=port,
        status="active",
        is_free=is_free,
    )
    return {"login": login, "password": password, "ip": ip, "port": port}


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


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    config = runtime.config
    if config is None:
        await message.answer("Бот не настроен.")
        return

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id_any(db, message.from_user.id)
        if user and user["deleted_at"]:
            await dao.delete_user(db, user["id"])
            user = None

        if user:
            if user["blocked_at"]:
                await message.answer("Ваш аккаунт заблокирован.")
                return
            await db.execute(
                "UPDATE users SET username = ? WHERE tg_id = ?",
                (message.from_user.username, message.from_user.id),
            )
            await db.commit()
            await dao.update_user_last_seen(db, message.from_user.id)
            user_row, header = await _get_user_and_header(db, message.from_user.id)
            text = f"{header}\n\nГлавное меню" if header else "Главное меню"
            await message.answer(text, reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)))
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
            link = build_proxy_link(proxy["ip"], proxy["port"], proxy["login"], proxy["password"])
            user_row, header = await _get_user_and_header(db, message.from_user.id)
            prefix = f"{header}\n\n" if header else ""
            await message.answer(
                prefix
                + "Добро пожаловать! Ваш бесплатный прокси готов:\n"
                f"{link}\n\n"
                "Нажмите на ссылку → Telegram откроет настройки прокси → Добавьте прокси → "
                "Включайте и выключайте в настройках Telegram.\n\n"
                f"IP: {proxy['ip']}\nПорт: {proxy['port']}\nЛогин: {proxy['login']}\nПароль: {proxy['password']}",
                reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)),
            )
        except Exception:
            await message.answer(
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
        await message.answer(
            prefix
            + "Инструкция:\n"
            "1) Нажмите на ссылку прокси.\n"
            "2) Telegram откроет настройки прокси.\n"
            "3) Добавьте прокси и включайте/выключайте в настройках Telegram.\n\n"
            "Если ссылка не открывается — введите данные вручную (IP, порт, логин, пароль).",
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
            "1) Нажмите на ссылку прокси.\n"
            "2) Telegram откроет настройки прокси.\n"
            "3) Добавьте прокси и включайте/выключайте в настройках Telegram.\n\n"
            "Если ссылка не открывается — введите данные вручную (IP, порт, логин, пароль).",
            reply_markup=main_menu_inline_kb(_is_admin(call.from_user.id)),
        )
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
        lines = [f"{header}", "", "Ваши прокси:"]
        for idx, p in enumerate(proxies, 1):
            link = build_proxy_link(p["ip"], p["port"], p["login"], p["password"])
            lines.append(f"{idx}. {p['login']} — {link}")
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
        link = build_proxy_link(proxy["ip"], proxy["port"], proxy["login"], proxy["password"])
        active = await dao.count_active_proxies(db, user_id=user["id"])
        header = f"Баланс: {user['balance']} ₽ | Активных прокси: {active}"
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Новый прокси создан:\n"
            f"{link}\n\n"
            f"IP: {proxy['ip']}\nПорт: {proxy['port']}\nЛогин: {proxy['login']}\nПароль: {proxy['password']}",
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
        link = build_proxy_link(proxy["ip"], proxy["port"], proxy["login"], proxy["password"])
        user = await dao.get_user_by_id(db, proxy["user_id"])
        active = await dao.count_active_proxies(db, user_id=proxy["user_id"]) if user else 0
        balance = user["balance"] if user else 0
        header = f"Баланс: {balance} ₽ | Активных прокси: {active}"
        await _safe_edit(
            call,
            f"{header}\n\n"
            "Ссылка на прокси:\n"
            f"{link}\n\n"
            f"IP: {proxy['ip']}\nПорт: {proxy['port']}\nЛогин: {proxy['login']}\nПароль: {proxy['password']}",
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
        link = build_proxy_link(proxy["ip"], proxy["port"], proxy["login"], proxy["password"])
        await _safe_edit(
            call,
            "Удалить прокси?\n"
            f"{link}\n\n"
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
    provider = runtime.proxy_provider
    if provider is None:
        return

    proxy_id = int(call.data.split(":")[-1])
    db = await get_db(config.db_path)
    try:
        proxy = await dao.get_proxy_by_id(db, proxy_id)
        if not proxy:
            await _safe_edit(call, "Прокси не найден.", reply_markup=proxy_detail_kb())
            return
        await provider.disable_proxy(proxy["login"])
        await dao.mark_proxy_deleted(db, proxy_id)
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
        await state.set_state(UserStates.waiting_topup_amount)
        await _safe_edit(call, f"{header}\n\nВведите сумму пополнения в рублях (целое число).")
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
        await message.answer("Введите целое число.")
        return

    if rub <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, message.from_user.id)
        if not user:
            await message.answer("Нажмите /start")
            return
        rate = await get_decimal_setting(db, "stars_rate", "1")
        stars = convert_rub_to_stars(rub, rate)
        payload = f"topup:{user['id']}:{rub}:{stars}"
        payment_id = await dao.create_payment(db, user_id=user["id"], amount=rub, status="pending", payload=payload)
        payload = f"{payload}:{payment_id}"
        await dao.update_payment_payload(db, payment_id, payload)

        prices = [LabeledPrice(label="Пополнение баланса", amount=stars)]
        await message.answer_invoice(
            title="Пополнение баланса",
            description=f"Пополнение на {rub} ₽",
            payload=payload,
            currency="XTR",
            prices=prices,
        )
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
        user = await dao.get_user_by_id(db, user_id)
        active = await dao.count_active_proxies(db, user_id=user_id) if user else 0
        balance = user["balance"] if user else 0
        header = f"Баланс: {balance} ₽ | Активных прокси: {active}"
        await message.answer(f"{header}\n\nБаланс пополнен на {rub} ₽.", reply_markup=main_menu_inline_kb(_is_admin(message.from_user.id)))
    finally:
        await db.close()
