# Value Growth Screener — Claude Cowork 핸드오프

기준일: 2026-09-02 (Asia/Seoul)

## 1. 프로젝트 목적

미국 상위 종목을 대상으로 공시 원자료와 시장 데이터를 정규화하고, 객관적 재무 품질·가치·성장·위험 팩터로 1차 스크리닝한 뒤 상위 후보에만 애널리스트 추정치, RavenPack 심리, 공시·콘퍼런스콜과 DCF를 추가하는 로컬 투자 리서치 시스템이다.

Scientific-Investment와는 현재 별도 프로젝트로 유지한다. 충분히 검증한 뒤 정규화 JSON/CSV 인터페이스를 통해 합친다.

프로젝트 절대경로:

```text
C:\Users\eigoo\Documents\Codex\Investment-Report\Value-Growth-Screener
```

OneDrive에 프로젝트 산출물을 저장하지 않는다.

## 2. 사용자 의사결정 배경

현재 미국 보유 종목은 GOOGL, MRVL, MU, SNDK, ADI, NVDA, QCOM이다. 반도체 집중도를 단순히 줄이는 것이 아니라 내재가치, 상대가치, 매크로 환경, 위험 대비 기대수익률을 기준으로 MRVL·SNDK 등의 보유 지속 또는 교체 여부를 판단하려는 목적이다.

미국 스크리닝 기본 유니버스는 다음과 같이 제안되어 있다.

- S&P 500 + Nasdaq-100 중복 제거
- 현재 보유 미국 종목은 지수 포함 여부와 무관하게 강제 포함
- 은행·보험·REIT·적자 바이오는 범용 FCFF 점수에서 분리
- Visa·Mastercard 같은 결제 네트워크는 `payment_network` 전용 유형으로 포함

## 3. 완료된 구현

### 계산 엔진

- 객관적 원자료 `objective`, 분석자 가정 `assumptions`, 계산 결과 `computed` 분리
- Damodaran식 FCFF DCF
- 시장가치 가중 WACC 구성
- Bear/Base/Bull 확률가중 적정가치
- Reverse DCF 내재 초기 매출성장률
- PE, EV/EBITDA, P/TBV 상대가치 교차검증
- ETF look-through PE 평가
- 상승여력과 Base 안전마진
- ROIC-WACC, OCF/순이익, accrual, 희석, 레버리지, 이자보상 품질 플래그
- Beta, 최대낙폭, 포트폴리오 상관, 집중도 감소 반영
- 기관·고용·RavenPack 심리는 보조신호로 제한
- 데이터 완전성 및 필드별 출처 연결률 게이트
- 종목별 Markdown 리포트 및 복수 종목 CSV 순위 출력

### 현재 점수 구조

- 객관 근거 점수: 품질 30, 성장·리비전 20, 재무안정성 20, 시장위험·분산 20, 보조신호 10
- 위험조정 기회점수: 객관 근거 45%, 상승여력 25%, 안전마진 15%, 데이터 완전성 7.5%, 출처 연결률 7.5%, 위험 플래그 차감
- 기본 게이트: 객관 점수 65, 안전마진 15%, 완전성 70%, 출처 연결률 80%, critical flag 0

이 가중치는 아직 실증 검증되지 않은 프로토타입이다. 매매 신호로 사용하면 안 된다.

### 테스트

합성 fixture와 provider 응답 fixture 기반 단위테스트 16개가 통과한다.

