import streamlit as st
import pandas as pd
from datetime import datetime
from engine import (
    initialize_state, advance_market, score_universe, run_strategy,
    portfolio_snapshot, reset_session
)

st.set_page_config(page_title="AI 모의매매", page_icon="📈", layout="wide")

# Application-level access gate. Configure SITE_USERNAME and SITE_PASSWORD
# as Render environment variables. Fail closed when either is missing.
import os
import hmac

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
        user_ok = hmac.compare_digest(entered_username, site_username)
        pass_ok = hmac.compare_digest(entered_password, site_password)
        if user_ok and pass_ok:
            st.session_state.site_authenticated = True
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

initialize_state()

st.title("📈 AI 장중 모의매매")
st.caption("코스피·코스닥 분석 구조 검증용 DEMO · 가상 시세만 사용 · 실제 주문 기능 없음")

with st.sidebar:
    st.subheader("운용 설정")
    st.metric("초기 모의투자금", f"{st.session_state.initial_cash:,.0f}원")
    st.number_input("종목당 최대 투자금(원)", min_value=10000, max_value=500000,
                    step=10000, key="max_position")
    st.number_input("최대 보유 종목 수", min_value=1, max_value=5, step=1,
                    key="max_positions")
    st.number_input("일일 손실 한도(원)", min_value=1000, max_value=100000,
                    step=1000, key="daily_loss_limit")
    st.number_input("매수 점수 기준", min_value=50, max_value=100,
                    step=1, key="buy_threshold")
    st.number_input("익절 기준(%)", min_value=0.2, max_value=10.0,
                    step=0.1, key="take_profit_pct")
    st.number_input("손절 기준(%)", min_value=0.2, max_value=10.0,
                    step=0.1, key="stop_loss_pct")
    st.divider()
    st.toggle("자동 모의매매 실행", key="auto_trade")
    st.caption("자동 실행을 켜면 새 가상 시세가 생성될 때 매수·매도 규칙을 시험합니다.")
    if st.button("모의계좌 초기화", use_container_width=True):
        reset_session()
        st.rerun()

# A fragment refreshes the demo market periodically. No external market feed is connected.
@st.fragment(run_every="5s")
def live_panel():
    advance_market()
    scored = score_universe()
    if st.session_state.auto_trade:
        run_strategy(scored)

    snap = portfolio_snapshot()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 평가자산", f"{snap['equity']:,.0f}원",
              f"{snap['total_pnl']:+,.0f}원")
    c2.metric("주문 가능 현금", f"{snap['cash']:,.0f}원")
    c3.metric("보유 종목", f"{len(st.session_state.positions)} / {st.session_state.max_positions}")
    c4.metric("당일 실현손익", f"{snap['realized_pnl']:+,.0f}원")

    if snap["daily_halted"]:
        st.error("일일 손실 한도 도달: 신규 매수가 중지되었습니다.")
    elif st.session_state.auto_trade:
        st.success("자동 모의매매 실행 중")
    else:
        st.info("자동 모의매매 일시정지 상태입니다. 분석은 계속 갱신됩니다.")

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("매수 후보 TOP 10")
        cols = ["종목명", "시장", "현재가", "등락률(%)", "거래량비율", "AI점수", "판정"]
        st.dataframe(scored[cols].head(10), use_container_width=True, hide_index=True)
    with right:
        st.subheader("보유 종목")
        if st.session_state.positions:
            holdings = []
            for code, pos in st.session_state.positions.items():
                quote = st.session_state.market[code]
                pnl_pct = (quote["price"] / pos["avg_price"] - 1) * 100
                holdings.append({
                    "종목명": quote["name"], "수량": pos["qty"],
                    "매입가": round(pos["avg_price"], 0),
                    "현재가": round(quote["price"], 0),
                    "수익률(%)": round(pnl_pct, 2),
                    "평가손익": round((quote["price"] - pos["avg_price"]) * pos["qty"], 0)
                })
            st.dataframe(pd.DataFrame(holdings), use_container_width=True, hide_index=True)
        else:
            st.write("현재 보유 종목이 없습니다.")

    st.subheader("전체 분석 종목")
    st.dataframe(scored[cols], use_container_width=True, hide_index=True)

    st.subheader("모의매매 체결 내역")
    if st.session_state.trades:
        trades = pd.DataFrame(st.session_state.trades[-30:][::-1])
        st.dataframe(trades, use_container_width=True, hide_index=True)
    else:
        st.write("아직 체결 내역이 없습니다.")

    st.caption(f"마지막 가상 시세 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 5초 주기 DEMO")

live_panel()

with st.expander("전략 점수 구성 및 주의사항"):
    st.markdown("""
    - 추세 강도 35점 + 단기 모멘텀 25점 + 거래량/거래대금 30점 + 위험도 10점
    - 80점 이상을 우선 후보로 분류하는 초기 테스트 규칙입니다.
    - 모의 시세는 실제 시장 데이터가 아닙니다. 종목명·가격·거래량은 모두 테스트용 가상 값입니다.
    - 현재 버전은 NH투자증권 API, 실제 계좌, 실제 주문과 연결되어 있지 않습니다.
    - 익절/손절은 가상 체결 규칙이며 실제 시장의 갭·체결 지연·유동성 위험을 반영하지 않습니다.
    - 실전 전환 전 실제 시세 연동, 수수료·세금 검증, 장기간 백테스트 및 사용자 승인 절차가 필요합니다.
    """)
