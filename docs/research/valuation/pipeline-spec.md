# Actual-Data-First 리서치 파이프라인 — 스펙 & 세션 기록

> 위치: `docs/research/valuation/pipeline-spec.md`
> 최종 갱신: 2026-08-30
> 상태: **Phase A·B·C·D COMPLETE · Phase E1 COMPLETE** (SEC EDGAR + OpenDART actual foundation · 증분 동기화/TTL · 보안 강화 · 프로토타입 Phase C · company raw cache/no-network · Damodaran 업종 기준점 + recipe selector)
> 관련 문서: `데이터소스_아키텍처_리팩터_설계서_v1.md`(지배) · `플랫폼_설계서_v1.md` · `AGENTS.md`
> 다음 세션: `docs/research/valuation/next-session.md`

---

## 0. 목적 / 방향

증권사 리포트·컨센서스·목표주가·forward EPS 를 **actual core 에서 분리**하고,
**실제 관측/공식 공시 데이터**만으로 투자분석 대시보드의 데이터 기반(foundation)을 만든다.

```
REAL SOURCES → RAW → NORMALIZED → DERIVED → DASHBOARD
```

- 존재하지 않는 데이터는 임의 생성 금지 → `INSUFFICIENT_DATA`.
- 모든 숫자는 layer(ACTUAL/DERIVED/ASSUMPTION/REPORT/META) 라벨 + provenance 필수.
- 기존 대시보드(`반도체_메모리_대시보드/index.html`)는 **사용자 명시 요청 전까지 무수정**.
  DS 주입은 프로토타입(`data_sources/prototypes/DS_hook_prototype.html`)에서만 검증.

---

## 1. 디렉터리 맵 (`data_sources/`)

```
data_sources/
  .env                     # OPENDART_API_KEY, SEC_EDGAR_USER_AGENT  (gitignore, 절대 커밋/출력 금지)
  .env.example
  .gitignore
  config/data_sources.json # providers 설정 + covered[] (slug·market·sec_cik·dart_corp_code·bigdata_entity_id)
  run_sync.py              # 오케스트레이터: collect→validate→append→record_health→(actual면) derive
  build_dashboard_data.py  # store → var DS / var ACTUAL / var HEALTH / var SRC  (마커 주입, --check 는 미수정)
  migrate_inline_to_store.py  # 기존 index.html var MC/CD → 스토어 시드 + metric layer 분리
  common/
    schema.py         # NormalizedRecord (dataclass) + dedup_key() + to_ln_node()
    store.py          # append-only 파일 스토어. save_raw_json / append_normalized / append_archive / parse_dt / record_health
    classification.py # SourceClass·NumberType·priority() + METRIC_CLASS / metric_class()
    actual_metrics.py # ACTUAL_METRICS 레지스트리 + SOURCE_AVAILABILITY (live/maybe/none)
    xbrl_map.py       # metric → SEC us-gaap 후보 태그 / DART IFRS 표준계정 id·계정명
    periods.py        # sec_frame() (start/end 날짜→FY/Q, YTD 제외) · dart_frame() (reprt_code)
    derive.py         # actual → revenue_yoy/qoq·*_margin·eps_yoy·fcf_margin·debt_to_equity (formula+input_ids)
    validation.py     # VALID/WARNING/ERROR/INSUFFICIENT_DATA + reason. 자동 삭제 안 함
    normalization.py · provider.py · retry.py · cache.py
  sec_edgar/{adapter,parser,schema}.py   # 미국: data.sec.gov companyconcept XBRL (키 불필요, UA 필수)
  opendart/{adapter,parser,schema}.py    # 한국: opendart.fss.or.kr fnlttSinglAcntAll (OPENDART_API_KEY)
  bigdata/{adapter,parser,schema}.py     # price/market_cap (브라우저 window.cowork, run_sync 대상 아님)
  hankyung_consensus/ · hankyung_global/ # enabled:false (report/estimate 소스, 이번 범위 제외)
  tests/test_phase_b.py  # 18 테스트 (fixture + live-store)
  store/
    raw/<provider>/*.json        # {_meta:{endpoint,request_urls|corp_code,content_hash,http_status}, data:<원본>}
    normalized/<provider>.jsonl  # NormalizedRecord append-only (sec_edgar, opendart, _migrated)
    derived/<name>.jsonl         # actual_metrics, mc_dashboard(legacy)
    archive/report.jsonl         # target_price·forward eps·optimism_check·cycle_pe (격리, 삭제 안 함)
    source_health.json · sync_state.json · sync.log
  valuation/{__init__,damodaran,recipes,context,__main__}.py   # Phase E1: 업종 기준점(Damodaran) + 업종별 metric recipe selector (계산 없음)
  prototypes/DS_hook_prototype.html      # Phase B actual/provenance 미리보기 (index.html 대체 아님)
```

---

