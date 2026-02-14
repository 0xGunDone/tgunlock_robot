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
            "FreeKassa create: method=%s amount=%s amount_value=%s email=%s ip=%s",
            method,
            amount_rub,
            amount_value,
            email,
            ip,
        )
        logger.info("FreeKassa payload (без signature): %s", {k: v for k, v in payload.items() if k != "signature"})

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                text = await resp.text()
                logger.info("FreeKassa response: status=%s, text=%s", resp.status, text[:500])
                logger.info("FreeKassa response headers: %s", dict(resp.headers))
                
                payment_link = resp.headers.get("Location")
                logger.info("FreeKassa Location header: %s", payment_link)
                
                data: dict = {}
                try:
                    data = await resp.json(encoding="utf-8")
                    logger.info("FreeKassa response JSON: %s", data)
                    if "location" in data and not payment_link:
                        payment_link = data["location"]
                        logger.info("FreeKassa location from JSON: %s", payment_link)
                except Exception as e:
                    logger.error("Ошибка парсинга JSON ответа FreeKassa: %s", e)
                    data = {"error": "Invalid JSON", "raw": text}

                if resp.status != 200:
                    error_msg = data.get("message") or data.get("error") or "Unknown error"
                    logger.error("Ошибка FreeKassa при создании платежа: %s", error_msg)
                    return {"error": error_msg, "message": error_msg}

                if not payment_link:
                    error_msg = "Не получена ссылка на оплату от FreeKassa"
                    logger.error(error_msg)
                    logger.error("Response data: %s", data)
                    return {"error": error_msg, "message": error_msg}

                logger.info("FreeKassa платеж создан успешно: payment_link=%s", payment_link)
                return {
                    "payment_link": payment_link,
                    "order_id": data.get("orderId") or data.get("id"),
                    "status": data.get("status"),
                }
    except Exception as exc:
        logger.error("FreeKassa create error: %s", exc, exc_info=True)
        return {"error": "FreeKassa error", "message": str(exc)}


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
    merchant_id = data.get("MERCHANT_ID") or data.get("merchant_id") or ""
    amount = data.get("AMOUNT") or data.get("amount") or ""
    order_id = data.get("MERCHANT_ORDER_ID") or data.get("merchant_order_id") or ""
    sign = (data.get("SIGN") or data.get("sign") or "").lower()

    logger.info("FreeKassa webhook verify: merchant_id=%s, amount=%s, order_id=%s, sign=%s", 
                merchant_id, amount, order_id, sign[:10] + "..." if sign else "")

    if not (merchant_id and amount and order_id and sign):
        logger.warning("Недостаточно данных для проверки подписи")
        return False
    if merchant_id != shop_id:
        logger.warning("merchant_id не совпадает с shop_id: %s != %s", merchant_id, shop_id)
        return False

    sign_string = f"{merchant_id}:{amount}:{secret_word_2}:{order_id}"
    expected = hashlib.md5(sign_string.encode("utf-8")).hexdigest().lower()
    
    logger.info("FreeKassa sign_string: %s", sign_string.replace(secret_word_2, "***"))
    logger.info("FreeKassa expected: %s, got: %s, match: %s", expected, sign, expected == sign)
    
    return expected == sign


def amount_matches(expected_rub: int, amount_str: str) -> bool:
    try:
        got = Decimal(amount_str)
        want = Decimal(str(expected_rub))
        return got.quantize(Decimal("0.01")) == want.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False
