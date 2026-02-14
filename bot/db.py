from __future__ import annotations

import aiosqlite
import os
from typing import Any, Dict

DEFAULT_SETTINGS: Dict[str, str] = {
    "proxy_create_price": "100",
    "proxy_day_price": "10",
    "free_credit": "50",
    "stars_rate": "1",
    "stars_enabled": "1",
    "freekassa_enabled": "0",
    "freekassa_method_44_enabled": "1",
    "freekassa_method_36_enabled": "1",
    "freekassa_method_43_enabled": "1",
    "stars_buy_url": "",
    "stars_buy_hint_enabled": "0",
    "mtproto_enabled": "1",
    "mtproto_host": "",
    "mtproto_port": "9443",
    "ref_bonus_inviter": "10",
    "ref_bonus_invited": "10",
    "max_active_proxies": "10",
    "referral_enabled": "1",
}


async def get_db(db_path: str) -> aiosqlite.Connection:
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON;")
    await db.execute("PRAGMA journal_mode = WAL;")
    return db


async def init_db(db: aiosqlite.Connection) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            tg_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            ref_code TEXT,
            balance INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            last_menu_message_id INTEGER,
            last_low_balance_warn_at TEXT,
            referred_by TEXT,
            blocked_at TEXT,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            login TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            ip TEXT NOT NULL,
            port INTEGER NOT NULL,
            status TEXT NOT NULL,
            is_free INTEGER NOT NULL DEFAULT 0,
            mtproto_secret TEXT,
            created_at TEXT NOT NULL,
            last_billed_at TEXT,
            deleted_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            provider_payment_id TEXT,
            payload TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS referral_links (
            id INTEGER PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT,
            owner_user_id INTEGER,
            bonus_inviter INTEGER NOT NULL DEFAULT 0,
            bonus_invited INTEGER NOT NULL DEFAULT 0,
            limit_total INTEGER,
            limit_per_user INTEGER,
            created_at TEXT NOT NULL,
            disabled_at TEXT,
            FOREIGN KEY(owner_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS referral_events (
            id INTEGER PRIMARY KEY,
            inviter_user_id INTEGER NOT NULL,
            invited_user_id INTEGER NOT NULL,
            link_code TEXT NOT NULL,
            bonus_inviter INTEGER NOT NULL,
            bonus_invited INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(inviter_user_id) REFERENCES users(id),
            FOREIGN KEY(invited_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS processed_updates (
            id INTEGER PRIMARY KEY,
            update_id INTEGER UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_ref_code ON users(ref_code);
        CREATE INDEX IF NOT EXISTS idx_proxies_user_id ON proxies(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_referral_events_inviter ON referral_events(inviter_user_id);
        CREATE INDEX IF NOT EXISTS idx_referral_events_invited ON referral_events(invited_user_id);
        CREATE INDEX IF NOT EXISTS idx_referral_links_code ON referral_links(code);
        """
    )
    await db.commit()
    await _ensure_column(db, "users", "last_menu_message_id", "last_menu_message_id INTEGER")
    await _ensure_column(db, "users", "last_low_balance_warn_at", "last_low_balance_warn_at TEXT")
    await _ensure_column(db, "proxies", "mtproto_secret", "mtproto_secret TEXT")


async def _ensure_column(
    db: aiosqlite.Connection, table: str, column: str, ddl: str
) -> None:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    cols = {row["name"] for row in rows}
    if column in cols:
        return
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    await db.commit()


async def ensure_default_settings(db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM settings WHERE key IN ('mtproto_secret', 'socks_enabled')")
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (key, value),
        )
    await db.commit()