## 2. 계층 (RAW / NORMALIZED / DERIVED / ARCHIVE)

| 계층 | 내용 | 저장 | 식별 |
|---|---|---|---|
| RAW | 외부 API 원본 응답 + 요청 메타 | `store/raw/<provider>/*.json` | `_meta.content_hash` (sha256) |
| NORMALIZED | 공통 스키마로 변환한 **실제 관측/공시값** | `store/normalized/<provider>.jsonl` | `record_id` · `dedup_key()` |
| DERIVED | 대시보드가 actual 로부터 **계산**한 값 | `store/derived/actual_metrics.jsonl` | `is_derived` + `formula` + `input_record_ids` + `calculated_at` |
| ARCHIVE | report/forward/assumption (actual 아님) | `store/archive/report.jsonl` | `deprecated_for_actual_dashboard=true` |

`build_ds()` 의 legacy MC 파생(fv/expret/pup/pe)은 `core_eligible=false` + `validation_status=WARNING(estimate_dependent_input)` 로 표시.

### metric layer 분류 (`common/classification.METRIC_CLASS`)
- **ACTUAL**: price·volume·market_cap · revenue·operating_income·net_income·eps_actual·eps_basic·eps_diluted·shares_outstanding·book_value · cash·debt·total_assets·total_liabilities·equity·inventory · operating_cash_flow·capex · (산업) asp·shipment·capacity
- **DERIVED**: *_yoy·*_qoq·operating_margin·net_margin·fcf_margin·debt_to_equity·trailing_pe·pb·ps·drawdown·volatility · (legacy) mc_fair_value_*·expected_return·p_up·fwd_pe
- **ASSUMPTION**: cycle_pe_mid·wacc·terminal_growth
- **REPORT** (archive): target_price·rating·eps(forward)·optimism_check·regime_*
- **META**: valuation_confidence·data_coverage

---

## 3. NormalizedRecord 핵심 필드 (`common/schema.py`)

```
필수      source·provider·retrieved_at·as_of_date·original_url
분류      source_type(SourceClass)·number_type(FACT/CONSENSUS/MODEL/...)·document_type
대상      ticker·slug·company_name·market·currency
값        metric·value·unit·period
시간      as_of_date(=재무제표 기준일/period end)·available_date(=filing_date, 분기말 아님)·filing_date·published_at
파생      is_derived·formula·input_record_ids·calculated_at
품질      confidence·validation_status·validation_notes·verification
raw       raw_ref("raw/<provider>/<file>#<fragment>")·raw_value·source_metric(원본 XBRL/계정 태그 — 삭제 금지)
공시메타   fiscal_year·fiscal_period·original_period·form·filing_date·accession(SEC accession / DART rcept_no)·fs_div(CFS|OFS)·revision_status
격리       deprecated_for_actual_dashboard
식별       record_id ("rec_" + uuid12)
```

`dedup_key()` = sha1(provider·original_url·accession·title·date·broker·ticker·metric·source_metric·period·fiscal_year·fiscal_period·fs_div) — record_id 만 달라도 같은 논리적 fact.

**Provenance chain (검증됨):**
```
dashboard node → record_id → raw_ref → accession → original_url(filing index) → RAW file(_meta.content_hash + 원 API URL)
```

---

## 4. Provider 별 규칙

### SEC EDGAR (`sec_edgar/`)
- 엔드포인트: `https://data.sec.gov/api/xbrl/companyconcept/CIK{10}/us-gaap/{tag}.json` (키 불필요, `SEC_EDGAR_USER_AGENT` 필수)
- CIK: config `covered[].sec_cik` (Micron `0000723125`, SanDisk `0002023554`)
- period: fact 의 `fy/fp` 무시(보고서 기준) → `start/end` 날짜로 도출. 분기(~90d)/연간(~365d), YTD(누적) 제외
- restatement: 같은 period 다중 filing 전부 보존, 최신 `filed` = `revision_status:"latest"`
- CLI: `python -m data_sources.sec_edgar.adapter --all` / `--rebuild`(스토어 초기화 후 재수집; SEC facts 결정적) / `--resolve-cik MU SNDK`

### OpenDART (`opendart/`)
- 엔드포인트: `https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json` (`OPENDART_API_KEY` 필요)
- corp_code: config `covered[].dart_corp_code` (삼성 `00126380`, SK `00164779`)
- reprt_code → `as_of_date`: 11013→YYYY-03-31 · 11012→YYYY-06-30 · 11014→YYYY-09-30 · 11011→YYYY-12-31
- `filing_date`=`available_date` = `rcept_no[:8]` (YYYY-MM-DD) · `accession` = rcept_no · `original_url` = `dart.fss.or.kr/dsaf001/main.do?rcpNo=`
- 연결(CFS) 우선, 없으면 별도(OFS) fallback → `missing` note
- account: `account_id`(IFRS 표준계정 `ifrs-full_*`) 우선, 없으면 `account_nm`. 불확실 시 `uncertain_account_mapping` → validation WARNING
- **보안**: `adapter._scrub(text, key)` 가 로그·예외·health 에서 키와 인증키 파라미터 값 마스킹
- CLI: `python -m data_sources.opendart.adapter --all` / `--resolve-corp 005930 000660`

