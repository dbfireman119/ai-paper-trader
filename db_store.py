"""Persistent storage for paper-trading portfolios and strategy settings.

Only virtual portfolio state is stored. This module has no brokerage order calls.
"""
from __future__ import annotations

import json
import os
from typing import Any


def _connect():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    import psycopg
    return psycopg.connect(url, connect_timeout=8)


def initialize_database() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_trader_state (
                    state_key TEXT PRIMARY KEY,
                    portfolios JSONB NOT NULL,
                    strategy_settings JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()


def load_state() -> dict[str, Any] | None:
    initialize_database()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT portfolios, strategy_settings
                FROM paper_trader_state WHERE state_key = 'main'
            """)
            row = cur.fetchone()
    if not row:
        return None
    portfolios, settings = row
    if isinstance(portfolios, str):
        portfolios = json.loads(portfolios)
    if isinstance(settings, str):
        settings = json.loads(settings)
    return {"portfolios": portfolios, "strategy_settings": settings}


def save_state(portfolios: dict, strategy_settings: dict) -> None:
    initialize_database()
    payload_portfolios = json.dumps(portfolios, ensure_ascii=False)
    payload_settings = json.dumps(strategy_settings, ensure_ascii=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paper_trader_state
                    (state_key, portfolios, strategy_settings, updated_at)
                VALUES ('main', %s::jsonb, %s::jsonb, NOW())
                ON CONFLICT (state_key) DO UPDATE SET
                    portfolios = EXCLUDED.portfolios,
                    strategy_settings = EXCLUDED.strategy_settings,
                    updated_at = NOW()
            """, (payload_portfolios, payload_settings))
        conn.commit()


def get_auto_trade_enabled(default: bool = True) -> bool:
    initialize_database()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_trader_control (
                    control_key TEXT PRIMARY KEY,
                    enabled BOOLEAN NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("SELECT enabled FROM paper_trader_control WHERE control_key='auto_trade'")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO paper_trader_control (control_key, enabled) VALUES ('auto_trade', %s) ON CONFLICT DO NOTHING",
                    (bool(default),)
                )
                conn.commit()
                return bool(default)
            return bool(row[0])


def save_auto_trade_enabled(enabled: bool) -> None:
    initialize_database()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paper_trader_control (control_key, enabled, updated_at)
                VALUES ('auto_trade', %s, NOW())
                ON CONFLICT (control_key) DO UPDATE
                SET enabled=EXCLUDED.enabled, updated_at=NOW()
            """, (bool(enabled),))
        conn.commit()


def save_strategy_settings(strategy_settings: dict) -> None:
    initialize_database()
    payload = json.dumps(strategy_settings, ensure_ascii=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE paper_trader_state
                SET strategy_settings=%s::jsonb, updated_at=NOW()
                WHERE state_key='main'
            """, (payload,))
        conn.commit()


def save_portfolios(portfolios: dict) -> None:
    initialize_database()
    payload = json.dumps(portfolios, ensure_ascii=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE paper_trader_state
                SET portfolios=%s::jsonb, updated_at=NOW()
                WHERE state_key='main'
            """, (payload,))
        conn.commit()


def load_market_cache(cache_date: str) -> dict[str, Any] | None:
    initialize_database()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_trader_market_cache (
                    cache_date DATE PRIMARY KEY,
                    market JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "SELECT market FROM paper_trader_market_cache WHERE cache_date=%s::date",
                (cache_date,)
            )
            row = cur.fetchone()
    if not row:
        return None
    market = row[0]
    return json.loads(market) if isinstance(market, str) else market


def save_market_cache(cache_date: str, market: dict) -> None:
    initialize_database()
    payload = json.dumps(market, ensure_ascii=False, allow_nan=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paper_trader_market_cache (cache_date, market, updated_at)
                VALUES (%s::date, %s::jsonb, NOW())
                ON CONFLICT (cache_date) DO UPDATE
                SET market=EXCLUDED.market, updated_at=NOW()
            """, (cache_date, payload))
        conn.commit()
