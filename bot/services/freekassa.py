from __future__ import annotations

import hmac
import hashlib
import time
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

            link = resp.headers.get("Location") or data.get("location")
            if not link:
                return {"error": "Не получена ссылка на оплату"}

            return {
                "payment_link": link,
                "order_id": data.get("orderId") or data.get("id"),
                "status": data.get("status"),
            }


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
