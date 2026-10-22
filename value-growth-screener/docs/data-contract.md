# 데이터 계약

입력 JSON은 아래 네 영역을 엄격히 분리한다.

공시 쪽(`security`·`objective`·`sources`)은 `facts/<티커>.json`, 사람의 가정은 `assumptions/<티커>.json`(`{"ticker":…, "assumptions":{…}}`)에 따로 두고 `--assumptions-dir`로 합친다. 공시 파일에 `assumptions`가 있으면 거부한다. 한 파일에 다 담은 기존 형식도 `--assumptions-dir` 없이 그대로 읽는다.

1. `security`: 티커, 기업명, 섹터, 통화 같은 식별 정보
2. `objective`: Bigdata.com, SEC, 거래소, ETF 운용사 등에서 관측한 원자료
3. `assumptions`: 성장률, 목표 마진, WACC, 영구성장률, 목표 멀티플처럼 분석자가 정한 숫자
4. `sources`: 원자료별 제공자, 문서 ID/URL, 관측시각, 연결 필드

엔진은 다섯 번째 영역인 `computed`를 결과에 새로 만들며 원자료나 가정을 덮어쓰지 않는다.

## 애널리스트 추정치 (비교용, 로컬 전용)

추정은 누구 것이든 사실이 아니다. 컨센서스 EPS·목표주가·추정치 리비전은 `objective`에 넣지 않는다. 들어오면 엔진은 점수·완전성·출처연결률·가치평가 입력에서 모두 제외하고 `ANALYST_INPUT_EXCLUDED` 경고를 단다. PE 교차검증의 기본 EPS는 `financials.eps_ttm`이며, 정상화 EPS를 쓰려면 `assumptions.relative_cross_check.eps`에 가정으로 명시한다.

비교해 보려면 입력 JSON의 최상위에 `analyst` 블록을 둔다. `source`와 `as_of`는 필수다.

```json
"analyst": {"source": "제공처 이름", "as_of": "2026-10-20", "url": "https://...",
            "target_price": 130.0, "eps_next_fy": 18.0, "revenue_growth_next_fy": 0.15}
```

- 엔진은 이 블록을 읽지 않고 결과에 그대로 실어 나른다. 어떤 계산 값도 바뀌지 않는다(테스트로 고정).
- `vgs export`는 기본(공개 배포용)으로 이 블록을 쓰지 않는다. `--include-analyst`를 줄 때만 `detail.step3.analyst`에 쓴다. 이 출력은 공개 배포하지 않는다.
- `screen.json`과 `step1`·`step2`에는 어느 경우에도 들어가지 않는다.

## 섹터·업종 (`security`)

`vgs sec-sectors`가 SEC submissions의 SIC 코드로 분류하고, `vgs export --sectors <jsonl>`가 결과에 붙인다(입력 파일은 바꾸지 않음).

| 필드 | 뜻 |
|---|---|
| `security.sector`, `sector_label` | 섹터 키·이름 (`config/sectors.json`의 12개) |
| `security.industry`, `industry_label` | 업종 키·이름 (49개) |
| `security.classification.sic`, `sic_description` | SEC가 공시한 SIC 코드와 설명 (사실) |
| `security.classification.sic_industry` | 규칙만 적용했을 때의 업종 (예외가 있어도 남음) |
| `security.classification.source` | `sec_sic`(규칙) · `override`(사람 예외) · `unclassified`(어느 규칙에도 안 걸림) |
| `security.classification.override_reason`, `override_decided_on` | 예외일 때 이유와 날짜 |
| `security.classification.provider`, `url`, `observed_at`, `map_version` | 출처와 규칙표 버전 |

- 규칙표는 위에서부터 첫 매치. 넓은 범위가 좁은 범위를 가리면 로드할 때 오류.
- 예외는 `config/sector_overrides.json`에 `{"overrides": {"TICKER": {"industry", "reason", "decided_on"}}}`. 이유가 없거나 없는 업종이면 오류.
- `screen.json` 행에는 `sector`, `sector_label`, `industry`, `industry_label`, `sector_source`, `sic`. `--sectors`를 주면 `meta.sectors`에 섹터→업종 목록(표시 순서)이 들어간다.
- 분류는 공시 숫자 해시(`integrity.objective_sha256`)에 포함되지 않는다.

## 단위

- 비율은 모두 소수: 12% → `0.12`
- 통화 금액은 동일 통화·동일 배율이어야 한다. 권장 단위는 백만 통화단위다.
- 주식 수와 이익의 배율이 같아야 주당가치가 올바르게 계산된다.
- `ravenpack_sentiment`는 -1~1로 정규화한다.
- `portfolio.concentration_reduction`은 해당 종목 편입 뒤 섹터 HHI 감소분을 양수로 표시한다.

## 객관 필드 그룹

