"""Background full-market technical scan using NHPLUG stock master and daily bars."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from nhplug.instruments import load_master
from nh_api import get_daily_history

_LOCK = threading.RLock()
_STATE = {
    "status": "idle", "total": 0, "done": 0, "success": 0, "failed": 0,
    "market": {}, "started_at": None, "finished_at": None, "error": None,
}


def _clean(value) -> str:
    return str(value or "").strip()


def _stock_universe() -> list[dict]:
    master = load_master("m_new_stock")
    if not isinstance(master, pd.DataFrame):
        master = pd.DataFrame(master)
    required = {"sCode", "sMarket", "sKorName"}
    missing = required - set(master.columns)
    if missing:
        raise RuntimeError(f"NH 종목마스터 필드 누락: {', '.join(sorted(missing))}")

    # KRX common/preferred stock listings only; exclude ETN/ETF and non-equity rows.
    rows = []
    for _, row in master.iterrows():
        code = _clean(row.get("sCode"))
        market_code = _clean(row.get("sMarket"))
        name = _clean(row.get("name") or row.get("sKorName")).lstrip("*#").strip()
        if len(code) != 6 or not code.isdigit() or market_code not in {"1", "4"} or not name:
            continue
        if _clean(row.get("eCapSize")) == "":
            continue
        if _clean(row.get("gVenture")) == "8":  # ETF
            continue
        rows.append({
            "code": code, "name": name,
            "market": "KOSPI" if market_code == "1" else "KOSDAQ",
            "tradable": (
                _clean(row.get("eStop")) != "Y"
                and _clean(row.get("eUnder")) != "Y"
                and _clean(row.get("sltr_yn")) != "Y"
                and _clean(row.get("eWarn")) != "Y"
                and _clean(row.get("invt_epmd_issu_yn")) != "Y"
                and _clean(row.get("alert_gb")) in {"", "0"}
                and _clean(row.get("short_over_issu_cls_code")) in {"", "0"}
            ),
        })
    # De-duplicate without changing master order.
    unique = {}
    for row in rows:
        unique[row["code"]] = row
    return list(unique.values())


def _features(stock: dict) -> dict:
    rows = get_daily_history(stock["code"], "KRX", 80)
    df = pd.DataFrame(rows).copy()
    aliases = {"date": "bsop_date", "close": "stck_clpr", "volume": "acml_vol"}
    for target, source in aliases.items():
        if target not in df.columns and source in df.columns:
            df[target] = df[source]
    if not {"date", "close", "volume"}.issubset(df.columns):
        raise ValueError("일봉 날짜·종가·거래량 필드가 없습니다.")
    df["date"] = df["date"].astype(str)
    for col in ("close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "volume"]).sort_values("date").drop_duplicates("date")
    if len(df) < 60:
        raise ValueError(f"60거래일 미만({len(df)}일)")
    close, volume = df["close"], df["volume"]
    sma5, sma20, sma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
    ret5 = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
    avg_vol = volume.shift(1).rolling(20).mean().iloc[-1]
    volume_ratio = float(volume.iloc[-1] / avg_vol) if pd.notna(avg_vol) and avg_vol > 0 else 1.0
    daily_returns = close.pct_change().dropna().tail(20)
    volatility = float(daily_returns.std() * 100) if len(daily_returns) else 2.0
    trend = (1.0 if sma5 > sma20 else -1.0) + (1.0 if sma20 > sma60 else -1.0)
    return {
        **stock,
        "price": float(close.iloc[-1]),
        "prev": float(close.iloc[-2]),
        "volume_ratio": max(0.0, min(10.0, volume_ratio)),
        "momentum": max(-2.0, min(2.0, ret5 / 2.0)),
        "trend": float(trend),
        "risk": max(0.05, min(1.0, volatility / 5.0)),
        "history_date": str(df["date"].iloc[-1]),
        "quote_time": "일봉 기준",
    }


def _worker():
    try:
        universe = _stock_universe()
        with _LOCK:
            _STATE.update(status="running", total=len(universe), done=0, success=0,
                          failed=0, market={}, started_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                          finished_at=None, error=None)
        market = {}
        for stock in universe:
            try:
                q = _features(stock)
                market[q["code"]] = q
                with _LOCK:
                    _STATE["success"] += 1
            except Exception:
                with _LOCK:
                    _STATE["failed"] += 1
            finally:
                with _LOCK:
                    _STATE["done"] += 1
                    # Publish incremental results so the UI can show scan progress.
                    if _STATE["done"] % 25 == 0 or _STATE["done"] == _STATE["total"]:
                        _STATE["market"] = dict(market)
        with _LOCK:
            _STATE.update(status="complete", market=market,
                          finished_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat())
    except Exception as exc:
        with _LOCK:
            _STATE.update(status="error", error=str(exc),
                          finished_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat())


def start_scan(force: bool = False) -> bool:
    with _LOCK:
        if _STATE["status"] == "running":
            return False
        if _STATE["status"] == "complete" and not force:
            return False
        _STATE.update(status="starting", total=0, done=0, success=0, failed=0,
                      market={}, error=None, started_at=None, finished_at=None)
    thread = threading.Thread(target=_worker, name="nh-full-market-scan", daemon=True)
    thread.start()
    return True


def get_scan_state() -> dict:
    with _LOCK:
        return dict(_STATE, market=dict(_STATE["market"]))
