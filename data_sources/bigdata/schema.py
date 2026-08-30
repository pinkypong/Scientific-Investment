"""Bigdata.com tearsheet/search 응답 → 공통 필드 매핑.

현재 대시보드가 실제로 쓰는 값 (index.html refreshQuotes/loadNews):
  - price_performance.current_market.current_price   → price (FACT)
  - (컨센서스 EPS/EBITDA/PE/PB 는 과거 세션에서 수동 확보 → CD.fin[*].eps 에 baked-in)
  - bigdata_search results[].{headline,timestamp,source,url,chunks|summary} → 뉴스/리포트 피드

tearsheet 응답은 sections 파라미터에 따라 구조가 달라짐. 아래는 관대한 경로 탐색.
"""

# tearsheet 에서 값 뽑을 때 시도할 경로들 (첫 히트 사용)
PRICE_PATHS = [
    ("price_performance", "current_market", "current_price"),
    ("company_overview", "price"),
    ("price_performance", "last_close"),
]
MARKETCAP_PATHS = [
    ("company_overview", "market_cap"),
    ("valuation", "market_cap"),
]
CONSENSUS_PATHS = {
    "eps_fwd": [("estimates", "eps", "forward"), ("consensus", "eps_forward")],
    "pe_fwd": [("valuation", "pe_forward"), ("estimates", "pe", "forward")],
    "pb": [("valuation", "pb"), ("valuation", "price_to_book")],
    "ebitda_fwd": [("estimates", "ebitda", "forward")],
    "target_price": [("estimates", "target_price", "mean"), ("consensus", "target_price")],
}

# 뉴스 vs 리포트 분류 신호 (index.html loadNews 의 content-based 분류와 동일 취지)
REPORT_SIGNALS = ("목표주가", "투자의견", "매수의견", "target price", "Overweight", "Underweight",
                  "증권", "Securities", "리서치", "analyst", "애널리스트")
