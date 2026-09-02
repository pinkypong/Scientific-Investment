# Value Growth Screener

Bigdata.com에서 필요한 데이터만 단계적으로 받아 로컬에서 DCF·상대가치·품질·위험·분산효과를 계산하는 독립 프로젝트다. Scientific-Investment와는 현재 분리되어 있으며 나중에 정규화 JSON/CSV 인터페이스로 합칠 수 있다.

## 핵심 원칙

- 객관적 원자료(`objective`)와 분석자 가정(`assumptions`)을 같은 필드에 저장하지 않는다.
- 객관 근거 점수는 ROIC-WACC, 현금전환, accrual, 레버리지, 성장·추정치 변화, 변동성·분산, 보조신호만 사용한다.
- DCF/상대가치의 상승여력과 안전마진은 가정 의존 결과이므로 객관 점수와 별도 게이트로 사용한다.
- 데이터가 빠지면 0으로 채우지 않고 완전성을 낮춘다.
- 출처가 필드에 연결되지 않은 숫자는 ‘객관 데이터’로 인정하지 않고 출처 연결률 게이트에서 탈락시킨다.
- 기관 보유, 고용, RavenPack 심리는 합계 10점의 보조신호이며 단독 매수근거가 아니다.

후보 순위는 객관 근거 45%, 가정 의존 상승여력 25%, 안전마진 15%, 데이터 완전성 7.5%, 출처 연결률 7.5%에서 경고·치명 플래그를 차감한 ‘위험조정 기회점수’를 쓴다. 객관 점수와 혼동하지 않도록 둘을 모두 출력한다.

## 6개 데이터 축

| 축 | 1차 스크린 | 심층 스크린 |
|---|---|---|
| 재무·밸류·추정치 | overview/ratios/key metrics | estimates/latest earnings |
| SEC·실적·콜 | 신규 이벤트 유무 | 핵심 공시와 콜 원문 |
| 뉴스·리서치·심리 | 30일 집계 | 주요 이벤트와 RavenPack 변화 |
| ETF | 구성·성과·변동성·HHI | 팩터 노출·상관·유동성 |
| 거시·섹터·팩터 | 배치당 시장 스냅샷 1회 | 후보 민감도 시나리오 |
| 기관·고용 | 상위 후보만 | 13F/고용 변화의 원인 확인 |

자세한 호출 절약 규칙은 [docs/collection-plan.md](docs/collection-plan.md), 필드 정의는 [docs/data-contract.md](docs/data-contract.md)에 있다.

## 실행

설치 없이 프로젝트 루트에서 PowerShell로 실행할 수 있다.

```powershell
$env:PYTHONPATH = "src"
python -m vgs.cli analyze examples/synthetic_compounder.json --config config/default.json
python -m vgs.cli screen examples/synthetic_compounder.json --config config/default.json --output ranking.csv
```

첫 명령은 종목별 Markdown 보고서를, 두 번째 명령은 여러 후보의 순위 CSV를 만든다. `--output`을 생략하면 화면에 출력한다.

미국 데이터 계층의 기본 명령은 다음과 같다. 키는 파일이나 명령 인자에 넣지 않는다.

```powershell
$env:SEC_USER_AGENT = "Your Name <CONTACT_EMAIL>"
$env:ALPACA_API_KEY_ID = "..."
$env:ALPACA_API_SECRET_KEY = "..."
$env:FRED_API_KEY = "..."

python -m vgs.cli official-us-universe --trade-date 2026-09-01 --data-root data
python -m vgs.cli sec-security-master --data-root data
python -m vgs.cli sec-snapshot 0001652044 --as-of 2026-09-01 --data-root data
python -m vgs.cli alpaca-bars GOOGL MRVL MU SNDK ADI NVDA QCOM --start 2023-01-01 --end 2026-09-02 --feed iex
python -m vgs.cli ken-french --data-root data
python -m vgs.cli fred --start 2020-01-01 --end 2026-09-01 --vintage-date 2026-09-01 --data-root data
python -m vgs.cli bigdata-queue ranking.csv --data-root data
```