```powershell
Set-Location 'C:\Users\eigoo\Documents\Codex\Investment-Report\Value-Growth-Screener'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

### 데이터 연결 확인

- Bigdata.com 플러그인 연결 완료
- Bigdata 기업 tearsheet에서 FMP 기반 재무·비율·애널리스트 추정치 조회 확인
- Bigdata market tearsheet 및 RavenPack/Bigdata sentiment 접근 가능
- 2026-09-02 Codex에서 Alpaca 플러그인 설치 및 연결 완료
- Alpaca IEX feed로 GOOGL, MRVL, MU, SNDK, ADI, NVDA, QCOM의 최근 일별 OHLCV 조회 성공
- provider-neutral `SecurityRecord`, `MarketBar`와 원자적 JSON/JSONL cache 구현
- SEC `company_tickers_exchange`, submissions, companyfacts 직접 adapter 구현
- Alpaca batch daily bars·pagination·adjustment·feed 직접 adapter 구현
- holdings CSV 합집합, SEC Security Master 보강, 미국 보유 7종목 강제 포함 universe builder 구현
- `sec-security-master`, `alpaca-bars`, `build-universe` CLI 구현
- State Street SPY와 Nasdaq NDX 공식 XLSX 자동 수집·스키마 검증 구현
- 2026-09-01 공식 보유행 605개, 중복 제거 518종목 적재; 현재 미국 보유 7종목 포함 확인
- SEC companyfacts의 `filed <= as_of` 시점고정, 분기·유도 Q4·TTM·FCF 정규화 구현
- Kenneth French FF5/Momentum 공식 ZIP 수집과 퍼센트→소수 정규화 구현
- 2026-09-02 적재 기준 FF5 15,854행, Momentum 26,173행; 제공 파일 최신일 2026-06-30
- FRED/ALFRED vintage 고정 adapter 구현
- 순위 상위 50/20/15개만 단계적으로 확장하는 Bigdata 심층조회 JSONL 큐 구현
- `official-us-universe`, `sec-snapshot`, `ken-french`, `fred`, `bigdata-queue` CLI 구현

주의: Codex 플러그인 연결 상태는 Claude Cowork에 자동 이전되지 않는다. Claude 쪽에서도 별도의 MCP/API 연결이 필요하다.

## 4. 아직 구현되지 않은 부분

공식 현재 유니버스와 Ken French 팩터는 실제 적재했다. SEC·FRED·Alpaca 직접 대량 적재는 로컬 셸에 환경변수가 없어 아직 실행하지 않았다. Codex Alpaca 플러그인으로 현재 보유 7종목의 실제 IEX bar 조회 자체는 검증했다. Bigdata MCP는 Python이 직접 호출하지 않는다.

- FIGI/CUSIP와 ticker history를 포함하는 장기 Security Master
- 과거 편출입·상장폐지 종목을 포함하는 point-in-time universe
- SEC nightly bulk ZIP 다운로드, 압축 해제, incremental refresh
- SEC 회사별 extension tag, 통화·주식분할, 복합 debt taxonomy 정규화
- 사용자 직접 Alpaca API 자격증명으로 장기 일별 bars 실제 적재
- 시점별 발행주식 수와 과거 시가총액 계산
- 업종 중립 percentile/z-score와 winsorization
- 업종별 valuation/factor 모델
- 실제 종목 및 과거 시점 백테스트
- 거래비용, 세금, 환율, 유동성, 공분산 기반 포트폴리오 계층

## 5. 현재 팩터의 핵심 한계

1. 모든 업종에 같은 필수 필드와 절대 임계값을 적용한다.
2. 애널리스트 추정치와 RavenPack 가공 심리가 `objective`에 들어가 순수 공시 사실과 완전히 분리되지 않았다.
3. 결측값은 팩터 0점과 완전성 하락으로 이중 감점된다.
4. ROIC·현금전환·레버리지 및 성장·EPS 리비전 간 중복노출을 제거하지 않는다.
5. 수동 가중치와 선형 점수 경계가 백테스트로 검증되지 않았다.
6. FCFF가 선형 성장·마진 fade를 사용해 반도체 사이클과 구조조정을 충분히 표현하지 못한다.
7. 은행, 보험, REIT, pre-revenue biotech 전용 모델이 없다.
8. Beta·1년 최대낙폭·단일 상관계수만으로 꼬리위험과 유동성을 충분히 측정하지 못한다.
9. 현재 구성종목만 사용하면 생존편향과 선행편향이 발생한다.
10. 출처 연결률은 필드가 출처에 연결되었는지만 확인하며 숫자의 회계적 정확성을 보장하지 않는다.

## 6. 합의된 데이터 소스 전략

### 전 종목 저비용 데이터

- SEC EDGAR: 재무제표, 10-K/10-Q/8-K, 13F, Forms 3/4/5
- Alpaca: 일별 가격·수익률·거래량. 무료 IEX volume은 전체 SIP volume이 아님을 표시
- SPY·QQQ 운용사 공식 holdings: 현재 유니버스의 실용적 proxy
- Kenneth French Data Library: 미국 factor returns
- FRED/ALFRED: 금리·인플레이션·경기·당시 발표 vintage

### 상위 후보에만 적용

- Bigdata/FMP: 애널리스트 추정치, 리비전, 재무 교차검증
- Bigdata/RavenPack: 30일 sentiment 평균·변화·기사 수
- Bigdata: 기관 동향과 modeled hiring trends
- SEC 원문과 실적 콜: 최종 10~20개 후보

### 추후 유료 보완

- Norgate Data: 과거 지수 편출입·상장폐지 포함 point-in-time universe
- Finnhub 또는 별도 estimates API: 전체 자동 컨센서스 스냅샷
- Lightcast: 회사별 채용공고 추세. 신호의 유효성을 확인한 뒤 도입

## 7. 구현 우선순위

### P0 — 재현 가능한 미국 1차 스크린

1. 완료: `data/raw`, `data/normalized`, `data/cache`, `data/reports` 디렉터리 정책
2. 완료: Security Master 기본 스키마와 SEC CIK 매핑 수집기
3. 진행 필요: SEC nightly bulk ZIP 및 incremental refresh
4. 완료: Alpaca 일별 bars 정규화 형식과 직접 API adapter
5. 완료: SPY·NDX 공식 파일 자동 다운로드, 비주식 placeholder 제외, 현재 보유 포함 검증
6. 진행 필요: 순수 공시 사실 점수와 시장 기대 점수 분리

### P1 — 횡단면 팩터 재설계

1. 섹터별 winsorized percentile 또는 robust z-score
2. Value, Quality, Growth, Estimate, Risk를 독립 팩터로 분리
3. 결측값은 0점이 아니라 비교집단 내 중립 또는 별도 coverage penalty 처리
4. 팩터 상관·VIF·rank IC로 중복 측정
5. 반도체에는 mid-cycle margin, inventory, CAPEX, sales-to-capital을 추가

### P2 — 계층형 심층 리서치

- 전체 유니버스: SEC + 가격 기반 1차 스크린
- 상위 50개: estimates, 최신 earnings, 13F 변화
- 상위 20개: RavenPack, 채용, 공시·콜 원문
- 상위 10~15개: DCF, reverse DCF, 상대가치, 확률 시나리오
- 현재 보유종목과 세후 기대수익·하방·집중도 기준 교체 비교

### P3 — 검증

- 최소 5~10년 walk-forward 백테스트
- point-in-time 재무와 당시 유니버스 사용
- 섹터 중립 성과, turnover, 거래비용, drawdown, hit rate, rank IC 측정
- 가중치와 임계값은 훈련·검증 기간을 분리해 결정

## 8. 보안 및 데이터 정책

- API 키를 Markdown, JSON fixture, Git, 대화 메시지에 저장하지 않는다.
- 직접 API adapter를 만들 경우 환경변수 또는 OS secret store를 사용한다.
- 권장 환경변수명: `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `FRED_API_KEY`
- SEC는 API 키가 없지만 식별 가능한 `User-Agent`와 요청 제한·캐시 정책을 준수한다.
- 원문, 정규화 값, 계산 값, 분석자 가정을 별도 저장한다.
- 모든 값에 `provider`, `observed_at`, `period_end`, `filing_date`, `accession/document_id`, `unit`, `currency`를 연결한다.