### Source priority (`classification.priority()`)
`PRIMARY_OFFICIAL`(SEC/DART) > `PROFESSIONAL_LICENSED` > `SECONDARY_PROFESSIONAL` > `MARKET_DATA`(bigdata) > `AI_DERIVED`.
같은 priority → 최신 `filing_date` → 최신 `retrieved_at` (**실제 datetime**, `store.parse_dt()`. 문자열 길이 비교 금지).
값 평균 금지 — preferred + `alt_sources`.

---

## 5. 실행 커맨드

> 전부 **프로젝트 루트**에서 실행 (`python -m data_sources.*`). `data_sources/` 안에서 실행 시 `ModuleNotFoundError`.
> Python 3.14 · **pytest 없음** → 테스트는 내장 `_run()` 러너.

```bash
# 미국 (키 불필요)
python -m data_sources.sec_edgar.adapter --all            # 또는 --rebuild
# 한국 (data_sources/.env 에 OPENDART_API_KEY 필요)
python -m data_sources.run_sync --provider opendart               # TTL(update_policy_sec) 존중 — fresh 면 SKIPPED
python -m data_sources.run_sync --provider opendart --force       # TTL 무시 강제 (실 API ~23s)
python -m data_sources.run_sync --provider opendart --dry-run     # 외부 저장 전무 (raw/normalized/derived/state/health/log)
python -m data_sources.run_sync --all --force-derived             # 신규 actual 없어도 actual derived 재계산
# 대시보드 데이터 빌드 (파일 미수정)
python -m data_sources.build_dashboard_data --check
python -m data_sources.build_dashboard_data --emit-block          # 주입용 JS 블록만 파일로 (store/dashboard_snapshot/ds_block.js), index.html 미수정
# 프로토타입 재생성 (Phase C: 고정 스크립트)
python -m data_sources.prototypes.build_ds_prototype             # → prototypes/DS_hook_prototype.html
# valuation 업종 기준점 / recipe (Phase E1, 파일 미수정)
python -m data_sources.valuation.context --check      # covered 4개의 업종→benchmark→recipe 매핑 표
python -m data_sources.valuation --check              # 위와 동일
python -m data_sources.valuation.damodaran --list     # Damodaran 업종 54개
python -m data_sources.valuation.recipes --list       # recipe 7종
# 테스트
python -m data_sources.tests.test_phase_b     # 18
python -m data_sources.tests.test_phase_c     # 15
python -m data_sources.tests.test_phase_d     # 26
```

---

## 6. 현재 데이터 상태 (2026-08-28)

| Store | Records | 대상 |
|---|--:|---|
| `normalized/sec_edgar.jsonl` | 2,444 | Micron·SanDisk (14 metric, FY2009→2026Q3) |
| `normalized/opendart.jsonl` | 336 | 삼성·SK하이닉스 (12 metric/사, CFS, 2023→2026반기) |
| `normalized/_migrated.jsonl` | 4 | price (bigdata 스냅샷 2026-08-21) |
| `derived/actual_metrics.jsonl` | 911 | micron 578·sandisk 85·samsung 124·skhynix 124 |
| `derived/mc_dashboard.jsonl` | 20 | legacy MC 파생 (core_eligible=false) |
| `archive/report.jsonl` | 21 | target_price·eps(fwd)·optimism_check·cycle_pe |

RAW: `raw/sec_edgar/concepts_{micron,sandisk}_2026-08-28.json` · `raw/opendart/statements_{samsung,skhynix}_2026-08-28.json` (~1.8MB, `_meta.content_hash`, `_redact_meta` 적용)
주입 블록: `store/dashboard_snapshot/ds_block.js` (`--emit-block` 산출, ~259KB, secret CLEAN, index.html 미주입)

**Source Health**: `sec_edgar` HEALTHY (2,444 fetched, 재sync 0 new / 2,444 dup) · `opendart` HEALTHY (336 fetched/added, 0 fail)

**build_dashboard_data --check**: `var DS` 56 노드 · `var ACTUAL` 4종목
(micron/sandisk 24 metric [INCOME 5·BS 7·CF 2·DERIVED 9·PRICE 1] · samsung/skhynix 22 metric [INCOME 4·BS 6·CF 2·DERIVED 9·PRICE 1])

