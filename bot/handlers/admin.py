from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from bot import dao
from bot.db import get_db
from bot.handlers.states import AdminStates
from bot.keyboards import admin_menu_inline_kb, main_menu_inline_kb, broadcast_filters_kb, admin_user_actions_kb, admin_settings_kb, admin_referrals_kb
from bot.runtime import runtime

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


async def _safe_edit(call: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await call.message.answer(text, reply_markup=reply_markup)


@router.message(Command("admin"))
async def admin_start(message: Message) -> None:
    if not _require_admin(message):
        return
    await message.answer("Админка", reply_markup=admin_menu_inline_kb())


@router.callback_query(F.data == "menu:admin")
async def admin_menu(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
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

        await _safe_edit(
            call,
            "Статистика:\n"
            f"Всего пользователей: {total_users}\n"
            f"Активные за 7 дней: {active_7}\n"
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
    await state.set_state(AdminStates.waiting_user_query)
    await call.message.answer("Введите tg_id или username пользователя.")


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
            await message.answer("Пользователь не найден.")
            await state.clear()
            return

        await state.update_data(admin_user_id=user["id"])
        await message.answer(
            "Профиль:\n"
            f"ID: {user['id']}\n"
            f"tg_id: {user['tg_id']}\n"
            f"username: @{user['username']}\n"
            f"Баланс: {user['balance']} ₽\n"
            f"Заблокирован: {'да' if user['blocked_at'] else 'нет'}\n"
            f"Дата регистрации: {user['created_at']}"
        )
        await message.answer(
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
                await message.answer("Неверный формат суммы.")
                return
            await dao.add_user_balance(db, user_id, delta)
            await message.answer("Баланс обновлён.")
            return

        if text == "block":
            await dao.block_user(db, user_id)
            await message.answer("Пользователь заблокирован.")
            return

        if text == "unblock":
            await dao.unblock_user(db, user_id)
            await message.answer("Пользователь разблокирован.")
            return

        if text == "delete":
            provider = runtime.proxy_provider
            proxies = await dao.list_proxies_by_user(db, user_id)
            if provider:
                for p in proxies:
                    try:
                        await provider.disable_proxy(p["login"])
                    except Exception:
                        continue
            await dao.delete_user(db, user_id)
            await message.answer("Пользователь удалён.")
            return

        await message.answer("Неизвестная команда.")
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
        elif action == "custom":
            await state.set_state(AdminStates.waiting_balance_delta)
            await state.update_data(balance_user_id=user_id)
            await call.message.answer("Введите сумму (можно со знаком -):")
            return
        elif action == "block":
            user = await dao.get_user_by_id(db, user_id)
            if user and user["blocked_at"]:
                await dao.unblock_user(db, user_id)
            else:
                await dao.block_user(db, user_id)
        elif action == "delete":
            provider = runtime.proxy_provider
            proxies = await dao.list_proxies_by_user(db, user_id)
            if provider:
                for p in proxies:
                    try:
                        await provider.disable_proxy(p["login"])
                    except Exception:
                        continue
            await dao.delete_user(db, user_id)
        elif action == "refresh":
            pass

        user = await dao.get_user_by_id(db, user_id)
        if not user:
            await _safe_edit(call, "Пользователь не найден.", reply_markup=admin_menu_inline_kb())
            return
        text = await _admin_user_profile(db, user_id)
        await _safe_edit(call, text, reply_markup=admin_user_actions_kb(user_id, bool(user["blocked_at"])))
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
        await message.answer("Введите целое число (можно со знаком -).")
        return

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await dao.add_user_balance(db, user_id, delta)
        user = await dao.get_user_by_id(db, user_id)
        if user:
            text = await _admin_user_profile(db, user_id)
            await message.answer(text, reply_markup=admin_user_actions_kb(user_id, bool(user["blocked_at"])))
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
        await message.answer("Введите числовой tg_id.")
        return

    tg_id = int(message.text.strip())
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        user = await dao.get_user_by_tg_id(db, tg_id)
        if not user:
            await message.answer("Пользователь не найден.")
            return
        proxies = await dao.list_proxies_by_user(db, user["id"])
        if not proxies:
            await message.answer("У пользователя нет прокси.")
            return
        lines = []
        for p in proxies:
            lines.append(f"{p['login']} {p['ip']}:{p['port']} статус={p['status']}")
        await message.answer("Прокси пользователя:\n" + "\n".join(lines))
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
        lines = [f"{k} = {v}" for k, v in sorted(settings_map.items())]
        await _safe_edit(
            call,
            "Текущие настройки:\n" + "\n".join(lines),
            reply_markup=admin_menu_inline_kb(),
        )
        await call.message.answer("Выберите параметр или отправьте: ключ значение")
        await call.message.answer("Настройки:", reply_markup=admin_settings_kb())
        await state.set_state(AdminStates.waiting_setting_input)
    finally:
        await db.close()


@router.message(AdminStates.waiting_setting_input)
async def admin_settings_set(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return

    data = await state.get_data()
    selected_key = data.get("setting_key")

    if selected_key:
        key = selected_key
        value = message.text.strip()
    else:
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.answer("Формат: ключ значение")
            return
        key, value = parts
    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        await dao.set_setting(db, key, value)
        await message.answer("Настройка обновлена.")
        await state.clear()
    finally:
        await db.close()


@router.callback_query(F.data.startswith("admin_settings:"))
async def admin_settings_pick(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    key = call.data.split(":", 1)[1]
    await state.update_data(setting_key=key)
    await call.message.answer(f"Введите значение для `{key}`:", parse_mode=None)


@router.callback_query(F.data == "admin:export")
async def admin_export(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await _safe_edit(
        call,
        "Экспорт CSV: отправьте одно из слов: users, users_balances, proxies, payments, referrals"
    )


@router.message(F.text)
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
        await message.answer_document(file)
    finally:
        await db.close()


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_broadcast_text)
    await call.message.answer("Введите текст рассылки.")


@router.message(AdminStates.waiting_broadcast_text)
async def admin_broadcast_text(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    await state.update_data(broadcast_text=message.text)
    await message.answer("Выберите аудиторию:", reply_markup=broadcast_filters_kb())


@router.callback_query(F.data.startswith("broadcast:"))
async def admin_broadcast_send(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return

    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await call.message.answer("Рассылка отменена.")
        return

    data = await state.get_data()
    text = data.get("broadcast_text")
    if not text:
        await call.message.answer("Текст рассылки не задан.")
        return

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        query = "SELECT tg_id FROM users WHERE deleted_at IS NULL"
        params = []

        if action == "active7":
            since = (datetime.utcnow() - timedelta(days=7)).replace(microsecond=0).isoformat() + "Z"
            query += " AND last_seen_at >= ?"
            params.append(since)
        elif action == "active_proxies":
            query = (
                "SELECT DISTINCT u.tg_id FROM users u "
                "JOIN proxies p ON p.user_id = u.id "
                "WHERE u.deleted_at IS NULL AND p.status = 'active'"
            )
        elif action == "balance_pos":
            query += " AND balance > 0"

        cur = await db.execute(query, params)
        rows = await cur.fetchall()
        tg_ids = [row["tg_id"] for row in rows]

        await call.message.answer(f"Начинаю рассылку. Получателей: {len(tg_ids)}")
        delay = config.broadcast_delay_ms / 1000.0

        for tg_id in tg_ids:
            try:
                await call.message.bot.send_message(tg_id, text)
            except Exception:
                continue
            if delay:
                await asyncio.sleep(delay)

        await call.message.answer("Рассылка завершена.")
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
        if links:
            lines = []
            for link in links:
                cur = await db.execute(
                    "SELECT COUNT(*) AS cnt, COALESCE(SUM(bonus_inviter + bonus_invited), 0) AS total "
                    "FROM referral_events WHERE link_code = ?",
                    (link["code"],),
                )
                stats = await cur.fetchone()
                uses = int(stats["cnt"])
                total_bonus = int(stats["total"])
                lines.append(
                    f"{link['code']} owner={link['owner_user_id'] or 0} "
                    f"bonus({link['bonus_inviter']}/{link['bonus_invited']}) "
                    f"limit({link['limit_total'] or 0}/{link['limit_per_user'] or 0}) "
                    f"uses={uses} total_bonus={total_bonus}₽"
                )
            await _safe_edit(call, "Ссылки:\n" + "\n".join(lines), reply_markup=admin_menu_inline_kb())
        else:
            await _safe_edit(call, "Активных ссылок нет.", reply_markup=admin_menu_inline_kb())
    finally:
        await db.close()

    await call.message.answer(
        "Создание ссылки: нажмите кнопку и пройдите мастер.",
        reply_markup=admin_referrals_kb(),
    )


@router.callback_query(F.data == "admin:ref_create")
async def admin_ref_create(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(AdminStates.ref_code)
    await call.message.answer("Шаг 1/6. Введите код ссылки (латиница/цифры без пробелов).")


@router.message(AdminStates.ref_code)
async def admin_ref_code(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    code = message.text.strip()
    if not code.isalnum():
        await message.answer("Код должен состоять из латиницы и цифр, без пробелов.")
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        if await dao.get_user_by_ref_code(db, code):
            await message.answer("Код уже используется пользователем. Введите другой.")
            return
    finally:
        await db.close()
    await state.update_data(ref_code=code)
    await state.set_state(AdminStates.ref_owner)
    await message.answer("Шаг 2/6. Введите tg_id владельца (кому начислять бонус) или 0.")


@router.message(AdminStates.ref_owner)
async def admin_ref_owner(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Введите числовой tg_id или 0.")
        return
    owner_tg_id = int(text)
    owner_user_id = None
    if owner_tg_id != 0:
        config = runtime.config
        if config is None:
            return
        db = await get_db(config.db_path)
        try:
            owner = await dao.get_user_by_tg_id(db, owner_tg_id)
            if not owner:
                await message.answer("Владелец не найден. Введите другой tg_id или 0.")
                return
            owner_user_id = owner["id"]
        finally:
            await db.close()
    await state.update_data(ref_owner_user_id=owner_user_id)
    await state.set_state(AdminStates.ref_bonus_inviter)
    await message.answer("Шаг 3/6. Бонус приглашающему (рубли, 0 если не нужен).")


@router.message(AdminStates.ref_bonus_inviter)
async def admin_ref_bonus_inviter(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("Введите целое число.")
        return
    await state.update_data(ref_bonus_inviter=val)
    await state.set_state(AdminStates.ref_bonus_invited)
    await message.answer("Шаг 4/6. Бонус приглашённому (рубли, 0 если не нужен).")


@router.message(AdminStates.ref_bonus_invited)
async def admin_ref_bonus_invited(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("Введите целое число.")
        return
    await state.update_data(ref_bonus_invited=val)
    await state.set_state(AdminStates.ref_limit_total)
    await message.answer("Шаг 5/6. Общий лимит срабатываний (0 = без лимита).")


@router.message(AdminStates.ref_limit_total)
async def admin_ref_limit_total(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("Введите целое число.")
        return
    await state.update_data(ref_limit_total=val)
    await state.set_state(AdminStates.ref_limit_per_user)
    await message.answer("Шаг 6/6. Лимит на владельца (0 = без лимита).")


@router.message(AdminStates.ref_limit_per_user)
async def admin_ref_limit_per_user(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    try:
        val = int(message.text.strip())
    except Exception:
        await message.answer("Введите целое число.")
        return

    data = await state.get_data()
    code = data.get("ref_code")
    owner_user_id = data.get("ref_owner_user_id")
    bonus_inviter = int(data.get("ref_bonus_inviter") or 0)
    bonus_invited = int(data.get("ref_bonus_invited") or 0)
    limit_total = int(data.get("ref_limit_total") or 0)

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        await dao.create_referral_link(
            db,
            code=code,
            name=None,
            owner_user_id=owner_user_id,
            bonus_inviter=bonus_inviter,
            bonus_invited=bonus_invited,
            limit_total=None if limit_total == 0 else limit_total,
            limit_per_user=None if val == 0 else val,
        )
        await message.answer("Ссылка создана.")
        await state.clear()
    finally:
        await db.close()