- `market`: price, cash, debt, diluted_shares, market_cap, enterprise_value
- `financials`: revenue_ttm, ebit_margin_ttm, ocf_ttm, net_income_ttm, ebitda_ttm, eps_ttm, tangible_book_value, book_value(지배주주 자본, XBRL `StockholdersEquity`)
- `ratios`: roic, wacc, ocf_to_net_income, accrual_ratio, debt_to_ebitda, interest_coverage, share_dilution_yoy
- `history`: revenue_cagr_3y, revenue_yoy_ttm, ebit_margin_change_3y — 공시된 FY·분기 값으로만 계산 (`vgs.data.xbrl.reported_growth`)
  - `ttm_series`: 최근 40개 분기말(10년)의 rolling TTM 원자료 목록 (`vgs.data.xbrl.ttm_series`). 각 점은 period_end, revenue, operating_income, net_income, operating_cash_flow, capital_expenditure, ebit_margin, includes_derived_q4, accessions. 연속 4개 분기가 모두 있을 때만 합산하고, 아니면 None으로 남긴다(보간 없음). 분기마다 as_of 이전 최신 공시값을 쓰므로 정정 공시가 원공시를 대체한다.
- `risk`: beta, max_drawdown_1y
- `portfolio`: correlation, concentration_reduction
- `signals`: institutional_change_pct, workforce_yoy_pct, ravenpack_sentiment
- `capital`: risk_free_rate, beta, equity_risk_premium, country_risk_premium, pre_tax_cost_debt, tax_rate, debt_value, equity_value
- `etf`: lookthrough_trailing_pe, concentration_hhi, top10_weight, expense_ratio, tracking_error

`wacc`의 시장 입력값은 객관적 관측치로 보관할 수 있지만 DCF에 실제 적용하는 WACC는 `assumptions.scenarios.*.wacc`에 둔다. 이 구분은 ‘관측값’과 ‘모델 선택’을 혼동하지 않기 위함이다.

DCF 종목에는 `relative_cross_check`를 추가해 PE/EV-EBITDA/P-TBV/RI/EPV로 별도 검산할 수 있다.

## 절대가치 방법 (`assumptions.valuation_method`)

| 방법 | 공시 사실(objective) | 사람 가정(assumptions) |
|---|---|---|
| `fcff` | revenue_ttm, ebit_margin_ttm, cash, debt, diluted_shares | 성장률 경로, 목표마진, 세율, sales_to_capital, wacc, terminal_growth, terminal_roic |
| `ri` 잔여이익 | book_value, net_income_ttm(시작 ROE 기본값), diluted_shares | target_roe, cost_of_equity, payout_ratio, terminal_growth, forecast_years, (선택) roe_start |
| `epv` 이익력가치 | cash, debt, diluted_shares | normalized_revenue, normalized_ebit_margin, tax_rate, wacc, maintenance_capex_adjustment (모두 필수, 기본값 없음) |

- RI: 가치 = 장부가 + Σ(ROE−자기자본비용)×기초장부가 할인 + 잔존가치. ROE는 roe_start→target_roe로 선형 수렴. 장부가는 항상 공시값.
- EPV: 성장 없는 가치 = (정상화 매출 × 정상화 마진 × (1−세율) + 유지capex 조정) ÷ WACC − 부채 + 현금. 정상화는 판단이므로 엔진이 기본값을 채우지 않는다. 하나라도 빠지면 `VALUATION_INPUT` critical.
- RI·EPV 결과의 `inputs`는 숫자마다 `{value, source}`를 담는다. source가 `objective.*`이면 공시 사실, `assumptions.*`이면 가정이다.
- 시장 입력 CAPM과 base 가정이 200bp 넘게 다르면 경고한다: `epv`는 WACC(`WACC_ASSUMPTION_GAP`), `ri`는 자기자본비용(`COE_ASSUMPTION_GAP`). ETF는 `etf_lookthrough_pe` 방법으로 현재 look-through PE, 목표 PE, 평가기간 이익성장을 분리 입력한다.

## 자료 일관성 규칙

- TTM, FY, NTM을 한 필드에 섞지 않는다.
- SEC 원문과 제3자 집계치가 다르면 SEC 값을 우선하고 차이를 플래그로 남긴다.
- 제공자별 기간 라벨이 맞지 않거나 마진 정의가 불명확하면 값을 버리지 말고 `sources`와 품질 플래그에 기록한다.
- 결측치는 0으로 대체하지 않는다. 완전성 점수와 게이트가 처리한다.

## 사이클 구간 (`assumptions.cycle_groups`)

엔진은 사이클을 추정하거나 구간을 나누지 않는다. 사이클을 어떻게 해석할지는 사이클마다 다르기 때문이다.
사람이 `ttm_series`를 보고 구간을 정하면, 엔진은 그 구간 안의 TTM 점에 대해 산술 통계만 낸다.

```json
"cycle_groups": [
  {"label": "2016-2019", "start": "2016-01-01", "end": "2019-12-31"},
  {"label": "2020-2023", "start": "2020-01-01", "end": "2023-12-31"}
]
```

결과 `computed.cycle_comparison`: 구간별 TTM 점 개수, 처음·끝 분기말, 처음·끝 매출과 변화율, 영업이익률 평균·최저·최고(시점 포함).
평균은 겹치는 rolling TTM 점들의 단순평균이다. 이 결과는 점수·플래그·게이트에 쓰이지 않는다.
