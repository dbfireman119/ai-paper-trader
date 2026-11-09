import random
import copy
from datetime import datetime, date
import streamlit as st
import pandas as pd
from db_store import load_state, save_state, get_auto_trade_enabled

STRATEGIES = {
    "안정형": {
        "max_position": 150000, "max_positions": 3, "cash_reserve": 50000,
        "daily_loss_limit": 10000, "buy_threshold": 70,
        "stop_loss_pct": 1.0, "trailing_activation_pct": 1.0,
        "trailing_gap_pct": 1.0, "risk_budget_pct": 0.5,
        "min_trend": -0.2, "min_momentum": -0.2, "min_volume_ratio": 0.9,
        "max_risk": 0.8, "max_change_pct": 4.0,
    },
    "공격형": {
        "max_position": 180000, "max_positions": 3, "cash_reserve": 20000,
        "daily_loss_limit": 15000, "buy_threshold": 60,
        "stop_loss_pct": 1.5, "trailing_activation_pct": 2.0,
        "trailing_gap_pct": 1.0, "risk_budget_pct": 0.75,
        "min_trend": -0.5, "min_momentum": -0.5, "min_volume_ratio": 0.8,
        "max_risk": 0.9, "max_change_pct": 5.0,
    },
    "스캘핑형": {
        "max_position": 100000, "max_positions": 2, "cash_reserve": 100000,
        "daily_loss_limit": 5000, "buy_threshold": 78,
        "stop_loss_pct": 0.7, "trailing_activation_pct": 0.8,
        "trailing_gap_pct": 0.4, "risk_budget_pct": 0.3,
        "min_trend": 0.2, "min_momentum": 0.3, "min_volume_ratio": 1.5,
        "max_risk": 0.55, "max_change_pct": 3.0,
    },
}

def _new_portfolio():
    return {
        "initial_cash": 500000.0, "cash": 500000.0, "positions": {},
        "trades": [], "realized_pnl": 0.0, "daily_realized": 0.0,
        "session_day": str(date.today()), "daily_halted": False,
        "last_buy_tick": {},
    }

def initialize_state():
    # Do not invent prices or symbols. Wait for the read-only live quote feed.
    if "market" not in st.session_state:
        st.session_state.market = {}
    if "portfolios" not in st.session_state or "strategy_settings" not in st.session_state:
        restored = None
        try:
            restored = load_state()
        except Exception as exc:
            st.session_state["persistence_error"] = str(exc)
        if restored:
            st.session_state.portfolios = {
                **{name: _new_portfolio() for name in STRATEGIES},
                **restored.get("portfolios", {}),
            }
            st.session_state.strategy_settings = copy.deepcopy(STRATEGIES)
            st.session_state.strategy_settings.update(restored.get("strategy_settings", {}))
            st.session_state["persistence_restored"] = True
        else:
            st.session_state.portfolios = {name: _new_portfolio() for name in STRATEGIES}
            st.session_state.strategy_settings = copy.deepcopy(STRATEGIES)
            st.session_state["persistence_restored"] = False
    if "tick" not in st.session_state:
        st.session_state.tick = 0
    if "auto_trade" not in st.session_state:
        try:
            st.session_state.auto_trade = get_auto_trade_enabled(default=True)
        except Exception:
            st.session_state.auto_trade = False

def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    initialize_state()
    save_state(st.session_state.portfolios, st.session_state.strategy_settings)

def advance_market():
    st.session_state.tick += 1
    for q in st.session_state.market.values():
        shock = random.gauss(0, 0.22)
        q["price"] = max(500, q["price"] * (1 + shock / 100))
        q["momentum"] = max(-4, min(5, q["momentum"] * 0.72 + shock * 0.8 + random.uniform(-0.25, 0.25)))
        q["trend"] = max(-4, min(5, q["trend"] * 0.96 + q["momentum"] * 0.06))
        q["volume_ratio"] = max(0.2, min(8, q["volume_ratio"] * 0.9 + random.uniform(0.0, 0.45)))
        q["risk"] = max(0, min(1, q["risk"] * 0.9 + random.uniform(0, 0.12)))
    today = str(date.today())
    for pf in st.session_state.portfolios.values():
        if pf["session_day"] != today:
            pf["session_day"] = today
            pf["daily_realized"] = 0.0
            pf["daily_halted"] = False

def score_universe():
    rows = []
    for q in st.session_state.market.values():
        trend_score = max(0, min(35, 17.5 + q["trend"] * 5.5))
        momentum_score = max(0, min(25, 12.5 + q["momentum"] * 4))
        volume_score = max(0, min(30, (q["volume_ratio"] / 3.0) * 30))
        risk_score = max(0, min(10, 10 - q["risk"] * 10))
        score = round(trend_score + momentum_score + volume_score + risk_score, 1)
        change = (q["price"] / q["prev"] - 1) * 100
        gates = []
        if q["trend"] <= 0: gates.append("상승 추세 미확인")
        if q["momentum"] <= 0: gates.append("모멘텀 미확인")
        if q["volume_ratio"] < 1.1: gates.append("거래량 확인 부족")
        if q["risk"] > 0.70: gates.append("위험도 높음")
        if change > 3.0: gates.append("급등 추격매수 제한")
        if not q.get("tradable", True): gates.append("거래정지·관리·투자주의 등 제외")
        rows.append({
            "code": q["code"], "종목명": q["name"], "시장": q["market"],
            "현재가": round(q["price"], 0), "등락률(%)": round(change, 2),
            "거래량비율": round(q["volume_ratio"], 2), "AI점수": score,
            "품질조건": not gates, "거래가능": bool(q.get("tradable", True)),
            "매매검증": "조건 충족" if not gates else ", ".join(gates),
            "추세값": q["trend"], "모멘텀값": q["momentum"], "위험도": q["risk"],
        })
    if not rows:
        return pd.DataFrame(columns=[
            "code", "종목명", "시장", "현재가", "등락률(%)", "거래량비율",
            "AI점수", "품질조건", "거래가능", "매매검증", "추세값", "모멘텀값", "위험도"
        ])
    return pd.DataFrame(rows).sort_values(["AI점수", "거래량비율"], ascending=False).reset_index(drop=True)

