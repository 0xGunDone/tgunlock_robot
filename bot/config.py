from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class Config:
    bot_token: str
    webhook_url: str
    webhook_secret: str | None
    admin_tg_ids: List[int]
    db_path: str
    app_prefix: str
    proxy_provider: str
    proxy_default_ip: str
    proxy_default_port: int
    proxy_cmd_create: str | None
    proxy_cmd_update_password: str | None
    proxy_cmd_disable: str | None
    proxy_cmd_prefix: str | None
    broadcast_delay_ms: int
    billing_interval_sec: int
    mtproxy_secrets_file: str
    mtproxy_service: str | None


def _parse_int_list(value: str) -> List[int]:
    if not value:
        return []
    items = []
    for part in value.split(","):
        part = part.strip()
        if part:
            items.append(int(part))
    return items


def load_config() -> Config:
    if load_dotenv:
        load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL is required")

    return Config(
        bot_token=bot_token,
        webhook_url=webhook_url,
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip() or None,
        admin_tg_ids=_parse_int_list(os.getenv("ADMIN_TG_IDS", "")),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        app_prefix=os.getenv("APP_PREFIX", "").strip(),
        proxy_provider=os.getenv("PROXY_PROVIDER", "mock"),
        proxy_default_ip=os.getenv("PROXY_DEFAULT_IP", "127.0.0.1"),
        proxy_default_port=int(os.getenv("PROXY_DEFAULT_PORT", "1080")),
        proxy_cmd_create=os.getenv("PROXY_CMD_CREATE", "") or None,
        proxy_cmd_update_password=os.getenv("PROXY_CMD_UPDATE_PASSWORD", "") or None,
        proxy_cmd_disable=os.getenv("PROXY_CMD_DISABLE", "") or None,
        proxy_cmd_prefix=os.getenv("PROXY_CMD_PREFIX", "").strip() or None,
        broadcast_delay_ms=int(os.getenv("BROADCAST_DELAY_MS", "50")),
        billing_interval_sec=int(os.getenv("BILLING_INTERVAL_SEC", "3600")),
        mtproxy_secrets_file=os.getenv("MTPROXY_SECRETS_FILE", "data/mtproxy_secrets.txt"),
        mtproxy_service=os.getenv("MTPROXY_SERVICE", "mtproxy.service").strip() or None,
    )
