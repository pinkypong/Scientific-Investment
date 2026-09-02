# 데이터 소스 맵

| 데이터 축 | Bigdata.com 저비용 호출 | 상위 후보 심층 호출 | 정규화 목적지 |
|---|---|---|---|
| 재무·밸류·추정치 | company tearsheet의 overview/ratios/key metrics | analyst estimates/latest earnings | `objective.market`, `financials`, `ratios`, `consensus` |
| SEC·실적·콜 | search 메타데이터 | fetch로 선택 공시·콜 원문 | `sources`, 품질·위험 플래그 |
| 뉴스·리서치·심리 | sentiment tearsheet 집계 | 주요 이벤트 검색·선택 fetch | `signals.ravenpack_sentiment` |
| ETF | ETF tearsheet 핵심 섹션 | 구성·팩터·유동성 상세 | `objective.etf`, `risk`, `portfolio` |
| 거시·금리·환율·팩터 | market tearsheet 배치당 1회 | country/sector 세부값 | `objective.capital`, 시나리오 근거 |
| 기관·고용 | 상위 후보만 검색 | 13F/공시·고용 이벤트 검증 | `signals.institutional_change_pct`, `workforce_yoy_pct` |

직접 수집 원천은 SPY(State Street 공식 XLSX), NDX(Nasdaq 공식 weightings XLSX), SEC companyfacts, Alpaca 일별 bars, Kenneth French FF5/Momentum, FRED/ALFRED다. 원본은 `data/raw`, 재사용 응답은 `data/cache`, 표준 레코드는 `data/normalized`, 심층조회 큐와 보고서는 `data/reports`에 둔다.

검색은 항상 메타데이터 → 선택 문서 원문 순서로 진행한다. 각 값은 제공자, 관측시각, URL/문서 ID, 연결 필드를 `sources`에 남긴다. Bigdata의 하위 제공자(FMP, SEC, RavenPack 등)도 가능한 범위에서 함께 기록한다.