**Tests**: `python -m data_sources.tests.test_phase_b` → **18 passed / 0 failed**
- fixture: schema 왕복·dedup 멱등·priority·datetime 선택(문자열 길이 아님)·parse_dt·validation(null/neg/NaN/derived 완전성/provenance 완전성)·극단변화 WARNING
- live: SEC/OpenDART records exist(비면 fail)·provenance complete(raw 파일 실존·`_meta.content_hash`·`data.results`)·derived formula+inputs·forward/report DS core 제외·archive 격리·health enum·**index.html 무변경**

**샘플 값 (삼성 2026 반기, DART CFS)**: revenue 171.5조 · operating_income 89.5조 · net_income 71.6조 · eps_actual 10,849원 · equity 579.3조 — 전부 `filing_date=2026-08-14`·`as_of_date=2026-06-30`·`VALID`
※ 반기 손익은 누적치 → parser `cumulative` 플래그. 분기 환산 파생은 Phase C.

**검증 상태 분포 (SEC)**: 2,314 VALID / 130 WARNING (41 restated + 89 메모리 super-cycle 극단변화) / 0 ERROR — 삭제 안 함, 표시만.

---

## 7. 보안

- API 키는 `data_sources/.env` 에만. **루트 `.gitignore` 신규** (`data_sources/.env`, `*.env`, `**/.env`, `!.env.example`, `store/`) + 기존 `data_sources/.gitignore` 유지. 프로젝트는 git repo 아님.
- `store/` 전체·`sync.log`·`source_health.json`·`sync_state.json`·프로토타입·README 키 스캔 **CLEAN (0건)**. 실제 키는 `data_sources/.env` 한 곳에만 존재. 시작 시 `rg` 로 노출 스캔하되 매칭된 키 문자열은 어디에도 재기재 금지.
- OpenDART raw `_meta` → `store._redact_meta()` 가 저장 직전 인증키 파라미터/키 포함 URL → `[REDACTED]` (완전 재귀). 허용 키: `endpoint,ticker,corp_code,fs_div,years_back,reprt_codes,http_status,result_count,retrieved_at,content_hash,provider`.
- OpenDART 로그/예외/health/traceback → `opendart.adapter._scrub()` 로 키·인증키 파라미터 값 마스킹.
- `build_dashboard_data._assert_no_secret()` — 주입 블록/emit 파일/프로토타입 blob 에 secret 패턴 있으면 `SystemExit`. `prototypes/build_ds_prototype.py` 도 동일 가드 + `opendart.fss.or.kr/api` 문자열 차단.
- `sync_state.<p>.blocked` 는 키가 아니라 **env 변수 이름**(`"OPENDART_API_KEY"`) — `--force` 성공 시 `null` 로 해제됨.
- 키 값은 문서·리포트·터미널 출력에 절대 미기재.

---

## 8. Phase C — 완료 (2026-08-28)

**증분 동기화 / TTL** (`run_sync.py`)
- `_ttl_skip(key, pconf, force)`: `config.providers.<p>.update_policy_sec`(초) 안 && not `--force` → `{"skipped":"ttl_fresh", age_sec, ttl_sec}` 반환, **외부 호출 없음**. 판단은 `sync_state.<p>.last_successful_sync` 실제 datetime 비교.
- `sync_provider()` → `store.set_dry_run(dry)` 감싸고 `_ttl_skip` → `_do_sync`. `_do_sync` 안에서 `append_normalized`/`record_health`/`update_sync_state` 는 dry-run 시 **no-op** (append 는 '신규 건수'만 계산해 반환).
- 새 플래그: `--force`(TTL 무시) · `--force-derived`(신규 actual 없어도 derive 재계산) · 기존 `--dry-run` 강화.
- derive 재계산 조건: `ran_actual`(신규 actual) or `--force-derived`, **and not dry-run**.
- append-only dedup 유지 — `--force` 재수집 336건 전부 `duplicates`, normalized 증가 0.

**source_health enum 통일**: `HEALTHY / WARNING / ERROR / NOT_CONFIGURED / SKIPPED` (`store.record_health` docstring+로직에 `SKIPPED` 추가, `ok` 판정에서 실패 아님). TTL skip → `SKIPPED` + `sync_state.last_skipped_at`/`last_skip_reason="ttl_fresh"`, `last_successful_sync` **보존**. 키 없음 → `NOT_CONFIGURED` 유지.

**store.py 추가**: `set_dry_run(bool)` + 모듈 `_DRY_RUN` 게이트(모든 writer) · `_redact_meta(meta)` (save_raw_json 이 저장 전 호출).

**build_dashboard_data.py 추가**: `_assert_no_secret()` + `_SECRET_RE` · `_block()` 이 반환 전 스캔 · `--emit-block [PATH]` (주입 블록만 파일로, 기본 `store/dashboard_snapshot/ds_block.js`, `node --check` 통과, index.html 미수정).

