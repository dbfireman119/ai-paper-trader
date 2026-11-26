"""Transparent, rule-based multi-analyst paper strategy inspired by TradingAgents.

This first-stage adapter intentionally uses only the market fields already available
in this application. It does NOT call an LLM and does NOT claim to reproduce the
full Tauric Research TradingAgents framework. No brokerage order API is imported.
"""
from __future__ import annotations

import pandas as pd


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def evaluate_candidates(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (eligible entries, full analyst report) for the top-scored universe.

    Analyst roles:
      * trend analyst: moving-average trend proxy already calculated by scanner
      * momentum analyst: five-session return proxy
      * liquidity analyst: current/average volume ratio
      * risk analyst: realized-volatility proxy and intraday price extension
      * bull/bear debate + portfolio manager: weighted consensus and hard gates

    Fundamental, news and sentiment inputs are deliberately marked unavailable;
    they are not fabricated from technical data.
    """
    if scored is None or scored.empty:
        empty = scored.copy() if isinstance(scored, pd.DataFrame) else pd.DataFrame()
        return empty, empty

    report = scored.copy()
    trend = report["추세값"].astype(float)
    momentum = report["모멘텀값"].astype(float)
    volume = report["거래량비율"].astype(float)
    risk = report["위험도"].astype(float)
    change = report["등락률(%)"].astype(float)

    report["추세분석"] = ((trend + 2.0) / 4.0 * 100).clip(0, 100).round(1)
    report["모멘텀분석"] = ((momentum + 2.0) / 4.0 * 100).clip(0, 100).round(1)
    report["유동성분석"] = (volume / 3.0 * 100).clip(0, 100).round(1)
    report["상승론점수"] = (
        report["추세분석"] * 0.40
        + report["모멘텀분석"] * 0.35
        + report["유동성분석"] * 0.25
    ).round(1)

    weak_trend = ((trend <= 0).astype(float) * 65 + (momentum < 0).astype(float) * 35)
    overheat = (change.clip(lower=0) / 5.0 * 100).clip(0, 100)
    report["하락론점수"] = (
        risk.clip(0, 1) * 100 * 0.50
        + overheat * 0.25
        + weak_trend * 0.25
    ).round(1)
    report["펀드합의점수"] = (
        report["상승론점수"] * 0.60
        + (100 - report["하락론점수"]) * 0.40
    ).round(1)

    gates = (
        (report["상승론점수"] >= 60)
        & (report["상승론점수"] - report["하락론점수"] >= 10)
        & (trend > 0)
        & (momentum > 0)
        & (volume >= 1.1)
        & (risk <= 0.70)
        & (change <= 3.5)
        & report["거래가능"].astype(bool)
    )
    report["펀드매니저판정"] = gates.map({True: "합의 통과", False: "관찰/보류"})
    report["리스크등급"] = pd.cut(
        risk, bins=[-0.001, 0.35, 0.60, 0.75, 1.001],
        labels=["낮음", "보통", "높음", "매우 높음"], include_lowest=True
    ).astype(str)
    report["판단근거"] = report.apply(
        lambda row: (
            "상승·모멘텀·거래량 합의, 하락론 우위 아님"
            if row["펀드매니저판정"] == "합의 통과"
            else "상승/하락 논거 또는 리스크 게이트 미충족"
        ), axis=1
    )
    eligible = report[gates].sort_values(
        ["펀드합의점수", "상승론점수"], ascending=False
    ).head(20).copy()
    return eligible, report
