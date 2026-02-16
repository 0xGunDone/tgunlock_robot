from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def days_ago_iso(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).replace(microsecond=0).isoformat() + "Z"


async def get_user_by_tg_id(db: aiosqlite.Connection, tg_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM users WHERE tg_id = ? AND deleted_at IS NULL",
        (tg_id,),
    )
    return await cur.fetchone()


async def get_user_by_tg_id_any(db: aiosqlite.Connection, tg_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return await cur.fetchone()


async def get_user_by_id(db: aiosqlite.Connection, user_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return await cur.fetchone()


async def get_user_by_username(db: aiosqlite.Connection, username: str) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(?) AND deleted_at IS NULL",
        (username,),
    )
    return await cur.fetchone()


async def get_user_by_ref_code(db: aiosqlite.Connection, ref_code: str) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM users WHERE ref_code = ? AND deleted_at IS NULL",
        (ref_code,),
    )
    return await cur.fetchone()


async def create_user(
    db: aiosqlite.Connection,
    tg_id: int,
    username: Optional[str],
    ref_code: str,
    referred_by: Optional[str],
    balance: int,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO users (tg_id, username, ref_code, referred_by, balance, created_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tg_id, username, ref_code, referred_by, balance, now_iso(), now_iso()),
    )
    await db.commit()
    return cur.lastrowid


async def update_user_last_seen(db: aiosqlite.Connection, tg_id: int) -> None:
    await db.execute(
        "UPDATE users SET last_seen_at = ? WHERE tg_id = ?",
        (now_iso(), tg_id),
    )
    await db.commit()


async def update_user_last_menu_message_id(
    db: aiosqlite.Connection, tg_id: int, message_id: int
) -> None:
    await db.execute(
        "UPDATE users SET last_menu_message_id = ? WHERE tg_id = ?",
        (message_id, tg_id),
    )
    await db.commit()


async def update_user_low_balance_warn_at(
    db: aiosqlite.Connection, user_id: int, value: str
) -> None:
    await db.execute(
        "UPDATE users SET last_low_balance_warn_at = ? WHERE id = ?",
        (value, user_id),
    )
    await db.commit()


async def set_user_balance(db: aiosqlite.Connection, user_id: int, balance: int) -> None:
    await db.execute("UPDATE users SET balance = ? WHERE id = ?", (balance, user_id))
    await db.commit()


async def add_user_balance(db: aiosqlite.Connection, user_id: int, delta: int) -> None:
    await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (delta, user_id))
    await db.commit()


