from __future__ import annotations

import hmac
import hashlib
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)


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
    try:
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
        logger.info(
            "FreeKassa create: method=%s amount=%s email=%s ip=%s",
            method,
            amount_value,
            email,
            ip,
        )

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                text = await resp.text()
                payment_link = resp.headers.get("Location")
                data: dict = {}
                try:
                    data = await resp.json(encoding="utf-8")
                    if "location" in data and not payment_link:
                        payment_link = data["location"]
                except Exception:
                    data = {"error": "Invalid JSON", "raw": text}

                logger.info(
                    "FreeKassa response: status=%s headers=%s body=%s",
                    resp.status,
                    dict(resp.headers),
                    data
                )

                if resp.status != 200:
                    return {"error": data.get("message") or data.get("error") or "FreeKassa error"}

                if not payment_link:
                    return {"error": "Не получена ссылка на оплату"}

                # Исправляем невалидные URL от Freekassa (пробелы в параметрах)
                if ' ' in payment_link and '?' in payment_link:
                    base, params = payment_link.split('?', 1)
                    payment_link = base + '?' + params.replace(' ', '%20')

                return {
                    "payment_link": payment_link,
                    "order_id": data.get("orderId") or data.get("id"),
                    "status": data.get("status"),
                }
    except Exception as exc:
        logger.error("FreeKassa create error: %s", exc, exc_info=True)
        return {"error": "FreeKassa error"}


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


def verify_notification(data: dict[str, str], shop_id: str, secret_word_2: str) -> bool:
    merchant_id = data.get("MERCHANT_ID") or data.get("merchant_id") or data.get("shopId") or ""
    amount = data.get("AMOUNT") or data.get("amount") or ""
    order_id = data.get("MERCHANT_ORDER_ID") or data.get("merchant_order_id") or data.get("orderId") or ""
    intid = data.get("intid") or data.get("INTID") or data.get("paymentId") or ""
    sign = (data.get("SIGN") or data.get("sign") or data.get("signature") or "").lower()

    if not (merchant_id and amount and sign):
        return False
    if str(merchant_id) != str(shop_id):
        return False

    candidates = []
    if order_id:
        candidates.append(f"{merchant_id}:{amount}:{secret_word_2}:{order_id}")
    if intid:
        candidates.append(f"{merchant_id}|{amount}|{intid}|{secret_word_2}")

    for sign_string in candidates:
        expected = hashlib.md5(sign_string.encode("utf-8")).hexdigest().lower()
        if expected == sign:
            return True
    return False


def amount_matches(expected_rub: int, amount_str: str, fee_percent: float | None = None) -> bool:
    try:
        got = Decimal(amount_str)
        want = Decimal(str(expected_rub))
        if got.quantize(Decimal("0.01")) == want.quantize(Decimal("0.01")):
            return True
        if fee_percent is None:
            return False
        fee = (want * Decimal(str(fee_percent)) / Decimal("100")).quantize(Decimal("0.01"))
        total = (want + fee).quantize(Decimal("0.01"))
        return got.quantize(Decimal("0.01")) == total
    except (InvalidOperation, ValueError):
        return False
