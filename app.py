import os
import hmac
from datetime import datetime
import pandas as pd
import streamlit as st
from engine import (
    STRATEGIES, initialize_state, advance_market, score_universe,
    run_strategy, portfolio_snapshot, reset_session
)

st.set_page_config(page_title="AI 모의매매 비교", page_icon="📈", layout="wide")

site_username = os.getenv("SITE_USERNAME", "")
site_password = os.getenv("SITE_PASSWORD", "")
if not site_username or not site_password:
    st.error("사이트 접근 설정이 완료되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

if not st.session_state.get("site_authenticated", False):
    st.title("🔒 비공개 모의매매 사이트")
    st.caption("접근 권한이 있는 사용자만 이용할 수 있습니다.")
    with st.form("site_login"):
        entered_username = st.text_input("아이디")
        entered_password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)
    if submitted:
        if hmac.compare_digest(entered_username, site_username) and hmac.compare_digest(entered_password, site_password):
            st.session_state.site_authenticated = True
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

initialize_state()
st.title("📈 AI 모의매매 전략 비교")
st.caption("안정형·공격형 독립 모의계좌 동시 운용 · 가상 시세 DEMO · 실제 주문 기능 없음")

with st.sidebar:
    st.subheader("공통 운용")
    st.metric("각 전략 초기 자금", "500,000원")
    st.toggle("두 전략 자동 모의매매", key="auto_trade")
    st.caption("켜면 동일한 가상 시세를 공유하면서 안정형과 공격형이 각각 독립된 현금·보유종목으로 매매합니다.")
    st.divider()
    st.subheader("나무증권 API")
    st.caption("현재는 연결 테스트만 제공하며 실제 시세·주문에는 연결하지 않습니다.")
    if st.button("나무증권 API 연결 테스트 (삼성전자)", use_container_width=True):
        try:
            from nh_api import get_current_price
            st.session_state["nh_api_test_result"] = get_current_price("005930")
            st.session_state["nh_api_test_error"] = None
        except Exception as exc:
            st.session_state["nh_api_test_error"] = str(exc)
            st.session_state["nh_api_test_result"] = None
    if st.session_state.get("nh_api_test_result"):
        result = st.session_state["nh_api_test_result"]
        st.success(f"API 응답 확인: {result['name']} {result['price']:,}원")
    elif st.session_state.get("nh_api_test_error"):
        st.error(f"API 연결 실패: {st.session_state['nh_api_test_error']}")
    else:
        st.info("키 미등록 상태에서는 가상 시세로 계속 실행됩니다.")
    st.divider()
    if st.button("두 모의계좌 모두 초기화", use_container_width=True):
        reset_session()
        st.rerun()

