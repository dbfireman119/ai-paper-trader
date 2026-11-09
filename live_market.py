"""Read-only live quote refresh for selected paper-trading candidates."""
from __future__ import annotations

from nh_api import get_current_price


def fetch_live_quotes(codes: list[str], daily_market: dict) -> dict:
    """Refresh only selected candidates and open positions; never calls order APIs."""
    result, errors = {}, []
    for code in dict.fromkeys(codes):
        base = daily_market.get(code)
        if not base:
            errors.append(f"{code}: 기준 일봉 데이터 없음")
            continue
        try:
            quote = get_current_price(code, "KRX")
            raw = quote.get("raw") or {}
            prev = raw.get("stck_sdpr") or raw.get("prdy_clpr") or base["prev"]
            q = dict(base)
            q.update({
                "name": quote.get("name") or base["name"],
                "price": float(quote["price"]),
                "prev": float(prev),
                "quote_time": __import__("datetime").datetime.now(
                    __import__("zoneinfo").ZoneInfo("Asia/Seoul")
                ).strftime("%Y-%m-%d %H:%M:%S"),
            })
            result[code] = q
        except Exception as exc:
            errors.append(f"{code} {base.get('name', '')}: {exc}")
    if errors:
        raise RuntimeError("일부 실시간 시세 조회 실패 — 안전을 위해 이번 주기 모의매매를 중지했습니다: " + " / ".join(errors[:4]))
    return result