**프로토타입 Phase C** (`prototypes/build_ds_prototype.py` 신규 — 임시 스크립트 아님, 고정):
- `build_dashboard_data.build_actual()/build_health()/build_ds()` + `store.get_sync_state()` 재사용 (별도 계산 로직 없음).
- `DS_hook_prototype.html` 덮어씀 (87KB→162KB). `<title>Phase C · Incremental Sync & Provenance`, **§14 Incremental Sync/TTL 패널**(provider status·last success/attempted·last skip·blocked), health 에 `SKIPPED` pill + resp ms.
- Phase B 원본 백업: 세션 스크래치패드 `DS_hook_prototype.PhaseB.bak.html`.
- 검증: secret 스캔 CLEAN · `node --check` PASS · PB blob JSON 파싱 OK (4 slug / 92 metric) · index.html·web_deploy **미수정**.

**tests/test_phase_c.py** (15, 내장 러너) — `.env` 키가 산출물에 미노출 · raw `_meta` 에 인증키 파라미터/키 없음 · `_redact_meta` 동작 · `--dry-run` writer no-op + 파일 카운트 불변 · TTL fresh 시 무네트워크 skip(patch 로 `collect`/`fetch_statements` 호출 시 fail) · `--force` 가 TTL 우회 · append-only dedup · health enum · 주입 블록/프로토타입 secret 없음 · Phase B 회귀. `test_phase_b` 는 enum 허용셋에 `SKIPPED` 추가만 수정.

**검증 결과**: test_phase_b **18/18** · test_phase_c **15/15** · `build_dashboard_data --check` 4종목 actual 정상 · `--dry-run`/plain/`--force`/`--force-derived` 전부 기대대로. 남은 blocker **없음**.

---

## 9. Phase D — 완료 (2026-08-29)

목표는 "운영형 데이터 파이프라인 안정화" — Phase C 의 TTL/보안 기반 위에 **호출 절감**과
**무해 점검 모드**를 얹는다.

**company-level raw cache** (`common/cache.py` + 두 어댑터)
- `stable_key(provider, **parts)` — `json.dumps(sort_keys=True)` → sha256[:32]. 키 계산 **전에**
  secret 계열 필드를 제거하므로 자격증명이 캐시 키·파일명·엔트리 어디에도 섞이지 않는다.
  키 구성: OpenDART = `slug·ticker·corp_code·years_back·reprt_codes·fs_div·기준일`,
  SEC = `slug·ticker·cik·metrics·기준일`.
- 엔트리는 payload 복제가 아니라 **`raw_ref` 포인터**. append-only raw 가 계속 유일 원본이고,
  cache hit 시 `store.load_raw_json()` 으로 되살려 **normalized 를 그대로 재생성**한다
  (SEC 는 `"metric|tag"` 키를 tuple 로 복원).
- `raw_fallback()` — 캐시 디렉터리가 비어 있어도 기존 raw 를 승격. 단 `put(stored_at=…)` 로
  **원본 수집 시각을 유지**한다. 지금 시각으로 쓰면 오래된 스냅샷의 TTL 시계가 리셋돼
  영원히 신선해 보이는 버그가 된다.
- TTL 두 축: `update_policy_sec`(86400, provider 를 얼마나 자주 시도하나) vs
  `raw_cache_ttl_sec`(604800, 받아둔 스냅샷을 얼마나 오래 믿나). 공시 원문은 하루 단위로
  바뀌지 않으므로 후자를 길게 잡는다.
- `--force` 는 **둘 다 우회**한다(재수집이 목적). 단 `--no-network` 와 겹치면 네트워크가
  막혀 있어 cache 가 유일한 경로이므로 계속 사용한다.

**no-network** (`common/netguard.py` 신규)
- `set_no_network(True)` → 어댑터 HTTP 진입점(`sec._get_json` / `dart._get`)이 `guard()` 에서
  `NoNetworkError`. 규약이 아니라 **강제**라 "cache hit 시 무호출"을 테스트로 증명할 수 있다.
- `retry_with_backoff` 는 `NoNetworkError` 를 재시도 대상에서 제외(fail-fast) — 재시도해도
  결과가 같고 백오프만큼 헛되이 기다린다.
- 예외 메시지에는 query 없는 endpoint 이름만 넣는다.
- cache miss + no-network → API 미호출, `blocked` 집계. 전부 blocked → `SKIPPED`,
  일부만 blocked → `WARNING`. 어느 쪽도 `last_successful_sync` 를 앞당기지 않는다.

**재귀 redaction** (`store.redact()`)
- dict/list/tuple/set 임의 깊이(최대 20단) 순회. 컨테이너 종류 유지.
- 필드명이 secret 계열이면 값 통째 `[REDACTED]`. 단독 `key` 는 일반 business 필드일 수 있어
  집합에서 제외 — query string 의 `key=` 만 정규식으로 처리한다.
- URL 은 secret query param 만 치환하고 `corp_code`·`bsns_year`·`fs_div` 등은 보존.
  `monkey=`/`low_key=` 처럼 'key' 를 포함하는 이름은 lookbehind 로 오탐 방지.