## 9. 토큰 절약 원칙

- SEC bulk ZIP과 가격 바는 Python에서 직접 처리하고 LLM에 원문 전체를 넣지 않는다.
- 시장·팩터 스냅샷은 배치당 한 번만 조회한다.
- 검색은 메타데이터 → 선택 문서 fetch 순서로 수행한다.
- 1차 탈락 종목에는 뉴스·RavenPack·콜 원문을 요청하지 않는다.
- LLM에는 상위 후보의 정규화 표, 예외 플래그, 필요한 공시 문단만 전달한다.

## 10. 프로젝트 주요 파일

- `README.md`: 프로젝트 개요와 실행법
- `src/vgs/engine.py`: DCF·점수·게이트·순위 엔진
- `src/vgs/report.py`: Markdown/CSV 출력
- `src/vgs/cli.py`: `analyze`, `screen` CLI
- `src/vgs/data/models.py`: Security Master·OHLCV 표준 레코드
- `src/vgs/data/cache.py`: 원자적 로컬 JSON/JSONL cache
- `src/vgs/data/sec.py`: SEC EDGAR adapter
- `src/vgs/data/alpaca.py`: Alpaca daily bars adapter
- `src/vgs/data/universe.py`: holdings 합집합과 강제 편입
- `src/vgs/data/holdings.py`: State Street SPY·Nasdaq NDX 공식 XLSX 수집/파싱
- `src/vgs/data/xbrl.py`: SEC point-in-time 분기·TTM 정규화
- `src/vgs/data/factors.py`: Ken French·FRED/ALFRED 수집
- `src/vgs/data/deep_dive.py`: 토큰 절약형 Bigdata 심층조회 큐
- `config/default.json`: 게이트와 수집 설정
- `docs/data-contract.md`: 객관·주관·출처 데이터 계약
- `docs/collection-plan.md`: 단계별 저비용 수집 전략
- `docs/source-map.md`: 데이터 소스와 필드 매핑
- `examples/synthetic_compounder.json`: 합성 데이터 fixture
- `tests/test_engine.py`: 단위테스트

