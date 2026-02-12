from __future__ import annotations

import re
import secrets
import string


def generate_login(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_ref_code(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_mtproto_secret() -> str:
    return secrets.token_hex(16)


def build_proxy_link(ip: str, port: int, login: str, password: str) -> str:
    return f"https://t.me/socks?server={ip}&port={port}&user={login}&pass={password}"


def extract_ref_code(start_param: str | None) -> str | None:
    if not start_param:
        return None
    match = re.match(r"^ref[_-](\w+)$", start_param.strip())
    if not match:
        return None
    return match.group(1)
