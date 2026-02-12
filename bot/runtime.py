from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.services.proxy_provider import ProxyProvider
from bot.config import Config


@dataclass
class Runtime:
    config: Optional[Config] = None
    proxy_provider: Optional[ProxyProvider] = None


runtime = Runtime()