- payload 본문은 원본 보존 원칙 때문에 가공하지 않는다. 호출측은 `_meta`·log·health·
  cache entry 처럼 보존 의무가 없는 값뿐.
- `store.log()` 와 `record_health(last_error=…)` 도 redact 를 통과시킨다.

**source_health cache stats** — `cache_hits` · `cache_misses` · `company_count` ·
`skipped_companies` · `no_network_blocked_count`. enum 은 그대로(`CACHE_HIT` 같은 status 신설 안 함),
detail 에 `cache hit=N miss=N blocked=N of N companies` 요약.

**tests/test_phase_d.py** (26, 내장 러너) — 재귀 redaction(중첩 dict/list/tuple/set) ·
비-secret query param 보존 · lookalike 파라미터 오탐 없음 · 캐시 키에 secret 미포함 ·
OpenDART/SEC cache hit 시 HTTP 함수 미호출(패치로 호출 시 즉시 실패) · TTL skip 과 cache hit 구분 ·
netguard 강제 · `--force` 의 cache 우회 · `--dry-run --no-network` 후 store 전체 sha256 불변 ·
health cache stats 존재 · 산출물 secret 스캔 · index.html 미수정 · Phase B/C 회귀.

**검증 결과**: test_phase_b **18/18** · test_phase_c **15/15** · test_phase_d **26/26** ·
`build_dashboard_data --check` 4종목 정상 · `--no-network` 4개 명령 전부 기대대로
(SEC 2,444 / OpenDART 336 레코드를 **네트워크 없이** 재생성, 신규 0 · 전량 dedup).
index.html·web_deploy **미수정**(sha256 불변). 남은 blocker **없음**.

---

## 10. Phase E1 — 완료 (2026-08-30)

Phase E 전체 이름: **Multi-Sector Damodaran-Guided Actual Valuation Engine**.
E1 의 범위는 **업종 기준점(benchmark) 연결 + recipe 결정 기반까지**다.
배수 계산·적정가치 산출은 **하지 않는다** — "이 기업은 어떤 업종 자로 재고, 어떤 metric 을
먼저 볼 것인가"를 확정하는 selector 레이어까지가 E1 의 성공 기준이다.

**전제 3가지 (E2 이후에도 그대로 적용)**

1. **Damodaran 은 정답이 아니라 업종 기준점/가드레일이다.** 개별 기업의 적정가치를 만드는
   입력이 아니라 "우리 숫자가 업종 대비 어디쯤인가"를 재는 자(ruler)다.
   업종 평균 배수를 메모리 peak EBITDA 에 곱하는 식의 사용은 금지 — `usage_rules` 가
   `Benchmark.guardrails()` 로 항상 함께 노출된다.
2. **multi-sector 구조다.** 이 프로젝트는 메모리 기업만 분석하지 않는다. 로더는 54개 업종
   전체를 조회면으로 열어 두고, recipe 는 업종군 단위(반도체·소프트웨어·은행·보험·리츠·에너지)로
   등록한다. covered 가 지금 4개(반도체 편중)인 것은 **데이터 커버리지의 현황**이지
   엔진의 범위가 아니다.
3. **actual valuation input 은 actual 값만.** SEC EDGAR / OpenDART / market data 의 관측·공시
   값만 쓴다. forward estimate·목표주가·컨센서스는 섞지 않는다(§0·§11 원칙 그대로).
   Damodaran 표 안의 `pe_forward` · `exp_growth_5y` · `peg` 도 forecast 파생이므로
   `FORWARD_LOOKING_FIELDS` 로 표시하고 **업종 분위기를 읽는 context 로만** 쓴다.

**파일별 역할** (`data_sources/valuation/`)

| 파일 | 역할 |
|---|---|
| `__init__.py` | 패키지 초기화 + 레이어 원칙(정답 아님 · forward 금지 · 계산 미완) 명시 |
| `damodaran.py` | `학습자료/damodaran_allsectors.json`(sectors 54) + `damodaran_benchmarks.json`(반도체 심화 + `usage_rules`) 로더. `list_industries()` · `resolve_industry()` · `get_benchmark()` · `market_context()` · `usage_rules()` · `Benchmark` dataclass(`to_dict()` / `guardrails()`) · `DamodaranDataMissing` · `FORWARD_LOOKING_FIELDS` |
| `recipes.py` | recipe 7종 레지스트리 + 명시적 패턴 테이블 `INDUSTRY_PATTERNS` + `select_recipe()` / `select_recipe_with_reason()` / `match_industry()` |
| `context.py` | config 의 `covered` → (업종 · benchmark · recipe · 신뢰도 · 경고) 결합. CLI `--check` / `--json` / `--slug` |
| `__main__.py` | `python -m data_sources.valuation --check` → `context.main` 위임 |