## 11. Claude Cowork 시작 지침

1. 위 프로젝트 경로를 직접 연다.
2. 이 문서와 `README.md`, `docs/data-contract.md`, `src/vgs/engine.py`를 먼저 읽는다.
3. 기존 파일을 대량 재작성하지 말고 작은 변경 단위로 작업한다.
4. 첫 작업은 `SEC_USER_AGENT`, `FRED_API_KEY`, Alpaca 직접 API 환경변수를 설정한 뒤 전체 518종목 실제 적재를 수행하는 것이다.
5. 플러그인 연결이 없으면 수집기를 provider interface와 fixture로 구현하고 키·데이터를 추측하지 않는다.
6. 변경 뒤 위 테스트 명령을 실행한다.
7. Scientific-Investment에는 아직 합치지 않는다.

## 12. 완료 판정

미국 1차 스크리너의 최소 완료 조건은 다음과 같다.

- 현재 S&P 500/QQQ proxy universe와 보유 종목을 재현 가능하게 생성
- SEC와 시장 데이터의 as-of 시점을 보존
- 최소 3년 일별 가격과 5년 분기/연간 재무를 정규화
- 업종 중립 팩터 순위와 coverage 표시
- 현재 보유 7개 종목이 항상 결과에 포함
- 원자료·추정치·모델 가정이 분리
- 실제 종목 fixture와 오류·결측·분할·재공시 테스트 통과
- 상위 후보만 Bigdata 심층조회 큐에 들어감

## 13. 2026-09-02 실행 상태와 바로 다음 명령

구현·fixture 검증·공식 유니버스 및 Ken French 실데이터 적재까지 완료했다. 전체 테스트는 16/16 통과했고 CLI 10개 명령의 help 로딩도 확인했다. 공식 유니버스는 518개 고유 종목이며 GOOGL, MRVL, MU, SNDK, ADI, NVDA, QCOM이 모두 포함된다. SPY 원본의 비주식 CVR placeholder 1건은 유효 ticker 규칙으로 제외했다.

현재 실행 호스트에서 값 자체를 출력하지 않고 환경변수 존재 여부를 검사한 결과 `SEC_USER_AGENT`, `FRED_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`가 모두 미설정이다. 따라서 아래는 자격정보 설정 직후 수행할 운영 적재 단계다.

```powershell
$env:SEC_USER_AGENT = "Your Name <CONTACT_EMAIL>"
$env:FRED_API_KEY = "..."
$env:ALPACA_API_KEY_ID = "..."
$env:ALPACA_API_SECRET_KEY = "..."

python -m vgs.cli sec-security-master --data-root data
python -m vgs.cli fred --start 2020-01-01 --end 2026-09-01 --vintage-date 2026-09-01 --data-root data
python -m vgs.cli alpaca-bars GOOGL MRVL MU SNDK ADI NVDA QCOM --start 2023-01-01 --end 2026-09-02 --feed iex --data-root data
```

SEC 518종목 companyfacts와 Alpaca 518종목 bars의 증분 배치 실행기는 아직 별도 명령으로 묶지 않았다. 먼저 위 소규모 운영 적재로 계정·rate limit·스키마를 확인한 후 배치 크기와 재시도 정책을 고정해야 한다. 실제 `ranking.csv`가 생성되면 다음 명령이 Bigdata 큐를 만들며, 현재 미국 보유 7종목은 자동으로 tier 4에 추가된다.

```powershell
python -m vgs.cli bigdata-queue ranking.csv --data-root data
```
