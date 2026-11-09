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