`Benchmark` 은 업종명 포함 **18개 필드**를 항상 노출한다(`industry` + `CORE_FIELDS` 17종).
allsectors 원본의 나머지 컬럼(`ev_invcap`·`exp_growth_5y`·`peg`)은 `extra` 로 보존한다.
**누락 필드는 0 이 아니라 `None`** (Missing ≠ 0, §11).
업종을 못 찾으면 **예외가 아니라 `None`** — 호출측이 warning + Default recipe 로 degrade 할 수
있어야 하기 때문이다. 반대로 **파일 자체가 없으면 `DamodaranDataMissing`** — 그건 데이터
부재가 아니라 설정 오류라서 조용히 넘기지 않는다.

**recipe 7종** — "이 업종은 무엇을 먼저 보는가". 계산이 아니라 **선택(selector)** 이다.

| recipe | primary | secondary | warnings | 왜 |
|---|---|---|---|---|
| `Semiconductor` | EV/EBIT · EV/Sales · P/B · ROIC | P/E TTM · EV/FCF · FCF margin | `cyclical_peak` `capex_heavy` `negative_fcf` | 사이클 업종 — peak 이익에 배수 금지, capex/감가 구조상 EBITDA 보다 EV/EBIT |
| `Software` | EV/Sales · FCF margin · revenue_growth | P/E TTM · Rule of 40 | `loss_making` `sbc_heavy` | 회계 적자·현금 흑자 흔함, SBC 제외 시 FCF 과대 |
| `Bank` | P/B · ROE · P/E TTM | dividend_yield | `EV_not_applicable` `credit_cycle` | 부채가 원재료 — EV/EBITDA 계열 무의미, 자기자본 기준 |
| `Insurance` | P/B · ROE · P/E TTM | book_value_growth | `reserve_quality` | 책임준비금 가정이 이익을 좌우, 장부가의 질이 핵심 |
| `REIT` | P/FFO · NAV discount · dividend_yield | debt_to_assets | `EPS_not_primary` | 감가상각이 커서 EPS 가 현금창출력을 과소표시 |
| `Energy` | EV/EBITDA · FCF yield · reserve_life | P/B | `commodity_cycle` | 원자재 가격이 이익 지배 — 스팟 기준 이익에 배수 금지 |
| `Default` | P/E TTM · P/B · EV/EBIT · EV/Sales | ROE · ROIC · FCF margin | `low_sector_specificity` | 업종 특화 recipe 미매치 시 범용 조합 — **업종 특성 미반영 사실을 함께 표시** |

업종 → recipe 는 추론이 아니라 **명시적 패턴 테이블**(`INDUSTRY_PATTERNS`, 위에서부터 첫 매치)이다.
못 찾으면 조용히 추측하지 않고 `Default` + `recipe_fallback_default` 경고로 degrade 한다.
현재 54개 업종 중 13개가 특화 recipe, **41개가 `Default`** — E2 이후 확장 대상(§11-1).

**covered 4개 매핑 결과** (`python -m data_sources.valuation.context --check`)

| slug | industry (primary) | recipe | benchmark | confidence | warnings |
|---|---|---|---|---|---|
| samsung | `Semiconductor` | `Semiconductor` | OK | high | – |
| skhynix | `Semiconductor` | `Semiconductor` | OK | high | – |
| micron | `Semiconductor` | `Semiconductor` | OK | high | – |
| sandisk | `Computers/Peripherals` | `Semiconductor` | OK | **medium** | `ambiguous_industry_mapping` (alt=`Semiconductor`) |

config(`config/data_sources.json`) 는 covered 4개에 `damodaran_industry` **alias** 를 추가했고
기존 `sector_damodaran` 은 하위호환으로 그대로 둔다(`context.pick_industry()` 가 신규 → 기존 순으로 읽음).
sandisk 에만 `damodaran_industry_alt="Semiconductor"` + `_damodaran_note` 를 추가했다.

**SanDisk 판단 근거** — SanDisk 는 NAND 플래시를 직접 설계·생산하는 메모리 기업이다
(Western Digital 에서 분사, Kioxia 와 합작 팹 운영). capex 사이클·웨이퍼 원가·비트 공급
증가율·ASP 변동이라는 **경제적 실질은 Micron/삼성/SK하이닉스와 같은 `Semiconductor`** 쪽에 가깝다.
그런데 **Damodaran 자신의 분류 체계는 WD 계열 스토리지 업체를 `Computers/Peripherals` 로 집계**하고,
벤치마크 숫자(마진·배수)는 그 분류로 집계된 값이다. "Damodaran 표를 읽는다"는 목적에서는
그의 분류를 primary 로 유지하는 것이 정직하다.
→ **config 값(`Computers/Peripherals`)을 primary 로 두고 `Semiconductor` 를 교차검증용 alt 로 병기**한다.
`benchmark` / `benchmark_alt`, `recipe` / `recipe_alt` 를 둘 다 노출하고, 이 모호성 때문에
`mapping_confidence` 를 **medium** 으로 낮춘다. 결론을 낼 때 **어느 쪽 기준인지 반드시 표기**할 것.