def _position_mark_price(code, pos):
    """Return the latest quote, or the last known/entry price if a quote is missing."""
    quote = st.session_state.market.get(code)
    if quote and quote.get("price") is not None:
        price = float(quote["price"])
        pos["last_price"] = price
        return price
    return float(pos.get("last_price", pos.get("avg_price", 0.0)))

def _daily_pnl(pf):
    unrealized = sum(
        (_position_mark_price(code, pos) - pos["avg_price"]) * pos["qty"]
        for code, pos in pf["positions"].items()
    )
    return pf["daily_realized"] + unrealized

def _snapshot(pf):
    market_value = sum(
        pos["qty"] * _position_mark_price(code, pos)
        for code, pos in pf["positions"].items()
    )
    equity = pf["cash"] + market_value
    return {
        "cash": pf["cash"], "market_value": market_value, "equity": equity,
        "total_pnl": equity - pf["initial_cash"],
        "realized_pnl": pf["realized_pnl"], "daily_halted": pf["daily_halted"],
    }

def _record(pf, side, q, qty, price, reason):
    pf["trades"].append({
        "시각": datetime.now().strftime("%H:%M:%S"), "구분": side,
        "종목명": q["name"], "수량": qty, "체결가": round(price, 0), "사유": reason,
    })

def run_strategy(name, scored):
    cfg = st.session_state.strategy_settings[name]
    pf = st.session_state.portfolios[name]
    if pf["daily_halted"]:
        return
    if _daily_pnl(pf) <= -cfg["daily_loss_limit"]:
        pf["daily_halted"] = True
        return

    for code in list(pf["positions"].keys()):
        pos = pf["positions"][code]
        # Missing quote must not crash the dashboard or trigger a fabricated exit.
        q = st.session_state.market.get(code)
        if not q or q.get("price") is None:
            continue
        pos["last_price"] = float(q["price"])
        ret = (q["price"] / pos["avg_price"] - 1) * 100
        pos["peak_price"] = max(float(pos.get("peak_price", pos["avg_price"])), float(q["price"]))
        peak_return = (pos["peak_price"] / pos["avg_price"] - 1) * 100
        drawdown = (q["price"] / pos["peak_price"] - 1) * 100
        reason = None
        if ret <= -cfg["stop_loss_pct"]:
            reason = "사전 설정 손절선 도달"
        elif peak_return >= cfg["trailing_activation_pct"] and drawdown <= -cfg["trailing_gap_pct"]:
            reason = "트레일링 스톱: 고점 대비 하락"
        elif q["trend"] < -1.8 or (q["trend"] < 0 and q["momentum"] < 0):
            reason = "추세 이탈"
        if reason:
            qty = pos["qty"]
            proceeds = qty * q["price"]
            pnl = proceeds - qty * pos["avg_price"]
            pf["cash"] += proceeds
            pf["realized_pnl"] += pnl
            pf["daily_realized"] += pnl
            _record(pf, "매도", q, qty, q["price"], reason)
            del pf["positions"][code]

    if _daily_pnl(pf) <= -cfg["daily_loss_limit"]:
        pf["daily_halted"] = True
        return

    for _, row in scored.iterrows():
        code = row["code"]
        if float(row["AI점수"]) < cfg["buy_threshold"]:
            continue
        if (float(row["추세값"]) < cfg["min_trend"] or
            float(row["모멘텀값"]) < cfg["min_momentum"] or
            float(row["거래량비율"]) < cfg["min_volume_ratio"] or
            float(row["위험도"]) > cfg["max_risk"] or
            float(row["등락률(%)"]) > cfg["max_change_pct"]):
            continue
        if code in pf["positions"] or len(pf["positions"]) >= cfg["max_positions"]:
            continue
        if st.session_state.tick - pf["last_buy_tick"].get(code, -999) < 12:
            continue
        q = st.session_state.market[code]
        equity = _snapshot(pf)["equity"]
        risk_budget = equity * cfg["risk_budget_pct"] / 100
        stop_fraction = max(cfg["stop_loss_pct"] / 100, 0.002)
        risk_shares = int(risk_budget / (q["price"] * stop_fraction))
        invest = min(
            cfg["max_position"], pf["cash"] - cfg["cash_reserve"],
            risk_shares * q["price"],
        )
        if invest < 10000:
            continue
        qty = int(invest // q["price"])
        if qty <= 0:
            continue
        cost = qty * q["price"]
        pf["cash"] -= cost
        pf["positions"][code] = {"qty": qty, "avg_price": q["price"], "peak_price": q["price"]}
        pf["last_buy_tick"][code] = st.session_state.tick
        _record(pf, "매수", q, qty, q["price"],
                f"AI 점수 {row['AI점수']}점 · 손실예산 {cfg['risk_budget_pct']}% · 추가매수 금지")

def portfolio_snapshot(name):
    return _snapshot(st.session_state.portfolios[name])