async def block_user(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute("UPDATE users SET blocked_at = ? WHERE id = ?", (now_iso(), user_id))
    await db.commit()


async def unblock_user(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute("UPDATE users SET blocked_at = NULL WHERE id = ?", (user_id,))
    await db.commit()


async def delete_user(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute(
        "DELETE FROM referral_events WHERE inviter_user_id = ? OR invited_user_id = ?",
        (user_id, user_id),
    )
    await db.execute("DELETE FROM referral_links WHERE owner_user_id = ?", (user_id,))
    await db.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM proxies WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await db.commit()


async def count_users(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT COUNT(*) AS cnt FROM users WHERE deleted_at IS NULL")
    row = await cur.fetchone()
    return int(row["cnt"])


async def count_active_users(db: aiosqlite.Connection, days: int) -> int:
    since = days_ago_iso(days)
    cur = await db.execute(
        "SELECT COUNT(*) AS cnt FROM users WHERE deleted_at IS NULL AND last_seen_at >= ?",
        (since,),
    )
    row = await cur.fetchone()
    return int(row["cnt"])


async def create_proxy(
    db: aiosqlite.Connection,
    user_id: int,
    login: str,
    password: str,
    ip: str,
    port: int,
    status: str,
    is_free: int,
    mtproto_secret: Optional[str] = None,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO proxies (
            user_id, login, password, ip, port, status, is_free, mtproto_secret, created_at, last_billed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            login,
            password,
            ip,
            port,
            status,
            is_free,
            mtproto_secret,
            now_iso(),
            now_iso(),
        ),
    )
    await db.commit()
    return cur.lastrowid


async def list_proxies_by_user(db: aiosqlite.Connection, user_id: int) -> List[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM proxies WHERE user_id = ? AND deleted_at IS NULL",
        (user_id,),
    )
    return await cur.fetchall()


async def list_active_proxies(db: aiosqlite.Connection) -> List[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM proxies WHERE status = 'active' AND deleted_at IS NULL"
    )
    return await cur.fetchall()


async def get_proxy_by_id(db: aiosqlite.Connection, proxy_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,))
    return await cur.fetchone()


async def update_proxy_password(db: aiosqlite.Connection, proxy_id: int, new_password: str) -> None:
    await db.execute("UPDATE proxies SET password = ? WHERE id = ?", (new_password, proxy_id))
    await db.commit()


async def update_proxy_mtproto_secret(db: aiosqlite.Connection, proxy_id: int, secret: str) -> None:
    await db.execute("UPDATE proxies SET mtproto_secret = ? WHERE id = ?", (secret, proxy_id))
    await db.commit()


async def set_proxy_status(db: aiosqlite.Connection, proxy_id: int, status: str) -> None:
    await db.execute("UPDATE proxies SET status = ? WHERE id = ?", (status, proxy_id))
    await db.commit()


async def set_proxies_status_by_user(
    db: aiosqlite.Connection, user_id: int, status: str
) -> None:
    await db.execute(
        "UPDATE proxies SET status = ? WHERE user_id = ? AND deleted_at IS NULL",
        (status, user_id),
    )
    await db.commit()


async def mark_proxy_deleted(db: aiosqlite.Connection, proxy_id: int) -> None:
    await db.execute(
        "UPDATE proxies SET status = 'deleted', deleted_at = ? WHERE id = ?",
        (now_iso(), proxy_id),
    )
    await db.commit()


async def count_active_proxies(db: aiosqlite.Connection, user_id: Optional[int] = None) -> int:
    if user_id is None:
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM proxies WHERE status = 'active'")
    else:
        cur = await db.execute(
            "SELECT COUNT(*) AS cnt FROM proxies WHERE status = 'active' AND user_id = ?",
            (user_id,),
        )
    row = await cur.fetchone()
    return int(row["cnt"])


async def update_proxy_last_billed(db: aiosqlite.Connection, proxy_id: int) -> None:
    await db.execute("UPDATE proxies SET last_billed_at = ? WHERE id = ?", (now_iso(), proxy_id))
    await db.commit()


async def update_proxies_last_billed_by_user(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute(
        "UPDATE proxies SET last_billed_at = ? WHERE user_id = ? AND deleted_at IS NULL",
        (now_iso(), user_id),
    )
    await db.commit()


async def get_active_proxies_for_billing(db: aiosqlite.Connection) -> List[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT p.*, u.balance AS user_balance, u.blocked_at AS user_blocked, "
        "u.deleted_at AS user_deleted, u.last_low_balance_warn_at AS user_warn_at "
        "FROM proxies p JOIN users u ON u.id = p.user_id "
        "WHERE p.status = 'active' AND p.deleted_at IS NULL AND u.deleted_at IS NULL"
    )
    return await cur.fetchall()


async def create_payment(
    db: aiosqlite.Connection,
    user_id: int,
    amount: int,
    status: str,
    payload: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO payments (user_id, amount, status, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, status, payload, now_iso()),
    )
    await db.commit()
    return cur.lastrowid


async def update_payment_status(
    db: aiosqlite.Connection,
    payment_id: int,
    status: str,
    provider_payment_id: Optional[str] = None,
) -> None:
    await db.execute(
        "UPDATE payments SET status = ?, provider_payment_id = ? WHERE id = ?",
        (status, provider_payment_id, payment_id),
    )
    await db.commit()


async def update_payment_payload(db: aiosqlite.Connection, payment_id: int, payload: str) -> None:
    await db.execute("UPDATE payments SET payload = ? WHERE id = ?", (payload, payment_id))
    await db.commit()


async def get_payment_by_id(db: aiosqlite.Connection, payment_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
    return await cur.fetchone()


async def get_payment_by_provider_id(
    db: aiosqlite.Connection, provider_payment_id: str
) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM payments WHERE provider_payment_id = ?", (provider_payment_id,)
    )
    return await cur.fetchone()


async def get_payments_sum(db: aiosqlite.Connection, since_iso: str) -> int:
    cur = await db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status = 'paid' AND created_at >= ?",
        (since_iso,),
    )
    row = await cur.fetchone()
    return int(row["total"])


async def get_settings_map(db: aiosqlite.Connection) -> Dict[str, str]:
    cur = await db.execute("SELECT key, value FROM settings")
    rows = await cur.fetchall()
    return {row["key"]: row["value"] for row in rows}


async def get_setting(db: aiosqlite.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    if row is None:
        return default
    return row["value"]


async def set_setting(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def get_open_support_ticket_by_user(
    db: aiosqlite.Connection, user_id: int
) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM support_tickets WHERE user_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    return await cur.fetchone()


async def get_support_ticket(db: aiosqlite.Connection, ticket_id: int) -> Optional[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
    return await cur.fetchone()


async def create_support_ticket(db: aiosqlite.Connection, user_id: int) -> int:
    now = now_iso()
    cur = await db.execute(
        "INSERT INTO support_tickets(user_id, status, created_at, updated_at) VALUES(?, 'open', ?, ?)",
        (user_id, now, now),
    )
    await db.commit()
    return int(cur.lastrowid)


async def set_support_ticket_status(db: aiosqlite.Connection, ticket_id: int, status: str) -> None:
    await db.execute(
        "UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), ticket_id),
    )
    await db.commit()


async def add_support_message(
    db: aiosqlite.Connection,
    ticket_id: int,
    sender_role: str,
    sender_id: int,
    message: str,
) -> None:
    now = now_iso()
    await db.execute(
        "INSERT INTO support_messages(ticket_id, sender_role, sender_id, message, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (ticket_id, sender_role, sender_id, message, now),
    )
    await db.execute(
        "UPDATE support_tickets SET updated_at = ? WHERE id = ?",
        (now, ticket_id),
    )
    await db.commit()


async def list_support_tickets(
    db: aiosqlite.Connection, status: str | None = "open", limit: int = 20, offset: int = 0
) -> List[aiosqlite.Row]:
    query = (
        "SELECT t.*, u.tg_id, u.username "
        "FROM support_tickets t "
        "JOIN users u ON u.id = t.user_id "
    )
    params: list[Any] = []
    if status:
        query += "WHERE t.status = ? "
        params.append(status)
    query += "ORDER BY t.updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur = await db.execute(query, params)
    return await cur.fetchall()


async def list_support_messages(
    db: aiosqlite.Connection, ticket_id: int, limit: int = 20
) -> List[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY id DESC LIMIT ?",
        (ticket_id, limit),
    )
    rows = await cur.fetchall()
    rows.reverse()
    return rows


async def insert_processed_update(db: aiosqlite.Connection, update_id: int) -> bool:
    cur = await db.execute(
        "INSERT OR IGNORE INTO processed_updates(update_id, created_at) VALUES(?, ?)",
        (update_id, now_iso()),
    )
    await db.commit()
    return cur.rowcount == 1


async def get_referral_link(db: aiosqlite.Connection, code: str) -> Optional[aiosqlite.Row]:
    cur = await db.execute(
        "SELECT * FROM referral_links WHERE code = ? AND disabled_at IS NULL",
        (code,),
    )
    return await cur.fetchone()


async def count_referral_events(db: aiosqlite.Connection, code: str) -> int:
    cur = await db.execute(
        "SELECT COUNT(*) AS cnt FROM referral_events WHERE link_code = ?",
        (code,),
    )
    row = await cur.fetchone()
    return int(row["cnt"])


async def count_referral_events_for_inviter(
    db: aiosqlite.Connection, code: str, inviter_user_id: int
) -> int:
    cur = await db.execute(
        "SELECT COUNT(*) AS cnt FROM referral_events WHERE link_code = ? AND inviter_user_id = ?",
        (code, inviter_user_id),
    )
    row = await cur.fetchone()
    return int(row["cnt"])


async def create_referral_event(
    db: aiosqlite.Connection,
    inviter_user_id: int,
    invited_user_id: int,
    link_code: str,
    bonus_inviter: int,
    bonus_invited: int,
) -> None:
    await db.execute(
        """
        INSERT INTO referral_events (inviter_user_id, invited_user_id, link_code, bonus_inviter, bonus_invited, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (inviter_user_id, invited_user_id, link_code, bonus_inviter, bonus_invited, now_iso()),
    )
    await db.commit()


async def create_referral_link(
    db: aiosqlite.Connection,
    code: str,
    name: str | None,
    owner_user_id: int | None,
    bonus_inviter: int,
    bonus_invited: int,
    limit_total: int | None,
    limit_per_user: int | None,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO referral_links
        (code, name, owner_user_id, bonus_inviter, bonus_invited, limit_total, limit_per_user, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code,
            name,
            owner_user_id,
            bonus_inviter,
            bonus_invited,
            limit_total,
            limit_per_user,
            now_iso(),
        ),
    )
    await db.commit()
    return cur.lastrowid


async def list_referral_links(db: aiosqlite.Connection) -> List[aiosqlite.Row]:
    cur = await db.execute("SELECT * FROM referral_links WHERE disabled_at IS NULL")
    return await cur.fetchall()


async def disable_referral_link(db: aiosqlite.Connection, code: str) -> None:
    await db.execute("UPDATE referral_links SET disabled_at = ? WHERE code = ?", (now_iso(), code))
    await db.commit()