`official-us-universe`는 State Street의 SPY 보유자료와 Nasdaq의 NDX 공식 가중치 자료를 자동 수집한다. Invesco QQQ 다운로드 URL의 자동호출 불안정성을 피하면서 동일한 Nasdaq-100 주식 유니버스를 공식 지수 원천에서 확보한다. `build-universe`는 별도 holdings CSV 합집합과 현재 미국 보유 7개 종목 강제 포함이 필요할 때 사용한다. 과거 백테스트에는 현재 유니버스를 사용하지 않는다.

## 가치평가

비금융 기업은 Damodaran식 FCFF를 기본으로 한다.

- `FCFF = NOPAT - Reinvestment`
- `Reinvestment = 매출 증가 / Sales-to-Capital`
- `Terminal FCFF = Terminal NOPAT × (1 - g / Terminal ROIC)`
- `Equity Value = Enterprise Value - Debt + Cash`

금융사는 `pe` 또는 `p_tbv`, 자본집약 업종은 `ev_ebitda`를 선택할 수 있다. Bear/Base/Bull 확률은 합계 100%여야 한다. Reverse DCF는 현 주가가 요구하는 초기 매출성장률을 역산한다.

WACC 구성 입력이 있으면 `Cost of Equity = Rf + Beta × ERP + CRP`, `After-tax CoD = Pre-tax CoD × (1-tax)`, 시장가치 가중 WACC를 별도로 계산해 시나리오 WACC와 비교한다. DCF 종목은 PE/EV-EBITDA/P-TBV 상대가치 교차검증을 함께 출력한다. ETF는 `etf_lookthrough_pe` 방식으로 편입기업의 look-through 이익·멀티플을 평가한다.

## 판정 게이트

기본값은 객관 근거 점수 65점 이상, Base 안전마진 15% 이상, 필수 데이터 완전성 70% 이상, 출처 연결률 80% 이상, 치명적 플래그 0개다. `config/default.json`에서 조정 가능하다. `PASS_DEEP_DIVE`는 매수 신호가 아니라 SEC·콜·뉴스 원문을 추가 조회할 후보라는 뜻이다.

## 현재 범위

SEC EDGAR·Alpaca·Ken French·FRED 직접 adapter, provider-neutral Security Master·일별 bar record, 원자적 로컬 cache, 공식 SPY/NDX universe builder가 추가되어 있다. SEC companyfacts는 `filed <= as_of`로 시점고정하고 분기·Q4 유도·TTM·FCF를 계산한다. FRED는 `realtime_start=realtime_end=vintage_date`로 당시 빈티지를 고정한다. Alpaca 직접 호출에는 `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, FRED에는 `FRED_API_KEY`가 필요하다. SEC 호출은 식별 가능한 이름과 이메일이 포함된 User-Agent를 사용한다.

2026-09-01 실데이터 적재 결과는 SPY/NDX 보유행 605개, 중복 제거 518종목이다. 현재 미국 보유 7종목이 모두 포함됐다. Ken French FF5 15,854행과 Momentum 26,173행도 적재했으며 제공 파일의 최신일은 2026-06-30이다.

Codex의 Bigdata MCP 연결은 Python 실행 파일이 직접 부를 수 없다. Bigdata 기반 estimates·RavenPack·기관·고용 데이터는 Codex가 상위 후보만 조회해 정규화 JSON으로 넘긴다. 직접 Bigdata API 자격증명이 생기면 동일 데이터 계약을 유지한 채 adapter를 추가한다.

현재 미국 작업 상태와 다음 구현 순서는 [CLAUDE_COWORK_HANDOFF.md](CLAUDE_COWORK_HANDOFF.md)에 유지한다.

샘플은 전부 합성 데이터이며 실제 종목 추천이나 실데이터가 아니다.
