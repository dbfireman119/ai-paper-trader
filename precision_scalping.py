"""Read-only NH PLUG WebSocket feed for precision scalping.
No brokerage order functions are imported or called.
"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

_LOCK = threading.RLock()
_STATE = {
    "status": "idle", "codes": [], "trade_count": 0, "book_count": 0,
    "last_trade_at": None, "last_book_at": None, "last_error": None,
    "last_trade": {}, "last_book": {}, "field_names": [],
}
_STARTED = False


def _body(message):
    body = message.get("body") if isinstance(message, dict) else None
    return body if isinstance(body, dict) else {}


def _stamp():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _trade_callback(message):
    body = _body(message)
    if not body:
        return
    with _LOCK:
        code = str(body.get("tr_key") or body.get("code") or message.get("header", {}).get("tr_key") or "")
        _STATE["trade_count"] += 1
        _STATE["last_trade_at"] = _stamp()
        _STATE["last_trade"] = {"code": code, "body": body}
        _STATE["field_names"] = sorted(set(_STATE["field_names"]) | set(body.keys()))


def _book_callback(message):
    body = _body(message)
    if not body:
        return
    with _LOCK:
        code = str(body.get("tr_key") or body.get("code") or message.get("header", {}).get("tr_key") or "")
        _STATE["book_count"] += 1
        _STATE["last_book_at"] = _stamp()
        _STATE["last_book"] = {"code": code, "body": body}
        _STATE["field_names"] = sorted(set(_STATE["field_names"]) | set(body.keys()))


def _run_channel(codes, tr_cd, callback):
    from nhplug.realtime import subscribe
    while True:
        try:
            with _LOCK:
                _STATE["status"] = "connecting"
                _STATE["last_error"] = None
            subscribe(codes, callback, tr_cd=tr_cd, timeout=30)
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = f"{tr_cd}: {exc}"
                _STATE["status"] = "error"
        with _LOCK:
            if _STATE["trade_count"] or _STATE["book_count"]:
                _STATE["status"] = "receiving"


def start_precision_feed(codes):
    """Start at most two SDK-managed WS sessions for selected candidates."""
    global _STARTED
    normalized = list(dict.fromkeys(str(c).zfill(6) for c in codes if str(c).isdigit()))
    normalized = normalized[:20]
    if not normalized:
        return False
    with _LOCK:
        if _STARTED:
            # Refresh tracked candidate list for display; the worker will reconnect on timeout.
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


def get_precision_feed_state():
    with _LOCK:
        return {
            **_STATE,
            "last_trade": dict(_STATE["last_trade"]),
            "last_book": dict(_STATE["last_book"]),
            "field_names": list(_STATE["field_names"]),
            "codes": list(_STATE["codes"]),
        }
