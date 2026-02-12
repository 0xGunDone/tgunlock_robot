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


def extract_ref_code(start_param: str | None) -> str | None:
    if not start_param:
        return None
    value = start_param.strip()
    match = re.match(r"^ref[_-](\w+)$", value)
    if match:
        return match.group(1)
    if re.match(r"^[A-Za-z0-9]+$", value):
        return value
    return None
