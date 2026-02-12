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
from bot.keyboards import admin_menu_kb, main_menu_kb, broadcast_filters_kb
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


@router.message(Command("admin"))
async def admin_start(message: Message) -> None:
    if not _require_admin(message):
        return
    await message.answer("Админка", reply_markup=admin_menu_kb())


@router.message(F.text == "⬅️ Назад")
async def admin_back(message: Message) -> None:
    if not _require_admin(message):
        return
    await message.answer("Главное меню", reply_markup=main_menu_kb())


@router.message(F.text == "📊 Статистика")
async def admin_stats(message: Message) -> None:
    if not _require_admin(message):
        return

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

        await message.answer(
            "Статистика:\n"
            f"Всего пользователей: {total_users}\n"
            f"Активные за 7 дней: {active_7}\n"
            f"Активных прокси: {active_proxies}\n"
            f"Отключённых прокси: {disabled_count}\n"
            f"Средний баланс: {avg_balance} ₽\n\n"
            f"Пополнения: день {sum_day} ₽, неделя {sum_week} ₽, месяц {sum_month} ₽"
        )
    finally:
        await db.close()


@router.message(F.text == "👤 Пользователи")
async def admin_users(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    await state.set_state(AdminStates.waiting_user_query)
    await message.answer("Введите tg_id или username пользователя.")


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
            "Действия: отправьте `+ сумма` или `- сумма` для изменения баланса, "
            "`block`/`unblock` для блокировки, `delete` для удаления.",
            parse_mode=None,
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
            for p in proxies:
                await dao.mark_proxy_deleted(db, p["id"])
            await dao.delete_user(db, user_id)
            await message.answer("Пользователь удалён.")
            return

        await message.answer("Неизвестная команда.")
    finally:
        await db.close()


@router.message(F.text == "🧦 Прокси")
async def admin_proxies(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
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
        await message.answer(
            "Прокси:\n"
            f"Активные: {row['active'] or 0}\n"
            f"Отключённые: {row['disabled'] or 0}\n"
            f"Удалённые: {row['deleted'] or 0}\n\n"
            "Введите tg_id пользователя для списка его прокси."
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


@router.message(F.text == "💳 Платежи")
async def admin_payments(message: Message) -> None:
    if not _require_admin(message):
        return
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
            await message.answer("Платежей нет.")
            return
        lines = [
            f"#{row['id']} user={row['user_id']} {row['amount']}₽ {row['status']} {row['created_at']}"
            for row in rows
        ]
        await message.answer("Последние платежи:\n" + "\n".join(lines))
    finally:
        await db.close()


@router.message(F.text == "⚙️ Настройки")
async def admin_settings(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return

    config = runtime.config
    if config is None:
        return

    db = await get_db(config.db_path)
    try:
        settings_map = await dao.get_settings_map(db)
        lines = [f"{k} = {v}" for k, v in sorted(settings_map.items())]
        await message.answer("Текущие настройки:\n" + "\n".join(lines))
        await message.answer("Отправьте: ключ значение (например: proxy_day_price 10)")
        await state.set_state(AdminStates.waiting_setting_input)
    finally:
        await db.close()


@router.message(AdminStates.waiting_setting_input)
async def admin_settings_set(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return

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


@router.message(F.text == "📦 Экспорт")
async def admin_export(message: Message) -> None:
    if not _require_admin(message):
        return
    await message.answer(
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


@router.message(F.text == "📣 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    await state.set_state(AdminStates.waiting_broadcast_text)
    await message.answer("Введите текст рассылки.")


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


@router.message(F.text == "🔗 Рефералы")
async def admin_referrals(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        links = await dao.list_referral_links(db)
        if links:
            lines = []
            for link in links:
                lines.append(
                    f"{link['code']} owner={link['owner_user_id'] or 0} "
                    f"bonus({link['bonus_inviter']}/{link['bonus_invited']}) "
                    f"limit({link['limit_total'] or 0}/{link['limit_per_user'] or 0})"
                )
            await message.answer("Ссылки:\n" + "\n".join(lines))
        else:
            await message.answer("Активных ссылок нет.")
    finally:
        await db.close()

    await state.set_state(AdminStates.waiting_referral_link)
    await message.answer(
        "Создание ссылки: отправьте строку\n"
        "code owner_tg_id bonus_inviter bonus_invited limit_total limit_per_user\n"
        "Если owner_tg_id = 0, бонус приглашающему не начисляется. Лимиты 0 = без лимита."
    )


@router.message(AdminStates.waiting_referral_link)
async def admin_referral_create(message: Message, state: FSMContext) -> None:
    if not _require_admin(message):
        return
    parts = message.text.strip().split()
    if len(parts) != 6:
        await message.answer("Неверный формат.")
        return

    code, owner_tg_id, bonus_inviter, bonus_invited, limit_total, limit_per_user = parts

    config = runtime.config
    if config is None:
        return
    db = await get_db(config.db_path)
    try:
        owner_tg_id_int = int(owner_tg_id)
        owner_user_id = None
        if owner_tg_id_int != 0:
            owner = await dao.get_user_by_tg_id(db, owner_tg_id_int)
            if not owner:
                await message.answer("Владелец не найден.")
                return
            owner_user_id = owner["id"]

        limit_total_int = int(limit_total)
        limit_per_user_int = int(limit_per_user)

        await dao.create_referral_link(
            db,
            code=code,
            name=None,
            owner_user_id=owner_user_id,
            bonus_inviter=int(bonus_inviter),
            bonus_invited=int(bonus_invited),
            limit_total=None if limit_total_int == 0 else limit_total_int,
            limit_per_user=None if limit_per_user_int == 0 else limit_per_user_int,
        )
        await message.answer("Ссылка создана.")
        await state.clear()
    finally:
        await db.close()
