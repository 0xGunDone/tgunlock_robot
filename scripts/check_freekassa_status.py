#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.freekassa import generate_api_signature, get_order_status


def _pretty(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


async def _post_orders(
    api_base: str,
    api_key: str,
    shop_id: str,
    payment_id: str,
) -> dict:
    payload = {
        "shopId": int(shop_id),
        "nonce": int(time.time() * 1000),
        "paymentId": str(payment_id),
    }
    payload["signature"] = generate_api_signature(payload, api_key)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-KEY": api_key,
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.post(f"{api_base.rstrip('/')}/orders", json=payload, headers=headers) as resp:
            text = await resp.text()
            try:
                data = await resp.json(encoding="utf-8")
            except Exception:
                data = {"raw": text}
            return {"http_status": resp.status, "data": data}


async def _get_order_by_id(
    api_base: str,
    api_key: str,
    shop_id: str,
    order_id: str,
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-KEY": api_key,
    }
    url = f"{api_base.rstrip('/')}/orders/{order_id}?shopId={shop_id}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            try:
                data = await resp.json(encoding="utf-8")
            except Exception:
                data = {"raw": text}
            return {"http_status": resp.status, "data": data}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка статуса платежа FreeKassa")
    parser.add_argument("--payment-id", default="50", help="MERCHANT_ORDER_ID (id платежа в боте)")
    parser.add_argument("--intid", default="274922675", help="FreeKassa intid из webhook")
    args = parser.parse_args()

    load_dotenv()

    api_base = os.getenv("FREEKASSA_API_BASE", "https://api.fk.life/v1").strip()
    api_key = os.getenv("FREEKASSA_API_KEY", "").strip()
    shop_id = os.getenv("FREEKASSA_SHOP_ID", "").strip()
    if not api_key or not shop_id:
        raise RuntimeError("Нужны FREEKASSA_API_KEY и FREEKASSA_SHOP_ID в .env")

    print(f"API base: {api_base}")
    print(f"Shop ID: {shop_id}")
    print(f"Проверяем payment_id={args.payment_id}, intid={args.intid}")
    print()

    by_payment = await get_order_status(
        api_base=api_base,
        api_key=api_key,
        shop_id=shop_id,
        payment_id=int(args.payment_id),
    )
    print("=== get_order_status(payment_id) ===")
    print(_pretty(by_payment))
    print()

    orders_by_payment = await _post_orders(api_base, api_key, shop_id, args.payment_id)
    print("=== POST /orders (payment_id) ===")
    print(_pretty(orders_by_payment))
    print()

    orders_by_intid = await _post_orders(api_base, api_key, shop_id, args.intid)
    print("=== POST /orders (intid) ===")
    print(_pretty(orders_by_intid))
    print()

    by_intid_path = await _get_order_by_id(api_base, api_key, shop_id, args.intid)
    print("=== GET /orders/{intid} ===")
    print(_pretty(by_intid_path))


if __name__ == "__main__":
    asyncio.run(main())
