from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.services.proxy_provider import ProxyProvider
from bot.config import Config


@dataclass
class Runtime:
    config: Optional[Config] = None
    proxy_provider: Optional[ProxyProvider] = None
    mtproxy_last_state: Optional[str] = None
    mtproxy_last_alert_ts: Optional[float] = None
    mtproxy_last_restart_ts: Optional[float] = None
    mtproxy_restart_required: bool = False
    bg_enabled: bool = True
    bg_path: Optional[str] = None
    last_freekassa_reconcile_ts: Optional[float] = None


runtime = Runtime()
