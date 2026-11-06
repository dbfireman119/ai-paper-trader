import random
from datetime import datetime, date
import streamlit as st
import pandas as pd

DEMO_NAMES = [
    "모의반도체", "모의바이오", "모의로봇", "모의전력", "모의화학",
    "모의게임", "모의자동차", "모의통신", "모의소재", "모의AI",
    "모의건설", "모의금융", "모의유통", "모의배터리", "모의항공",
    "모의조선", "모의콘텐츠", "모의의료", "모의보안", "모의환경",
    "모의부품", "모의반도체2", "모의헬스", "모의에너지", "모의물류",
    "모의소프트웨어", "모의기계", "모의식품", "모의서비스", "모의장비"
]

def initialize_state():
    defaults = {
        "initial_cash": 500000.0, "cash": 500000.0, "max_position": 150000,
        "max_positions": 3, "daily_loss_limit": 10000, "buy_threshold": 80,
        "take_profit_pct": 1.5, "stop_loss_pct": 1.0, "auto_trade": False,
        "positions": {}, "trades": [], "realized_pnl": 0.0,
        "daily_realized": 0.0, "session_day": str(date.today()),
        "market": {}, "tick": 0, "daily_halted": False,
        "last_buy_tick": {}
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if not st.session_state.market:
        rng = random.Random(119)
        for i, name in enumerate(DEMO_NAMES):
            code = f"DEMO{i+1:04d}"
            base = rng.randint(8000, 120000)
            st.session_state.market[code] = {
                "code": code, "name": name,
                "market": "KOSPI" if i % 2 == 0 else "KOSDAQ",
                "price": float(base), "prev": float(base),
                "volume_ratio": rng.uniform(0.8, 2.8),
                "momentum": rng.uniform(-1.5, 2.5),
                "trend": rng.uniform(-1.0, 2.0),
                "risk": rng.uniform(0.0, 1.0),
            }

def reset_session():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    initialize_state()

def advance_market():
    # Demo-only synthetic tick generator.
    st.session_state.tick += 1
    today = str(date.today())
    if st.session_state.session_day != today:
        st.session_state.session_day = today
        st.session_state.daily_realized = 0.0
        st.session_state.daily_halted = False
    for q in st.session_state.market.values():
        shock = random.gauss(0, 0.22)
        q["price"] = max(500, q["price"] * (1 + shock / 100))
        q["momentum"] = max(-4, min(5, q["momentum"] * 0.72 + shock * 0.8 + random.uniform(-0.25, 0.25)))
        q["trend"] = max(-4, min(5, q["trend"] * 0.96 + q["momentum"] * 0.06))
        q["volume_ratio"] = max(0.2, min(8, q["volume_ratio"] * 0.9 + random.uniform(0.0, 0.45)))
        q["risk"] = max(0, min(1, q["risk"] * 0.9 + random.uniform(0, 0.12)))

def score_universe():
    rows = []
    for q in st.session_state.market.values():
        trend_score = max(0, min(35, 17.5 + q["trend"] * 5.5))
        momentum_score = max(0, min(25, 12.5 + q["momentum"] * 4))
        volume_score = max(0, min(30, (q["volume_ratio"] / 3.0) * 30))
        risk_score = max(0, min(10, 10 - q["risk"] * 10))
        score = round(trend_score + momentum_score + volume_score + risk_score, 1)
        change = (q["price"] / q["prev"] - 1) * 100
        decision = "매수 후보" if score >= st.session_state.buy_threshold else ("관찰" if score >= 70 else "제외")
        rows.append({
            "code": q["code"], "종목명": q["name"], "시장": q["market"],
            "현재가": round(q["price"], 0), "등락률(%)": round(change, 2),
            "거래량비율": round(q["volume_ratio"], 2),
            "AI점수": score, "판정": decision
        })
    return pd.DataFrame(rows).sort_values(["AI점수", "거래량비율"], ascending=False).reset_index(drop=True)

def _record(side, q, qty, price, reason):
    st.session_state.trades.append({
        "시각": datetime.now().strftime("%H:%M:%S"),
        "구분": side, "종목명": q["name"], "수량": qty,
        "체결가": round(price, 0), "사유": reason
    })

def _daily_pnl_with_open_positions():
    unrealized = 0.0
    for code, pos in st.session_state.positions.items():
        current = st.session_state.market[code]["price"]
        unrealized += (current - pos["avg_price"]) * pos["qty"]
    return st.session_state.daily_realized + unrealized

def run_strategy(scored):
    if st.session_state.daily_halted:
        return
    if _daily_pnl_with_open_positions() <= -abs(st.session_state.daily_loss_limit):
        st.session_state.daily_halted = True
        return
    # Exit rules first.
    for code in list(st.session_state.positions.keys()):
        pos = st.session_state.positions[code]
        q = st.session_state.market[code]
        ret = (q["price"] / pos["avg_price"] - 1) * 100
        reason = None
        if ret >= st.session_state.take_profit_pct:
            reason = "익절 기준 도달"
        elif ret <= -st.session_state.stop_loss_pct:
            reason = "손절 기준 도달"
        elif q["trend"] < -1.8:
            reason = "추세 약화"
        if reason:
            qty = pos["qty"]
            proceeds = qty * q["price"]
            cost = qty * pos["avg_price"]
            pnl = proceeds - cost
            st.session_state.cash += proceeds
            st.session_state.realized_pnl += pnl
            st.session_state.daily_realized += pnl
            _record("매도", q, qty, q["price"], reason)
            del st.session_state.positions[code]
    if _daily_pnl_with_open_positions() <= -abs(st.session_state.daily_loss_limit):
        st.session_state.daily_halted = True
        return

    # Buy at most once per code per 12 synthetic ticks to reduce churn.
    for _, row in scored.iterrows():
        code = row["code"]
        score = float(row["AI점수"])
        if score < st.session_state.buy_threshold:
            continue
        if code in st.session_state.positions:
            continue
        if len(st.session_state.positions) >= st.session_state.max_positions:
            break
        if st.session_state.tick - st.session_state.last_buy_tick.get(code, -999) < 12:
            continue
        q = st.session_state.market[code]
        invest = min(float(st.session_state.max_position), st.session_state.cash - 50000)
        if invest < 10000:
            break
        qty = int(invest // q["price"])
        if qty <= 0:
            continue
        cost = qty * q["price"]
        st.session_state.cash -= cost
        st.session_state.positions[code] = {"qty": qty, "avg_price": q["price"]}
        st.session_state.last_buy_tick[code] = st.session_state.tick
        _record("매수", q, qty, q["price"], f"AI 점수 {score}점")

def portfolio_snapshot():
    market_value = sum(pos["qty"] * st.session_state.market[code]["price"]
                       for code, pos in st.session_state.positions.items())
    equity = st.session_state.cash + market_value
    total_pnl = equity - st.session_state.initial_cash
    return {
        "cash": st.session_state.cash, "market_value": market_value,
        "equity": equity, "total_pnl": total_pnl,
        "realized_pnl": st.session_state.realized_pnl,
        "daily_halted": st.session_state.daily_halted
    }