**데이터 출처 / 갱신 주기**

- 출처: Aswath Damodaran / NYU Stern (`pages.stern.nyu.edu/~adamodar`)
- `as_of = 2026-01` · **US industry aggregates (USD)** 기준.
- **KR 기업(삼성·SK하이닉스)에 그대로 쓰면 안 된다** — 통화(USD↔KRW)와
  country risk premium(CRP) 조정이 필요하다. 조정 없이 US WACC/배수를 KRW 숫자에 붙이는 것은 오용.
- **연 1회(매년 1월) 갱신 필요.** Damodaran 이 1월에 데이터셋을 갱신하므로,
  `학습자료/damodaran_*.json` 을 그때 다시 받아 `as_of` 를 올린다.
  모든 출력에 `as_of` 를 함께 표시해 스냅샷 시점을 숨기지 않는다.

**실행 / 검증**

```bash
python -m data_sources.valuation.context --check      # covered 매핑 표 (파일 미수정)
python -m data_sources.valuation --check              # 위와 동일
python -m data_sources.valuation.damodaran --list     # 업종 54개
python -m data_sources.valuation.recipes --list       # recipe 7종
```

`context` 출력은 `store.redact()` 를 한 번 통과시킨다(covered 는 원래 secret 을 담지 않지만
출력 경로에서 한 번 더 막는다). `build_dashboard_data --check` 4종목 정상 ·
`index.html` / `web_deploy` **미수정**(sha256 불변).

**남은 것 (Phase E2 후보)** — TTM financials · EV/market cap · actual-only multiples ·
sector benchmark comparison · fair range calculator. → §11-1

---

## 11. Phase E2+ 백로그 (blocker 아님)

### 11-1. Phase E2 후보 (valuation engine 다음 단계)

1. **TTM financials** — 분기 actual 을 굴려 trailing 12M 매출/영업이익/순이익/EPS 를 만든다.
   삼성·SK 는 반기 누적(`cumulative` 플래그)이라 분기 환산이 선행되어야 한다.
2. **EV / market cap** — 시가총액(주가 x 주식수) + 순부채 → EV. actual 입력만 사용.
3. **actual-only multiples** — 위 두 가지로 P/E TTM · P/B · EV/EBIT · EV/Sales 계산.
   forward EPS·컨센서스는 입력에서 제외(archive 격리 유지).
4. **sector benchmark comparison** — 계산된 배수를 recipe 의 primary metric 순서대로
   Damodaran 업종 기준점과 비교(percentile/배율). KR 종목은 통화·CRP 조정 표기 필수.
5. **fair range calculator** — 점 추정이 아니라 **범위**. 정상화(사이클 평균) 이익 기준,
   가정은 전부 ASSUMPTION 레이어로 라벨 + 가드레일 텍스트 동반.
6. recipe 커버리지 확장 — 현재 54개 업종 중 41개가 `Default` 다.
7. Damodaran 스냅샷 **매년 1월 갱신** 루틴화 (`as_of` 갱신 + 회귀 확인).

### 11-2. 데이터/운영 백로그

1. **price·재무 분기 history 축적** → `trailing_pe`·`pb`·`ps`·`drawdown`·`volatility`·`52w high distance` (actual 입력 확보됨, 계산기만)
2. 삼성·SK `eps_actual`/손익 **반기 누적 → 분기 환산** 파생 (`cumulative` 플래그 활용)
3. `market_cap`·`volume` (bigdata 스냅샷 스키마 검증)
4. 산업 actual (ASP·shipment·capacity) — source 미정 (TrendForce 등)
5. restatement **preferred-record 선택 UI** (동일 period 다중 filing)
6. **사용자 승인 시**: `index.html` 에 `var ACTUAL` 렌더 + `LN()` DS 훅 1줄 + `SRC` 참조로 하드코딩 UUID 제거
7. 스케줄러 자동화 (cron / routine)

> ~~company 단위 raw 캐시~~ · ~~`common/cache.py` SEC 경로 연결~~ → **Phase D 에서 완료** (§9)

---

## 12. 원칙 (스펙 요약)

- 실제 실행 결과 > 코드 존재 · 실제 저장 데이터 > adapter skeleton · 원문 추적성 > source label
- forward/target/consensus/optimism 은 actual core 에 혼합 금지 → archive 또는 `core_eligible=false`
- 이상치 자동 삭제 금지 → `VALID/WARNING/ERROR/INSUFFICIENT_DATA` + machine-readable reason
- source 다르다고 자동 평균 금지 → preferred + alternative 보존
- 기존 대시보드/사용자 데이터 삭제 금지 · 대규모 migration 은 plan 먼저
- API key 출력·커밋 금지
