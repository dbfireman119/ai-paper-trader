"""Read-only NH live quote feed for a Korean equity paper-trading universe."""
from __future__ import annotations

import math
import streamlit as st
import pandas as pd

from nh_api import get_current_price, get_daily_history

# Small pilot universe. Expand after checking API load and paper-trading behavior.
UNIVERSE = [
    ("005930", "삼성전자", "KRX"),
    ("000660", "SK하이닉스", "KRX"),
    ("005380", "현대차", "KRX"),
    ("000270", "기아", "KRX"),
    ("035420", "NAVER", "KRX"),
    ("035720", "카카오", "KRX"),
    ("005490", "POSCO홀딩스", "KRX"),
    ("006400", "삼성SDI", "KRX"),
    ("012330", "현대모비스", "KRX"),
    ("034020", "두산에너빌리티", "KRX"),
]


@st.cache_data(ttl=1800, show_spinner=False)
def _daily_features(code: str, market: str) -> dict:
    rows = get_daily_history(code, market, 80)
    df = pd.DataFrame(rows).copy()
    aliases = {"date": "bsop_date", "close": "stck_clpr", "volume": "acml_vol"}
    for target, source in aliases.items():
        if target not in df.columns and source in df.columns:
            df[target] = df[source]
    for col in ("close", "volume"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "volume"]).sort_values("date").drop_duplicates("date")
    if len(df) < 26:
        raise RuntimeError(f"{code}: 기술적 기준 데이터가 부족합니다({len(df)}일).")
    close, volume = df["close"], df["volume"]
    sma5 = close.rolling(5).mean().iloc[-1]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma60 = close.rolling(60).mean().iloc[-1]
    ret5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
    avg_volume = volume.shift(1).rolling(20).mean().iloc[-1]
    ratio = volume.iloc[-1] / avg_volume if pd.notna(avg_volume) and avg_volume > 0 else 1.0
    returns = close.pct_change().dropna().tail(20)
    volatility = float(returns.std() * 100) if len(returns) else 2.0
    trend = (1.0 if sma5 > sma20 else -1.0) + (1.0 if sma20 > sma60 else -1.0)
    return {
        "prev_close": float(close.iloc[-1]),
        "trend": float(trend),
        "momentum": max(-2.0, min(2.0, float(ret5) / 2.0)),
        "daily_volume_ratio": max(0.1, min(8.0, float(ratio))),
        "risk": max(0.05, min(1.0, volatility / 5.0)),
        "history_date": str(df["date"].iloc[-1]),
        "avg_volume": float(volume.tail(20).mean()),
    }


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_universe() -> dict:
    """Fetch live quotes with a short cache; no order endpoints are used."""
    result, errors = {}, []
    for code, fallback_name, market in UNIVERSE:
        try:
            quote = get_current_price(code, market)
            raw = quote.get("raw") or {}
            features = _daily_features(code, market)
            price = float(quote["price"])
            prev = raw.get("stck_sdpr") or raw.get("prdy_clpr") or features["prev_close"]
            cumulative_volume = raw.get("acml_vol")
            volume_ratio = (
                float(cumulative_volume) / max(1.0, features["avg_volume"])
                if cumulative_volume not in (None, "") else features["daily_volume_ratio"]
            )
            result[code] = {
                "code": code,
                "name": quote.get("name") or fallback_name,
                "market": market,
                "price": price,
                "prev": float(prev),
                "volume_ratio": max(0.0, min(10.0, volume_ratio)),
                "momentum": features["momentum"],
                "trend": features["trend"],
                "risk": features["risk"],
                "quote_time": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S"),
                "history_date": features["history_date"],
            }
        except Exception as exc:
            errors.append(f"{code} {fallback_name}: {exc}")
    if not result:
        raise RuntimeError("실시간 시세를 받지 못했습니다. " + " / ".join(errors[:3]))
    if errors:
        raise RuntimeError("일부 종목 조회 실패로 이번 주기 매매를 중지했습니다: " + " / ".join(errors[:3]))
    return result
