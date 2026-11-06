"""Namuh PLUG (NH Investment & Securities) read-only quote adapter.

This module deliberately exposes quote retrieval only. It contains no order
endpoints and cannot place real or simulated brokerage orders.
"""
from __future__ import annotations

import os
from typing import Any


def _configured() -> bool:
    return bool(
        os.getenv("NHPLUG_APP_KEY") and os.getenv("NHPLUG_APP_SECRET")
    )


def get_current_price(code: str, market: str = "KRX") -> dict[str, Any]:
    """Return normalized quote data for a Korean stock code."""
    if not _configured():
        raise RuntimeError(
            "Render 환경변수 NHPLUG_APP_KEY / NHPLUG_APP_SECRET가 설정되지 않았습니다."
        )

    # Namuh PLUG production token is issued by api.nhplug.com.
    # Quote requests can be routed to the mock endpoint using NHPLUG_BASE_URL.
    os.environ.setdefault("NHPLUG_AUTH_URL", "https://api.nhplug.com:8443")
    os.environ.setdefault("NHPLUG_BASE_URL", "https://moapi.nhplug.com:8443")

    from nhplug import call

    data = call(
        "/krstock/quote/v1/currentPrice",
        {"iem_cd": str(code).zfill(6), "market_cd": market},
    )
    output = data.get("Output_0") if isinstance(data, dict) else None
    if not isinstance(output, dict) or not output:
        message = data.get("rsp_msg") if isinstance(data, dict) else str(data)
        raise RuntimeError(f"나무증권 현재가 응답을 확인할 수 없습니다: {message or data}")

    price = output.get("stck_prpr")
    if price in (None, ""):
        raise RuntimeError(f"현재가 필드(stck_prpr)가 응답에 없습니다: {output}")

    return {
        "code": str(code).zfill(6),
        "name": str(output.get("iem_nm") or code),
        "price": int(float(price)),
        "raw": output,
    }
