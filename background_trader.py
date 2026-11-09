"""One-shot scheduled paper trader. Runs independently of the Streamlit login session.

This process reads NHPLUG market data only. It never calls brokerage order APIs.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import traceback

import pandas as pd
import streamlit as streamlit

import engine
from db_store import (
    get_auto_trade_enabled,
    load_market_cache,
    load_state,
    save_market_cache,
    save_portfolios,
    save_state,
)
from live_market import fetch_live_quotes
from market_scanner import _features, _stock_universe

KST = ZoneInfo("Asia/Seoul")


def market_is_open(now: datetime) -> bool:
    return (
        now.weekday() < 5
        and (now.hour > 9 or (now.hour == 9 and now.minute >= 5))
        and (now.hour < 15 or (now.hour == 15 and now.minute < 20))
    )


def get_market_for_today(today: str) -> dict:
    cached = load_market_cache(today)
    if cached:
        print(f"Using cached daily universe: {len(cached)} symbols")
        return cached

    print("Building today's market universe from NHPLUG daily bars")
    market = {}
    universe = _stock_universe()
    print(f"Universe size: {len(universe)}")
    for index, stock in enumerate(universe, start=1):
        try:
            quote = _features(stock)
            market[quote["code"]] = quote
        except Exception as exc:
            print(f"Skip {stock.get('code')}: {exc}")
        if index % 100 == 0:
            print(f"Daily scan progress: {index}/{len(universe)}")
    if not market:
        raise RuntimeError("시장 종목 스캔 결과가 비어 있습니다.")
    save_market_cache(today, market)
    print(f"Saved daily market cache: {len(market)} symbols")
    return market


def main() -> None:
    now = datetime.now(KST)
    print(f"Paper trader tick at {now.isoformat()}")

    if not market_is_open(now):
        print("Outside KRX paper-trading window; no action.")
        return

    if not get_auto_trade_enabled(default=True):
        print("Automatic paper trading is disabled in shared controls.")
        return

    restored = load_state()
    if not restored:
        portfolios = {name: engine._new_portfolio() for name in engine.STRATEGIES}
        settings = deepcopy(engine.STRATEGIES)
        save_state(portfolios, settings)
        restored = {"portfolios": portfolios, "strategy_settings": settings}

    market = get_market_for_today(now.date().isoformat())
    state = SimpleNamespace(
        portfolios=restored["portfolios"],
        strategy_settings=restored["strategy_settings"],
        market=dict(market),
        tick=int(now.timestamp() // 300),
    )
    # Reuse the existing virtual strategy logic in a headless process.
    engine.st = SimpleNamespace(session_state=state)

    daily_scored = engine.score_universe()
    top200 = daily_scored.head(200)
    top20_codes = top200[top200["거래가능"]]["code"].head(20).tolist()
    held_codes = []
    for portfolio in state.portfolios.values():
        held_codes.extend(list(portfolio["positions"].keys()))
    active_codes = list(dict.fromkeys(top20_codes + held_codes))
    if not active_codes:
        print("No eligible candidates or open positions.")
        return

    live_quotes = fetch_live_quotes(active_codes, market)
    state.market.update(live_quotes)
    scored = engine.score_universe().head(200)
    candidates = scored[scored["거래가능"]].head(20).copy()
    if candidates.empty:
        print("No eligible top-20 candidates; positions still evaluated.")
    for strategy_name in engine.STRATEGIES:
        engine.run_strategy(strategy_name, candidates)

    save_portfolios(state.portfolios)
    for name, portfolio in state.portfolios.items():
        snap = engine._snapshot(portfolio)
        print(
            f"{name}: cash={snap['cash']:.0f}, equity={snap['equity']:.0f}, "
            f"positions={len(portfolio['positions'])}, trades={len(portfolio['trades'])}"
        )
    print("Paper-trading tick completed. No brokerage orders were sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Paper-trading tick failed safely: {exc}")
        traceback.print_exc()
        raise
