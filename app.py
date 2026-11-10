import os
import hmac
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from engine import (
    STRATEGIES, initialize_state, score_universe,
    portfolio_snapshot, reset_session, run_strategy, _new_portfolio
)
from live_market import fetch_live_quotes
from market_scanner import start_scan, get_scan_state
from db_store import load_state, save_state, save_strategy_settings, save_auto_trade_enabled

st.set_page_config(page_title="AI 모의매매 비교", page_icon="📈", layout="wide")

site_username = os.getenv("SITE_USERNAME", "")
site_password = os.getenv("SITE_PASSWORD", "")

def persist_auto_trade_toggle():
    try:
        save_auto_trade_enabled(bool(st.session_state.get("auto_trade", False)))
    except Exception as exc:
        st.session_state["auto_trade_save_error"] = str(exc)
if not site_username or not site_password:
    st.error("사이트 접근 설정이 완료되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

# Streamlit session_state is recreated on a browser refresh. Keep a signed,
# time-limited session token in the browser cookie so refresh does not log out.
# The cookie contains no password; its signature prevents users from forging it.
try:
    import extra_streamlit_components as stx
    cookie_manager = stx.CookieManager(key="paper_trader_auth_cookie")
    auth_cookie_name = "paper_trader_session"
    session_secret = os.getenv("SITE_SESSION_SECRET", site_password).encode("utf-8")

    def make_session_token():
        expires = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
        payload = str(expires)
        signature = hmac.new(session_secret, payload.encode("utf-8"), "sha256").hexdigest()
        return f"{payload}.{signature}"

    def valid_session_token(token):
        try:
            expires_text, supplied_signature = str(token).split(".", 1)
            expires = int(expires_text)
            expected = hmac.new(session_secret, expires_text.encode("utf-8"), "sha256").hexdigest()
            return expires > int(datetime.now(timezone.utc).timestamp()) and hmac.compare_digest(supplied_signature, expected)
        except (TypeError, ValueError):
            return False

    # CookieManager is a browser component. On a hard refresh its first
    # Python pass can run before the browser has returned cookie values.
    # Wait for component readiness instead of incorrectly showing the login form.
    if not cookie_manager.ready():
        st.info("로그인 상태를 확인하고 있습니다...")
        st.stop()

    if not st.session_state.get("site_authenticated", False):
        saved_cookies = cookie_manager.get_all() or {}
        saved_token = saved_cookies.get(auth_cookie_name)
        if valid_session_token(saved_token):
            st.session_state.site_authenticated = True
except Exception as exc:
    st.error(f"로그인 유지 기능을 불러오지 못했습니다: {exc}")
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
            cookie_manager.set(
                cookie=auth_cookie_name,
                val=make_session_token(),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            st.session_state.site_authenticated = True
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    st.stop()

initialize_state()
if st.session_state.get('persistence_restored'):
    st.success('Saved paper portfolio restored.')
elif st.session_state.get('persistence_error'):
    st.warning('Database is not connected yet; this session is temporary.')
st.title("📈 AI 모의매매 전략 비교")
st.caption("NH투자증권 실제 국내주식 시세 기반 · 4개 독립 모의계좌 · 실제 주문 기능 없음 · 새로고침 시 로그인 유지")

with st.sidebar:
    st.subheader("공통 운용")
    st.metric("각 전략 초기 자금", "500,000원")
    st.toggle("4개 전략 자동 모의매매", key="auto_trade", on_change=persist_auto_trade_toggle)
    if st.session_state.get("auto_trade_save_error"):
        st.warning(f"자동매매 설정 저장 실패: {st.session_state['auto_trade_save_error']}")
    st.caption("켜면 4개 전략이 각각 독립된 가상계좌로 모의매매합니다. 정밀 스캘핑형은 현재 실시간 수신을 확인한 뒤 검증용 모의매매를 수행합니다.")
    st.divider()
    st.subheader("전체 시장 스캔")
    scan_info = get_scan_state()
    if st.button("전체 종목 다시 점수화", use_container_width=True, disabled=scan_info["status"] == "running"):
        start_scan(force=True)
        st.rerun()
    st.caption("국내주식 종목마스터를 기준으로 전체 상장주식의 최근 80거래일을 분석합니다. 최초 스캔은 API 호출량에 따라 수 분 이상 걸릴 수 있습니다.")
    st.divider()
    st.subheader("나무증권 API")
    st.caption("실제 시세만 조회합니다. 모든 매수·매도는 프로그램 내부 가상계좌에서만 처리합니다.")
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
        st.info("실제 시세 연동 모드입니다. API 오류 시 가상 시세로 대체하지 않고 매매를 중지합니다.")
    st.divider()
    if st.button("네 모의계좌 모두 초기화", use_container_width=True):
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
        st.caption("이 설정은 해당 전략에만 적용됩니다. 초기값 복원은 설정값만 변경하며 보유 종목·거래 내역·가상 잔액은 초기화하지 않습니다.")
        if st.button(f"↩ {name} 설정을 처음값으로 복원", key=f"{name}_reset_settings", use_container_width=True):
            defaults = dict(STRATEGIES[name])
            st.session_state.strategy_settings[name] = defaults
            # Streamlit widgets with explicit keys keep their own values in
            # session_state. Update those keys directly; popping them can leave
            # the browser-rendered controls showing the previous values.
            widget_defaults = {
                f"{name}_threshold": defaults["buy_threshold"],
                f"{name}_max_positions": defaults["max_positions"],
                f"{name}_max_position": defaults["max_position"],
                f"{name}_min_trend": defaults["min_trend"],
                f"{name}_min_momentum": defaults["min_momentum"],
                f"{name}_min_volume": defaults["min_volume_ratio"],
                f"{name}_max_risk": defaults["max_risk"],
                f"{name}_max_change": defaults["max_change_pct"],
                f"{name}_reserve": defaults["cash_reserve"],
                f"{name}_stop": defaults["stop_loss_pct"],
                f"{name}_trail_start": defaults["trailing_activation_pct"],
                f"{name}_trail_gap": defaults["trailing_gap_pct"],
                f"{name}_risk_budget": defaults["risk_budget_pct"],
                f"{name}_daily_loss": defaults["daily_loss_limit"],
            }
            for widget_key, default_value in widget_defaults.items():
                st.session_state[widget_key] = default_value
            try:
                save_strategy_settings(st.session_state.strategy_settings)
            except Exception as exc:
                st.error(f"초기 설정 저장 실패: {exc}")
                st.stop()
            st.success(f"{name} 설정을 최초 기본값으로 복원했습니다.")
            st.rerun()
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
                q = st.session_state.market.get(code) or {}
                price = float(q.get("price") or pos.get("last_price") or pos["avg_price"])
                rows.append({
                    "종목코드": code,
                    "종목명": q.get("name") or pos.get("name") or code,
                    "수량": pos["qty"],
                    "매입가": round(pos["avg_price"]), "현재가": round(price),
                    "수익률(%)": round((price / pos["avg_price"] - 1) * 100, 2),
                    "평가손익": round((price - pos["avg_price"]) * pos["qty"]),
                    "시세상태": "실시간" if q.get("price") is not None else "최근 확인가(시세 미수신)",
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

# Start a fresh full-market scan once per trading date.
scan_info = get_scan_state()
today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
if scan_info["status"] == "idle" or (
    scan_info["status"] == "complete"
    and (scan_info.get("finished_at") or "")[:10] != today_kst
):
    start_scan()

scored = pd.DataFrame()
top200_scored = pd.DataFrame()

@st.fragment(run_every="30s")
def live_panel():
    global scored, top200_scored
    scan = get_scan_state()
    if scan["status"] in {"idle", "starting", "running"}:
        if scan["total"]:
            progress = min(1.0, scan["done"] / scan["total"])
            st.progress(progress, text=f"전체 종목 분석 중: {scan['done']:,}/{scan['total']:,} · 성공 {scan['success']:,} · 제외/오류 {scan['failed']:,}")
        else:
            st.info("NH투자증권 전체 종목마스터를 불러오는 중입니다.")
        st.caption("전체 종목의 최근 80거래일을 순차 분석합니다. 분석이 끝날 때까지 자동 모의매매는 시작되지 않습니다.")
        return
    if scan["status"] == "error":
        st.error(f"전체 종목 스캔 실패: {scan.get('error')}")
        return
    daily_market = scan["market"]
    if not daily_market:
        st.warning("분석 가능한 종목 데이터가 없습니다.")
        return

    try:
        latest_state = load_state()
        if latest_state:
            # Merge database state with current strategy defaults. Older DB rows
            # may not contain newly introduced strategies such as scalping.
            st.session_state.portfolios = {
                **{name: _new_portfolio() for name in STRATEGIES},
                **latest_state.get("portfolios", {}),
            }
            merged_settings = {name: dict(cfg) for name, cfg in STRATEGIES.items()}
            merged_settings.update(latest_state.get("strategy_settings", {}))
            st.session_state.strategy_settings = merged_settings
    except Exception as exc:
        st.warning(f"공유 계좌 상태 갱신 실패: {exc}")

    st.session_state.market = dict(daily_market)
    daily_scored = score_universe()
    top200_daily = daily_scored.head(200)
    top20_codes = top200_daily[top200_daily["거래가능"]]["code"].head(20).tolist()
    held_codes = []
    for pf in st.session_state.portfolios.values():
        held_codes.extend(list(pf["positions"].keys()))
    active_codes = list(dict.fromkeys(top20_codes + held_codes))

    try:
        live_quotes = fetch_live_quotes(active_codes, daily_market)
        st.session_state.market.update(live_quotes)
        st.session_state["live_quote_error"] = None
        st.session_state.tick += 1
        all_scored = score_universe()
        top200_scored = all_scored.head(200).copy()
        top20_scored = top200_scored[top200_scored["거래가능"]].head(20).copy()
        scored = top20_scored
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        market_open = (
            now.weekday() < 5
            and (now.hour > 9 or (now.hour == 9 and now.minute >= 5))
            and (now.hour < 15 or (now.hour == 15 and now.minute < 20))
        )
        # Precision strategy is enabled in paper-only validation mode. Its
        # independent portfolio uses the existing live quote + scored-universe
        # engine with tighter risk settings. Raw tick/orderbook indicators are
        # still being validated before they become entry filters.
        from precision_scalping import start_precision_feed, get_precision_feed_state
        start_precision_feed(top20_codes)
        precision_feed = get_precision_feed_state()
        if st.session_state.auto_trade and market_open:
            for strategy_name in ("안정형", "공격형", "스캘핑형"):
                run_strategy(strategy_name, scored)
            if precision_feed["trade_count"] > 0 and precision_feed["book_count"] > 0:
                run_strategy("정밀 스캘핑형", scored)
                st.success("4개 전략 모의매매 처리 완료 · 정밀 스캘핑은 실시간 체결·호가 수신 확인 후 검증 운용 중")
            else:
                st.info("기존 3개 전략 모의매매 중 · 정밀 스캘핑은 체결·호가 데이터가 모두 들어오면 시작합니다.")
        elif st.session_state.auto_trade and not market_open:
            st.info("정규장 모의매매 가능 시간(평일 09:05~15:20)이 아닙니다.")

        st.success(f"전체 분석 {len(daily_market):,}종목 · 상위 200개 선별 · 실시간 추적 {len(live_quotes)}개 · 갱신 {now.strftime('%H:%M:%S')}")
        st.subheader("🏆 전체 시장 점수 상위 200개")
        st.caption("순위는 전체 종목의 최근 일봉 지표로 산출합니다. 상위 20개 거래가능 종목만 실시간 현재가를 갱신해 두 전략의 가상매매 후보로 사용합니다.")
        display_cols = ["종목명", "시장", "현재가", "등락률(%)", "거래량비율", "AI점수", "거래가능", "매매검증"]
        st.dataframe(top200_scored[display_cols], use_container_width=True, hide_index=True, height=520)
        st.caption(f"분석 기준일: {max(q.get('history_date', '') for q in daily_market.values())} · 스캔 완료: {scan.get('finished_at', '')}")
    except Exception as exc:
        st.session_state["live_quote_error"] = str(exc)
        scored = score_universe().head(0)
        st.error(f"실시간 후보 시세 수신 실패 — 안전을 위해 이번 주기 모의매매를 중지했습니다: {exc}")

    if st.session_state.get("market"):
        t1, t2, t3, t4 = st.tabs(["🛡️ 안정형", "🚀 공격형", "⚡ 스캘핑형", "🎯 정밀 스캘핑형"])
        with t1:
            show_strategy("안정형")
        with t2:
            show_strategy("공격형")
        with t3:
            show_strategy("스캘핑형")
        with t4:
            show_strategy("정밀 스캘핑형")
            from precision_scalping import get_precision_feed_state
            feed = get_precision_feed_state()
            st.subheader("NH 실시간 체결·호가 데이터 연결")
            st.write(f"연결 상태: {feed['status']} · 추적 종목: {len(feed['codes'])}개")
            a, b = st.columns(2)
            a.metric("실시간 체결 수신", feed["trade_count"], feed["last_trade_at"] or "수신 대기")
            b.metric("실시간 호가 수신", feed["book_count"], feed["last_book_at"] or "수신 대기")
            if feed["last_error"]:
                st.warning(feed["last_error"])
            if feed["field_names"]:
                st.caption("수신 확인된 데이터 필드: " + ", ".join(feed["field_names"]))
            st.info("정밀 스캘핑 모의계좌는 별도로 운용합니다. 현재 검증 운용은 실시간 시세·일봉 점수와 정밀 스캘핑 전용 위험설정을 사용하며, 실제 주문은 전혀 실행하지 않습니다. 1분봉·VWAP·EMA·RSI·호가 불균형을 실제 수신 필드에 맞춰 검증한 뒤 진입 필터에 추가합니다.")
        try:
            save_state(st.session_state.portfolios, st.session_state.strategy_settings)
            st.caption("Paper accounts saved to database.")
        except Exception as exc:
            st.error(f"Portfolio save failed: {exc}")

live_panel()

with st.expander("두 전략의 비교 기준 및 주의사항"):
    st.markdown("""
    - **안정형:** 진입 기준을 높이고 현금 유보액과 손실 제한을 크게 두는 방식입니다.
    - **공격형:** 매수 기준을 낮추고 종목당 투자 한도·위험예산을 높여 기회를 더 적극적으로 탐색합니다.
    - **스캘핑형:** 기존 30초 시세 갱신 기반 단기 전략입니다.
    - **정밀 스캘핑형:** NH PLUG WebSocket 실시간 체결·호가 데이터를 수집하고 있습니다. 데이터 필드 검증 전에는 자동 매매를 실행하지 않습니다.
    - 네 전략은 동일한 NH투자증권 시세 기반으로 운용하지만 현금, 보유종목, 체결내역, 손익, 손실중지 상태가 완전히 분리된 가상계좌입니다.
    - 매도는 고정 익절 대신 트레일링 스톱과 추세 이탈을 사용합니다.
    - 일일 손실 한도에 도달하면 해당 전략만 신규 매수를 중지합니다.
    - 실제 시세를 사용하더라도 체결은 가상으로 계산하며, 호가 차이·체결 지연·수수료·세금 등이 실제 시장과 달라 실전 수익률을 의미하지 않습니다.
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