def show_strategy(name):
    cfg = st.session_state.strategy_settings[name]
    pf = st.session_state.portfolios[name]
    snap = portfolio_snapshot(name)
    a, b, c, d = st.columns(4)
    a.metric("총 평가자산", f"{snap['equity']:,.0f}원", f"{snap['total_pnl']:+,.0f}원")
    b.metric("주문 가능 현금", f"{snap['cash']:,.0f}원")
    c.metric("보유 종목", f"{len(pf['positions'])} / {cfg['max_positions']}")
    d.metric("실현손익", f"{snap['realized_pnl']:+,.0f}원")
    if snap["daily_halted"]:
        st.error(f"일일 손실 한도({cfg['daily_loss_limit']:,}원) 도달: 신규 매수 중지")
    elif st.session_state.auto_trade:
        st.success("자동 모의매매 실행 중")
    else:
        st.info("자동 모의매매 일시정지 · 종목 분석만 갱신")
    st.markdown("**전략 설정**")
    st.caption(
        f"종목당 한도 {cfg['max_position']:,}원 · 최대 {cfg['max_positions']}종목 · "
        f"현금 유보 {cfg['cash_reserve']:,}원 · 매수점수 {cfg['buy_threshold']}점 · "
        f"손절 -{cfg['stop_loss_pct']}% · 트레일링 시작 +{cfg['trailing_activation_pct']}% / "
        f"고점 대비 -{cfg['trailing_gap_pct']}% · 거래 위험예산 {cfg['risk_budget_pct']}% · "
        f"일일 손실한도 {cfg['daily_loss_limit']:,}원"
    )
    with st.expander(f"{name} 세부 설정 조절", expanded=False):
        st.caption("이 설정은 현재 로그인 세션의 해당 전략에만 적용됩니다. 두 탭은 서로 독립적으로 조절할 수 있습니다.")
        x1, x2, x3 = st.columns(3)
        cfg["buy_threshold"] = x1.slider("매수 최소 점수", 40, 95, int(cfg["buy_threshold"]), key=f"{name}_threshold")
        cfg["max_positions"] = x2.slider("최대 보유 종목 수", 1, 8, int(cfg["max_positions"]), key=f"{name}_max_positions")
        cfg["max_position"] = x3.number_input("종목당 최대 투자금(원)", 10000, 500000, int(cfg["max_position"]), 10000, key=f"{name}_max_position")
        x1, x2, x3 = st.columns(3)
        cfg["min_trend"] = x1.slider("최소 추세값", -2.0, 2.0, float(cfg["min_trend"]), 0.1, key=f"{name}_min_trend")
        cfg["min_momentum"] = x2.slider("최소 모멘텀값", -2.0, 2.0, float(cfg["min_momentum"]), 0.1, key=f"{name}_min_momentum")
        cfg["min_volume_ratio"] = x3.slider("최소 거래량 비율", 0.5, 3.0, float(cfg["min_volume_ratio"]), 0.1, key=f"{name}_min_volume")
        x1, x2, x3 = st.columns(3)
        cfg["max_risk"] = x1.slider("허용 최대 위험도", 0.1, 1.0, float(cfg["max_risk"]), 0.05, key=f"{name}_max_risk")
        cfg["max_change_pct"] = x2.slider("급등 제한 등락률(%)", 1.0, 10.0, float(cfg["max_change_pct"]), 0.5, key=f"{name}_max_change")
        cfg["cash_reserve"] = x3.number_input("현금 유보액(원)", 0, 300000, int(cfg["cash_reserve"]), 10000, key=f"{name}_reserve")
        x1, x2, x3 = st.columns(3)
        cfg["stop_loss_pct"] = x1.slider("손절 기준(%)", 0.5, 5.0, float(cfg["stop_loss_pct"]), 0.1, key=f"{name}_stop")
        cfg["trailing_activation_pct"] = x2.slider("트레일링 시작 수익률(%)", 0.5, 8.0, float(cfg["trailing_activation_pct"]), 0.1, key=f"{name}_trail_start")
        cfg["trailing_gap_pct"] = x3.slider("고점 대비 매도 하락률(%)", 0.5, 5.0, float(cfg["trailing_gap_pct"]), 0.1, key=f"{name}_trail_gap")
        x1, x2 = st.columns(2)
        cfg["risk_budget_pct"] = x1.slider("1회 거래 위험예산(%)", 0.1, 2.0, float(cfg["risk_budget_pct"]), 0.05, key=f"{name}_risk_budget")
        cfg["daily_loss_limit"] = x2.number_input("일일 손실 제한(원)", 1000, 100000, int(cfg["daily_loss_limit"]), 1000, key=f"{name}_daily_loss")
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("보유 종목")
        if pf["positions"]:
            rows = []
            for code, pos in pf["positions"].items():
                q = st.session_state.market[code]
                rows.append({
                    "종목명": q["name"], "수량": pos["qty"],
                    "매입가": round(pos["avg_price"]), "현재가": round(q["price"]),
                    "수익률(%)": round((q["price"] / pos["avg_price"] - 1) * 100, 2),
                    "평가손익": round((q["price"] - pos["avg_price"]) * pos["qty"]),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.write("현재 보유 종목이 없습니다.")
    with right:
        st.subheader("최근 체결 내역")
        if pf["trades"]:
            st.dataframe(pd.DataFrame(pf["trades"][-15:][::-1]), use_container_width=True, hide_index=True)
        else:
            st.write("아직 체결 내역이 없습니다.")
    st.subheader("이 전략의 매수 후보")
    candidates = scored.copy()
    def judge(r):
        filters_ok = (
            r["추세값"] >= cfg["min_trend"] and
            r["모멘텀값"] >= cfg["min_momentum"] and
            r["거래량비율"] >= cfg["min_volume_ratio"] and
            r["위험도"] <= cfg["max_risk"] and
            r["등락률(%)"] <= cfg["max_change_pct"]
        )
        if r["AI점수"] >= cfg["buy_threshold"] and filters_ok:
            return "매수 후보"
        if r["AI점수"] >= max(40, cfg["buy_threshold"] - 10):
            return "관찰"
        return "제외"
    candidates["판정"] = candidates.apply(judge, axis=1)
    def validation(r):
        reasons = []
        if r["추세값"] < cfg["min_trend"]: reasons.append("추세 기준 미달")
        if r["모멘텀값"] < cfg["min_momentum"]: reasons.append("모멘텀 기준 미달")
        if r["거래량비율"] < cfg["min_volume_ratio"]: reasons.append("거래량 기준 미달")
        if r["위험도"] > cfg["max_risk"]: reasons.append("위험도 초과")
        if r["등락률(%)"] > cfg["max_change_pct"]: reasons.append("급등 제한")
        if r["AI점수"] < cfg["buy_threshold"]: reasons.append("매수 점수 미달")
        return "전략 조건 충족" if not reasons else ", ".join(reasons)
    candidates["매매검증"] = candidates.apply(validation, axis=1)
    st.dataframe(
        candidates[["종목명", "시장", "현재가", "등락률(%)", "거래량비율", "AI점수", "판정", "매매검증"]].head(10),
        use_container_width=True, hide_index=True
    )

@st.fragment(run_every="5s")
def live_panel():
    advance_market()
    global scored
    scored = score_universe()
    if st.session_state.auto_trade:
        for strategy_name in STRATEGIES:
            run_strategy(strategy_name, scored)
    st.caption(f"가상 시세 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 5초 주기")
    t1, t2 = st.tabs(["🛡️ 안정형 모의매매", "🚀 공격형 모의매매"])
    with t1:
        show_strategy("안정형")
    with t2:
        show_strategy("공격형")

scored = score_universe()
live_panel()

with st.expander("두 전략의 비교 기준 및 주의사항"):
    st.markdown("""
    - **안정형:** 진입 기준을 높이고 현금 유보액과 손실 제한을 크게 두는 방식입니다.
    - **공격형:** 매수 기준을 낮추고 종목당 투자 한도·위험예산을 높여 기회를 더 적극적으로 탐색합니다.
    - 두 전략은 동일한 가상 시세를 보지만 현금, 보유종목, 체결내역, 손익, 손실중지 상태가 완전히 분리된 모의계좌입니다.
    - 매도는 고정 익절 대신 트레일링 스톱과 추세 이탈을 사용합니다.
    - 일일 손실 한도에 도달하면 해당 전략만 신규 매수를 중지합니다.
    - 가상 시세와 가상 종목으로 작동하므로 실제 코스피·코스닥의 수익성을 의미하지 않습니다.
    - 실제 시세 연동, 거래비용 반영, 최소 20~60거래일 이상의 검증 전에는 실전 투자 판단에 사용하지 마세요.
    """)

with st.expander("전체 전략 성과 한눈에 비교"):
    rows = []
    for name in STRATEGIES:
        snap = portfolio_snapshot(name)
        pf = st.session_state.portfolios[name]
        rows.append({
            "전략": name, "평가자산": round(snap["equity"]),
            "누적손익": round(snap["total_pnl"]),
            "수익률(%)": round(snap["total_pnl"] / 500000 * 100, 2),
            "실현손익": round(snap["realized_pnl"]),
            "보유종목": len(pf["positions"]), "총 체결": len(pf["trades"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


st.divider()
st.header("📊 실제 종목 상승·하락 신호 분석")
st.caption("NH투자증권 일별 시세를 조회해 이동평균선·RSI·MACD·볼린저밴드·거래량을 종합 분석합니다. 이 기능은 조회 전용이며 실제 주문을 실행하지 않습니다.")
with st.form("real_stock_signal_form"):
    signal_code = st.text_input("종목코드 6자리", value="005930", max_chars=6)
    signal_market = st.selectbox("조회 시장", ["KRX", "NXT", "UNT"], index=0)
    signal_submit = st.form_submit_button("실제 시세 조회 및 신호 분석", use_container_width=True)

if signal_submit:
    if not signal_code.isdigit() or len(signal_code) != 6:
        st.error("종목코드 6자리를 숫자로 입력해주세요.")
    else:
        try:
            from nh_api import get_daily_history
            from signals import analyze_daily_bars
            with st.spinner("NH투자증권에서 일별 시세를 조회하고 있습니다..."):
                daily_rows = get_daily_history(signal_code, signal_market, 80)
                analysis = analyze_daily_bars(daily_rows)
            st.session_state["last_real_signal"] = analysis
            st.session_state["last_real_signal_code"] = signal_code
        except Exception as exc:
            st.error(f"실제 시세 분석 실패: {exc}")

if st.session_state.get("last_real_signal"):
    result = st.session_state["last_real_signal"]
    signal_code_saved = st.session_state.get("last_real_signal_code", "")
    color = "success" if result["signal"] == "상승" else "danger" if result["signal"] == "하락" else "warning"
    st.subheader(f"{signal_code_saved} 분석 결과")
    st.metric("종합 신호", result["signal"], f"점수 {result['score']:+d}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("최근 종가", f"{result['close']:,.0f}원")
    c2.metric("RSI(14)", f"{result['rsi14']:.1f}")
    c3.metric("MACD", f"{result['macd']:.2f}")
    c4.metric("거래량 비율", f"{result['volume_ratio']:.2f}배")
    st.caption(f"기준일: {result['date']} · 분석 데이터: {result['bars']}거래일")
    st.markdown("**신호 근거**")
    for reason in result["reasons"]:
        st.write(f"• {reason}")
    st.caption("상승·하락 신호는 확률이나 수익 보장이 아닙니다. 실제 매매 전 별도 검증이 필요합니다.")
