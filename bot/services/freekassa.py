from __future__ import annotations

import hmac
import hashlib
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any

import aiohttp


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def generate_api_signature(payload: dict, api_key: str) -> str:
    data_without_sig = {k: v for k, v in payload.items() if k != "signature"}
    sorted_keys = sorted(data_without_sig.keys())
    values = [_format_value(data_without_sig[key]) for key in sorted_keys]
    sign_string = "|".join(values)
    return hmac.new(api_key.encode("utf-8"), sign_string.encode("utf-8"), hashlib.sha256).hexdigest()


async def create_order(
    api_base: str,
    api_key: str,
    shop_id: str,
    amount_rub: int,
    method: int,
    email: str,
    ip: str,
    payment_id: int,
    currency: str = "RUB",
    description: str | None = None,
) -> Dict[str, Any]:
    amount_value = round(float(amount_rub), 2)
    if amount_value == int(amount_value):
        amount_value = int(amount_value)

    payload = {
        "shopId": int(shop_id),
        "nonce": int(time.time() * 1000),
        "paymentId": str(payment_id),
        "i": int(method),
        "email": email,
        "ip": ip,
        "amount": amount_value,
        "currency": currency,
    }
    if description:
        payload["description"] = description[:250]

    payload["signature"] = generate_api_signature(payload, api_key)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-KEY": api_key,
    }

    api_url = f"{api_base.rstrip('/')}/orders/create"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.post(api_url, json=payload, headers=headers) as resp:
            data = {}
            try:
                data = await resp.json(encoding="utf-8")
            except Exception:
                data = {"error": await resp.text()}

            if resp.status != 200:
                return {"error": data.get("message") or data.get("error") or "FreeKassa error"}

            link = data.get("location") or data.get("Location") or resp.headers.get("Location")
            if not link:
                return {"error": "Не получена ссылка на оплату"}

            link = _sanitize_url(link)

            return {
                "payment_link": link,
                "order_id": data.get("orderId") or data.get("id"),
                "status": data.get("status"),
            }


async def get_currencies(api_base: str, api_key: str, shop_id: str) -> Dict[str, Any]:
    payload = {
        "shopId": int(shop_id),
        "nonce": int(time.time() * 1000),
    }
    payload["signature"] = generate_api_signature(payload, api_key)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-KEY": api_key,
    }

    api_url = f"{api_base.rstrip('/')}/currencies"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.post(api_url, json=payload, headers=headers) as resp:
            data = {}
            try:
                data = await resp.json(encoding="utf-8")
            except Exception:
                data = {"error": await resp.text()}
            if resp.status != 200:
                return {"error": data.get("message") or data.get("error") or "FreeKassa error"}
            return data


def _pick_val(item: dict, *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _is_enabled(item: dict) -> bool:
    raw = _pick_val(item, "is_enabled", "enabled")
    if raw is None:
        return False
    val = raw.strip().lower()
    if val in {"1", "true", "yes"}:
        return True
    if val in {"0", "false", "no", ""}:
        return False
    return bool(val)


def _item_id(item: dict) -> int | None:
    raw = _pick_val(item, "id", "currency_id", "method_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _item_currency(item: dict) -> str:
    return (_pick_val(item, "currency", "cur") or "").upper()


async def resolve_method_id(
    api_base: str,
    api_key: str,
    shop_id: str,
    preferred_ids: list[int],
    currency: str = "RUB",
) -> int | None:
    data = await get_currencies(api_base=api_base, api_key=api_key, shop_id=shop_id)
    if data.get("error"):
        return None
    items = data.get("currencies") or data.get("data") or []
    if not items:
        return None
    available = {}
    for item in items:
        if not _is_enabled(item):
            continue
        if currency and _item_currency(item) != currency.upper():
            continue
        item_id = _item_id(item)
        if item_id is None:
            continue
        available[item_id] = item
    for pid in preferred_ids:
        if pid in available:
            return pid
    return None


def pick_rub_method(currencies: list[dict]) -> Optional[dict]:
    if not currencies:
        return None
    candidates = []
    for item in currencies:
        raw_enabled = str(item.get("is_enabled", "")).strip().lower()
        if raw_enabled in {"1", "true", "yes"}:
            enabled = True
        elif raw_enabled in {"0", "false", "no", ""}:
            enabled = False
        else:
            enabled = bool(raw_enabled)
        currency = str(item.get("currency") or "")
        if enabled and currency.upper() == "RUB":
            candidates.append(item)
    if not candidates:
        return None
    # приоритет популярных методов
    preferred_ids = [44, 42, 36, 43, 4, 8, 12, 13, 6, 1]
    for pid in preferred_ids:
        for item in candidates:
            try:
                if int(item.get("id")) == pid:
                    return item
            except Exception:
                continue
    # избегаем FKWallet, если есть альтернатива
    for item in candidates:
        name = str(item.get("name") or item.get("title") or "")
        if "fk" not in name.lower() or "wallet" not in name.lower():
            return item
    return candidates[0]


def verify_notification(data: dict[str, str], shop_id: str, secret_word_2: str) -> bool:
    merchant_id = data.get("MERCHANT_ID") or data.get("merchant_id") or ""
    amount = data.get("AMOUNT") or data.get("amount") or ""
    order_id = data.get("MERCHANT_ORDER_ID") or data.get("merchant_order_id") or ""
    sign = (data.get("SIGN") or data.get("sign") or "").lower()

    if not (merchant_id and amount and order_id and sign):
        return False
    if merchant_id != shop_id:
        return False

    sign_string = f"{merchant_id}:{amount}:{secret_word_2}:{order_id}"
    expected = hashlib.md5(sign_string.encode("utf-8")).hexdigest().lower()
    return expected == sign


def amount_matches(expected_rub: int, amount_str: str) -> bool:
    try:
        got = Decimal(amount_str)
        want = Decimal(str(expected_rub))
        return got.quantize(Decimal("0.01")) == want.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False


def _sanitize_url(url: str) -> str:
    if not url:
        return url
    if " " not in url:
        return url
    try:
        parts = urlsplit(url)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        query = urlencode(query_items, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        return url
