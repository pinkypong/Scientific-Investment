# 데이터 계약

입력 JSON은 아래 네 영역을 엄격히 분리한다.

1. `security`: 티커, 기업명, 섹터, 통화 같은 식별 정보
2. `objective`: Bigdata.com, SEC, 거래소, ETF 운용사 등에서 관측한 원자료
3. `assumptions`: 성장률, 목표 마진, WACC, 영구성장률, 목표 멀티플처럼 분석자가 정한 숫자
4. `sources`: 원자료별 제공자, 문서 ID/URL, 관측시각, 연결 필드

엔진은 다섯 번째 영역인 `computed`를 결과에 새로 만들며 원자료나 가정을 덮어쓰지 않는다.

## 단위

- 비율은 모두 소수: 12% → `0.12`
- 통화 금액은 동일 통화·동일 배율이어야 한다. 권장 단위는 백만 통화단위다.
- 주식 수와 이익의 배율이 같아야 주당가치가 올바르게 계산된다.
- `ravenpack_sentiment`는 -1~1로 정규화한다.
- `portfolio.concentration_reduction`은 해당 종목 편입 뒤 섹터 HHI 감소분을 양수로 표시한다.

## 객관 필드 그룹

- `market`: price, cash, debt, diluted_shares, market_cap, enterprise_value
- `financials`: revenue_ttm, ebit_margin_ttm, ocf_ttm, net_income_ttm, ebitda_ttm, tangible_book_value
- `ratios`: roic, wacc, ocf_to_net_income, accrual_ratio, debt_to_ebitda, interest_coverage, share_dilution_yoy
- `consensus`: forward_eps, revenue_growth_3y, eps_growth_3y, revision_90d, target_median
- `risk`: beta, max_drawdown_1y
- `portfolio`: correlation, concentration_reduction
- `signals`: institutional_change_pct, workforce_yoy_pct, ravenpack_sentiment
- `capital`: risk_free_rate, beta, equity_risk_premium, country_risk_premium, pre_tax_cost_debt, tax_rate, debt_value, equity_value
- `etf`: lookthrough_forward_pe, concentration_hhi, top10_weight, expense_ratio, tracking_error

`wacc`의 시장 입력값은 객관적 관측치로 보관할 수 있지만 DCF에 실제 적용하는 WACC는 `assumptions.scenarios.*.wacc`에 둔다. 이 구분은 ‘관측값’과 ‘모델 선택’을 혼동하지 않기 위함이다.

DCF 종목에는 `relative_cross_check`를 추가해 PE/EV-EBITDA/P-TBV로 별도 검산할 수 있다. ETF는 `etf_lookthrough_pe` 방법으로 현재 look-through PE, 목표 PE, 평가기간 이익성장을 분리 입력한다.

## 자료 일관성 규칙

- TTM, FY, NTM을 한 필드에 섞지 않는다.
- SEC 원문과 제3자 집계치가 다르면 SEC 값을 우선하고 차이를 플래그로 남긴다.
- 제공자별 기간 라벨이 맞지 않거나 마진 정의가 불명확하면 값을 버리지 말고 `sources`와 품질 플래그에 기록한다.
- 결측치는 0으로 대체하지 않는다. 완전성 점수와 게이트가 처리한다.
