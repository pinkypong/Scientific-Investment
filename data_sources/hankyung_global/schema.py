"""한경 글로벌마켓 종목 페이지 구조 참고.

URL:  https://www.hankyung.com/globalmarket/equities/americas/<ticker소문자>
확인(WebFetch, 2026-08): "예상실적(EPS)" 섹션 존재. 예상실적 컨센서스 표·목표주가·투자의견·PER
필드는 JS 렌더링 + 로그인 게이트(비로그인 시 대시 '—'). 손익/재무상태/현금흐름은 서버 렌더.

→ Playwright 로 탭 클릭 후 렌더된 표를 읽는다. XHR JSON 엔드포인트가 잡히면 raw 로 저장.
   실제 selector 는 --dump-html 로 1회 보정.
"""

TAB_LABELS = {
    "estimates": ["예상실적", "예상 실적", "Estimates"],
    "financials": ["재무", "실적", "Financials"],
}

SELECTORS = {
    "tab_estimates": "a:has-text('예상실적'), button:has-text('예상실적'), [data-tab='estimates']",
    "estimates_table": "table:has-text('EPS'), .estimates-table, [class*='estimate'] table",
    "target_price": "dt:has-text('목표주가') + dd, [class*='target'] .value",
    "rating": "dt:has-text('투자의견') + dd, [class*='opinion'] .value",
    "per": "dt:has-text('PER') + dd",
}

# 예상실적 표 헤더(한글) → canonical metric
ROW_LABEL_MAP = {
    "매출": "revenue", "매출액": "revenue",
    "영업이익": "operating_income",
    "순이익": "net_income", "당기순이익": "net_income",
    "EPS": "eps", "주당순이익": "eps",
}

GATED = ["target_price", "rating", "per"]  # 로그인 없으면 못 받을 수 있는 필드
