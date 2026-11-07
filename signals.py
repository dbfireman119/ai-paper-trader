"""Technical indicators and multi-signal scoring for real daily stock candles."""
from __future__ import annotations

import pandas as pd


def analyze_daily_bars(rows: list[dict]) -> dict:
    """Calculate trend, RSI, MACD, Bollinger and volume signals from NHPLUG daily bars."""
    if not rows:
        raise ValueError("일별 시세 데이터가 없습니다.")

    df = pd.DataFrame(rows).copy()
    aliases = {
        "date": "bsop_date", "close": "stck_clpr", "volume": "acml_vol",
        "open": "stck_oprc", "high": "stck_hgpr", "low": "stck_lwpr",
    }
    for target, source in aliases.items():
        if target not in df.columns and source in df.columns:
            df[target] = df[source]

    required = ["date", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"일별 시세 필드가 누락되었습니다: {', '.join(missing)}")

    for col in ["close", "volume", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = df["date"].astype(str)
    df = df.dropna(subset=["close", "volume"]).sort_values("date").drop_duplicates("date")
    if len(df) < 26:
        raise ValueError(f"기술적 분석에는 최소 26거래일 데이터가 필요합니다. 현재 {len(df)}일입니다.")

    close = df["close"]
    volume = df["volume"]
    df["sma5"] = close.rolling(5).mean()
    df["sma20"] = close.rolling(20).mean()
    df["sma60"] = close.rolling(60).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["rsi14"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "rsi14"] = 100
    df.loc[(loss == 0) & (gain == 0), "rsi14"] = 50

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    df["bb_upper"] = mid + 2 * std
    df["bb_lower"] = mid - 2 * std
    df["volume_ratio"] = volume / volume.shift(1).rolling(20).mean()

    latest = df.iloc[-1]
    previous = df.iloc[-2]
    score = 0
    reasons = []

    def add(condition: bool, points: int, positive: str, negative: str | None = None):
        nonlocal score
        if condition:
            score += points
            reasons.append(positive)
        elif negative:
            score -= points
            reasons.append(negative)

    add(latest["close"] > latest["sma20"], 2, "종가가 20일선 위", "종가가 20일선 아래")
    add(latest["sma5"] > latest["sma20"], 2, "5일선이 20일선 상회", "5일선이 20일선 하회")
    if pd.notna(latest["sma60"]):
        add(latest["sma20"] > latest["sma60"], 2, "20일선이 60일선 상회", "20일선이 60일선 하회")
    add(latest["macd"] > latest["macd_signal"], 2, "MACD 골든 구간", "MACD 데드 구간")
    add(latest["macd_hist"] > previous["macd_hist"], 1, "MACD 히스토그램 개선", "MACD 히스토그램 악화")

    rsi = float(latest["rsi14"])
    if 50 <= rsi <= 70:
        score += 1
        reasons.append("RSI 상승 모멘텀 양호")
    elif rsi > 75:
        score -= 1
        reasons.append("RSI 과열 주의")
    elif rsi < 45:
        score -= 1
        reasons.append("RSI 약세 구간")

    vol_ratio = float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else 0.0
    day_up = latest["close"] >= previous["close"]
    if vol_ratio >= 1.5 and day_up:
        score += 2
        reasons.append("거래량 증가와 가격 상승 동반")
    elif vol_ratio >= 1.5 and not day_up:
        score -= 2
        reasons.append("거래량 증가와 가격 하락 동반")

    if latest["close"] > latest["bb_upper"]:
        score += 1
        reasons.append("볼린저 상단 돌파")
    elif latest["close"] < latest["bb_lower"]:
        score -= 1
        reasons.append("볼린저 하단 이탈")

    signal = "상승" if score >= 4 else "하락" if score <= -4 else "중립"
    return {
        "signal": signal,
        "score": int(score),
        "reasons": reasons,
        "date": str(latest["date"]),
        "close": float(latest["close"]),
        "sma5": float(latest["sma5"]),
        "sma20": float(latest["sma20"]),
        "sma60": float(latest["sma60"]) if pd.notna(latest["sma60"]) else None,
        "rsi14": rsi,
        "macd": float(latest["macd"]),
        "macd_signal": float(latest["macd_signal"]),
        "volume_ratio": vol_ratio,
        "bars": len(df),
    }
