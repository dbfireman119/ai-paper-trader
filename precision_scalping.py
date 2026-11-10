"""Read-only NH PLUG WebSocket collector and precision-scalping signal engine.

This module only consumes market data. It never imports or calls order APIs.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

_LOCK = threading.RLock()
_STATE = {
    "status": "idle", "codes": [], "trade_count": 0, "book_count": 0,
    "last_trade_at": None, "last_book_at": None, "last_error": None,
    "last_trade": {}, "last_book": {}, "field_names": [],
}
_STARTED = False
_TICKS = defaultdict(lambda: deque(maxlen=600))
_BOOKS = {}

def _stamp():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")

def _body(message):
    body = message.get("body") if isinstance(message, dict) else None
    return body if isinstance(body, dict) else {}

def _pick(data, names, default=None):
    if not isinstance(data, dict):
        return default
    lower = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        value = lower.get(str(name).lower())
        if value not in (None, ""):
            return value
    return default

def _number(value):
    try:
        if value is None:
            return None
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None

def _code(message, body):
    header = message.get("header", {}) if isinstance(message, dict) else {}
    value = _pick(body, ("tr_key", "code", "mksc_shrn_iscd", "stck_shrn_iscd"))
    if not value:
        value = _pick(header, ("tr_key", "code"))
    code = str(value or "").strip()
    return code.zfill(6) if code.isdigit() else code

def _trade_callback(message):
    body = _body(message)
    if not body:
        return
    code = _code(message, body)
    price = _number(_pick(body, (
        "stck_prpr", "price", "cntg_prc", "trade_price", "last_price", "prpr"
    )))
    volume = _number(_pick(body, (
        "cntg_vol", "trade_volume", "volume", "exec_qty", "ccld_qty"
    ), 0))
    trade_time = _pick(body, ("stck_cntg_hour", "cntg_hour", "trade_time", "time"))
    with _LOCK:
        _STATE["trade_count"] += 1
        _STATE["last_trade_at"] = _stamp()
        _STATE["last_trade"] = {"code": code, "body": body}
        _STATE["field_names"] = sorted(set(_STATE["field_names"]) | set(body.keys()))
        if code and price and price > 0:
            _TICKS[code].append({
                "price": price, "volume": max(0.0, volume or 0.0),
                "time": str(trade_time or _stamp()),
                "received_at": datetime.now(ZoneInfo("Asia/Seoul")).timestamp(),
            })

def _book_callback(message):
    body = _body(message)
    if not body:
        return
    code = _code(message, body)
    ask = _number(_pick(body, ("askp1", "ask_price1", "best_ask", "ask_price")))
    bid = _number(_pick(body, ("bidp1", "bid_price1", "best_bid", "bid_price")))
    ask_qty = _number(_pick(body, ("askp_rsqn1", "ask_qty1", "ask_remain_qty1", "best_ask_qty")))
    bid_qty = _number(_pick(body, ("bidp_rsqn1", "bid_qty1", "bid_remain_qty1", "best_bid_qty")))
    # Prefer total depth when supplied; otherwise aggregate the first five levels.
    total_ask = _number(_pick(body, ("total_askp_rsqn", "total_ask_qty", "total_ask_remain_qty")))
    total_bid = _number(_pick(body, ("total_bidp_rsqn", "total_bid_qty", "total_bid_remain_qty")))
    if total_ask is None:
        total_ask = sum((_number(_pick(body, (f"askp_rsqn{i}", f"ask_qty{i}"))) or 0) for i in range(1, 6))
    if total_bid is None:
        total_bid = sum((_number(_pick(body, (f"bidp_rsqn{i}", f"bid_qty{i}"))) or 0) for i in range(1, 6))
    with _LOCK:
        _STATE["book_count"] += 1
        _STATE["last_book_at"] = _stamp()
        _STATE["last_book"] = {"code": code, "body": body}
        _STATE["field_names"] = sorted(set(_STATE["field_names"]) | set(body.keys()))
        if code:
            _BOOKS[code] = {
                "ask": ask, "bid": bid, "ask_qty": ask_qty, "bid_qty": bid_qty,
                "total_ask": total_ask, "total_bid": total_bid,
                "received_at": datetime.now(ZoneInfo("Asia/Seoul")).timestamp(),
            }

def _run_channel(codes, tr_cd, callback):
    from nhplug.realtime import subscribe
    while True:
        try:
            with _LOCK:
                active_codes = list(_STATE["codes"]) or list(codes)
                _STATE["status"] = "connecting"
                _STATE["last_error"] = None
            subscribe(active_codes, callback, tr_cd=tr_cd, timeout=30)
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = f"{tr_cd}: {exc}"
                _STATE["status"] = "error"
        with _LOCK:
            if _STATE["trade_count"] or _STATE["book_count"]:
                _STATE["status"] = "receiving"

def start_precision_feed(codes):
    """Start at most two SDK-managed WebSocket sessions for selected candidates."""
    global _STARTED
    normalized = list(dict.fromkeys(str(c).zfill(6) for c in codes if str(c).isdigit()))[:20]
    if not normalized:
        return False
    with _LOCK:
        if _STARTED:
            _STATE["codes"] = normalized
            return True
        _STATE["codes"] = normalized
        _STATE["status"] = "starting"
        _STARTED = True
    threading.Thread(target=_run_channel, args=(normalized, "mc", _trade_callback),
                     name="precision-scalp-trades", daemon=True).start()
    threading.Thread(target=_run_channel, args=(normalized, "mb", _book_callback),
                     name="precision-scalp-orderbook", daemon=True).start()
    return True

def get_precision_signal(code, now=None):
    """Return a conservative short-term signal only when tick and book data are fresh."""
    import math
    import statistics
    now = now or datetime.now(ZoneInfo("Asia/Seoul")).timestamp()
    with _LOCK:
        ticks = list(_TICKS.get(str(code), ()))
        book = dict(_BOOKS.get(str(code), {}))
    if len(ticks) < 30 or not book:
        return {"ready": False, "reason": "체결 30건 및 호가 데이터 대기"}
    if now - ticks[-1]["received_at"] > 20 or now - book.get("received_at", 0) > 20:
        return {"ready": False, "reason": "실시간 데이터 지연"}
    prices = [x["price"] for x in ticks]
    volumes = [x["volume"] for x in ticks]
    if any(p <= 0 for p in prices):
        return {"ready": False, "reason": "비정상 체결가"}
    # Tick-based EMA, VWAP and RSI(14).
    def ema(values, span):
        alpha = 2.0 / (span + 1.0)
        result = values[0]
        for value in values[1:]:
            result = alpha * value + (1.0 - alpha) * result
        return result
    ema9 = ema(prices[-120:], 9)
    ema21 = ema(prices[-240:], 21)
    total_volume = sum(volumes[-120:])
    vwap = (sum(p * v for p, v in zip(prices[-120:], volumes[-120:])) / total_volume
            if total_volume > 0 else statistics.fmean(prices[-30:]))
    changes = [b - a for a, b in zip(prices[-16:-1], prices[-15:])]
    gains = sum(max(x, 0) for x in changes) / 14
    losses = sum(max(-x, 0) for x in changes) / 14
    rsi = 100.0 if losses == 0 and gains > 0 else 50.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    bid_depth = book.get("total_bid") or book.get("bid_qty") or 0
    ask_depth = book.get("total_ask") or book.get("ask_qty") or 0
    depth_sum = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / depth_sum if depth_sum > 0 else 0.0
    spread_pct = None
    if book.get("ask") and book.get("bid") and book["ask"] > 0:
        spread_pct = (book["ask"] - book["bid"]) / ((book["ask"] + book["bid"]) / 2) * 100
    last = prices[-1]
    recent_return = (last / prices[-6] - 1) * 100 if len(prices) >= 6 else 0.0
    ready = book.get("ask") is not None and book.get("bid") is not None and depth_sum > 0
    entry = bool(ready and ema9 > ema21 and last > vwap and 50 <= rsi <= 70
                 and imbalance >= 0.10 and recent_return > 0
                 and (spread_pct is None or 0 <= spread_pct <= 0.25))
    return {
        "ready": ready, "entry": entry, "price": last, "ema9": ema9, "ema21": ema21,
        "vwap": vwap, "rsi14": rsi, "imbalance": imbalance,
        "spread_pct": spread_pct, "recent_return_pct": recent_return,
        "reason": "진입 조건 충족" if entry else "EMA/VWAP/RSI/호가잔량 조건 미충족",
        "tick_count": len(ticks), "age_seconds": round(now - ticks[-1]["received_at"], 1),
    }

def get_precision_feed_state():
    with _LOCK:
        return {
            **_STATE,
            "last_trade": dict(_STATE["last_trade"]),
            "last_book": dict(_STATE["last_book"]),
            "field_names": list(_STATE["field_names"]),
            "codes": list(_STATE["codes"]),
        }
