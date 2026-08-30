# data_sources/ — Financial Data Ingestion Architecture

파일 기반 파이프라인. 설계·감사는 `../데이터소스_아키텍처_리팩터_설계서_v1.md` (Phase 0–2).

```
External Source → Adapter → Parser → Normalization → Validation → Store(append-only JSONL)
                                                                    → build_dashboard_data → 대시보드 인라인(DS/SRC/HEALTH)
```

## 레이아웃
| 경로 | 역할 |
|---|---|
| `common/schema.py` | `NormalizedRecord`(공통 데이터 인터페이스) · `DerivedMetric` · JSON (de)ser · `to_ln_node()` |
| `common/classification.py` | `SourceClass`(PRIMARY_OFFICIAL…) · `NumberType`(FACT/CONSENSUS…) · provider→class · Source Priority |
| `common/normalization.py` | 숫자·통화·기간(FY/Q)·metric 명 정규화. Missing ≠ 0 |
| `common/validation.py` | `validate_record` → VALID/WARNING/ERROR + 사유 (자동 삭제 안 함) |
| `common/retry.py` | `retry_with_backoff` · `RateLimiter` |
| `common/cache.py` | 파일 TTL 캐시 + `stable_key()`(결정적 캐시 키, secret 자동 제외) + `raw_fallback()`(append-only raw 를 캐시로 승격) |
| `common/netguard.py` | `--no-network` 강제 가드. 어댑터 HTTP 진입점이 호출 → 차단 시 `NoNetworkError` |
| `common/store.py` | append-only 스토어("DB") + `sync_state` + `source_health` + `sync.log`. `history()`로 revision/time-series |
| `common/provider.py` | ABC `ResearchReportProvider` / `MarketDataProvider` / `NewsProvider` / `FundamentalProvider` + `register`/`get_provider` |
| `bigdata/` | 가격·컨센서스·피드. **브라우저에서 호출**(window.cowork) → `save_snapshot()`으로 적재. MCP 서버 id = config |
| `hankyung_consensus/` | 국내 증권사 리서치 PDF (requests+bs4). `--dump-html`로 셀렉터 1회 보정 |
| `hankyung_global/` | 해외 종목 예상실적 (Playwright + 세션). 게이트 필드는 `gated_fields`로 표기 |
| `valuation/` | **Phase E1** 업종 기준점 + recipe selector. `damodaran.py`(학습자료 2파일 로더 · `Benchmark`/`guardrails()` · `FORWARD_LOOKING_FIELDS`) · `recipes.py`(recipe 7종 + `INDUSTRY_PATTERNS`) · `context.py`(covered→업종·benchmark·recipe·신뢰도·경고). **계산 없음 — 무엇을 볼지까지만** |
| `config/data_sources.json` | 커버 종목·provider 설정·MCP 서버 id·세션 경로·TTL + `damodaran_industry`(/`_alt`). `data_sources.local.json`이 우선 |
| `store/` | 생성물(append-only). git 미추적 권장 |
| `run_sync.py` | provider별 collect→validate→store→health (Phase 1 수동) |
| `build_dashboard_data.py` | store → `var DS/SRC/HEALTH` 인라인 주입 (index.html + web_deploy). 비파괴 |
| `migrate_inline_to_store.py` | 일회성: 현재 `var MC/CD` → 스토어 시드 |

## 사용 순서
```bash
pip install -r data_sources/requirements.txt      # 수집기 실행 시
playwright install chromium                        # hankyung_global 시

python -m data_sources.migrate_inline_to_store     # 1회: 기존 값 스토어 시드
python -m data_sources.run_sync --provider opendart               # TTL(update_policy_sec) 존중 — fresh 면 skip
python -m data_sources.run_sync --provider opendart --force       # TTL 무시하고 강제
python -m data_sources.run_sync --provider opendart --dry-run     # 외부 저장 없음(raw/normalized/derived/state/health/log)
python -m data_sources.run_sync --all --force-derived             # 신규 actual 없어도 actual derived 재계산
python -m data_sources.run_sync --provider sec_edgar --no-network  # 외부 호출 없음 — TTL skip / company cache hit 만
python -m data_sources.run_sync --provider sec_edgar --no-network --dry-run  # 완전 무해 점검(호출도 저장도 없음)
python -m data_sources.build_dashboard_data --check               # 빌드 미리보기(파일 미수정)
python -m data_sources.build_dashboard_data --emit-block          # 주입용 JS 블록만 파일로 출력(index.html 미수정)
python -m data_sources.build_dashboard_data                       # index.html + web_deploy 주입

python -m data_sources.valuation.context --check   # covered 업종→Damodaran benchmark→recipe 매핑 표(파일 미수정)
python -m data_sources.valuation --check           # 위와 동일
python -m data_sources.valuation.damodaran --list  # Damodaran 업종 54개
python -m data_sources.valuation.recipes --list    # recipe 7종
```

### 증분 동기화 / TTL / 캐시 (Phase C·D)
| 개념 | 위치 | 동작 |
|---|---|---|
| TTL | `config.providers.<p>.update_policy_sec` (초) | `sync_state.last_successful_sync` 기준 age < TTL 이고 `--force` 아니면 **skip** |
| skip 표기 | `source_health.<p>.status = SKIPPED` · `sync_state.last_skipped_at` / `last_skip_reason` | 실패 아님 — `last_successful_sync` 보존 |
| dry-run | `store.set_dry_run(True)` | 모든 writer(no-op). `append_*` 는 '신규 건수'만 계산해 반환 |
| dedup | `store.append_normalized` (append-only) | 중복 수집은 `duplicates` 로만 잡히고 normalized 증가 없음 |
| **company cache** | `config.providers.<p>.raw_cache_ttl_sec` · `common/cache.py` | 종목별 raw 스냅샷이 신선하면 **API 재호출 없이** normalized 재생성. provider TTL 과 별개 축 |
| **no-network** | `common/netguard.py` · `--no-network` | 외부 **호출** 금지. cache miss 는 fetch 대신 `blocked` 보고. 가드는 HTTP 진입점에서 강제 |
| 보안 | `store.redact()` · `opendart.adapter._scrub()` | raw `_meta`·로그·예외·health·캐시엔트리에서 인증키 파라미터/API key 제거(**완전 재귀**). `.env` 는 읽기 전용, 산출물엔 존재 여부만 |

Bigdata 는 브라우저에서:
```js
// index.html — SRC.mcp_server + SRC.ids 로 호출, 응답을 스냅샷 파일로 저장 후:
//   python -m data_sources.bigdata.adapter --snapshot tearsheet_samsung.json --slug samsung
```

## 불변 규칙
- 원본 덮어쓰기 금지 — 갱신 = append.  · 파생/원본 분리(`is_derived`+`formula`+`input_record_ids`).
- 값은 출처까지 역추적(`to_ln_node()` → 대시보드 `DS`).  · Missing ≠ 0 (`None` 유지, confidence 하향).
- fallback 시 metadata 표기(조용한 대체 금지).  · robots/ToS 존중, rate-limit, 종목당 상한.

## 완료 (Phase C)
증분 동기화(sync_state + `update_policy_sec` TTL) · `--force` / `--dry-run` / `--force-derived` ·
append-only dedup 유지 · source_health enum 통일(HEALTHY/WARNING/ERROR/NOT_CONFIGURED/SKIPPED) ·
raw `_meta` secret 방어 · `build_dashboard_data --emit-block`(index.html 미수정) · `tests/test_phase_c.py`.

## 완료 (Phase D)
**company-level raw cache** — `cache.stable_key()`(provider+종목+요청 파라미터+기준일, secret 자동 제외) ·
캐시 엔트리는 payload 복제가 아니라 `raw_ref` **포인터** (append-only raw 가 유일 원본) ·
`cache.raw_fallback()` 로 기존 raw 를 캐시로 승격하되 `stored_at` 은 원본 수집 시각을 유지(TTL 시계 리셋 방지) ·
cache hit 시 normalized 를 그대로 재생성.
**no-network** — `netguard` 가 어댑터 HTTP 진입점에서 강제, `NoNetworkError` 는 재시도 대상 제외(fail-fast).
**재귀 redaction** — `store.redact()` 가 dict/list/tuple/set 임의 깊이를 훑고, URL 은 secret query param 만 치환.
**health cache stats** — `cache_hits` / `cache_misses` / `company_count` / `skipped_companies` /
`no_network_blocked_count` (enum 은 그대로, status 를 새로 만들지 않음).
`tests/test_phase_d.py` (26).

### 세 축의 구분
| 플래그 | 막는 것 | 막지 않는 것 |
|---|---|---|
| `--dry-run` | 외부 **저장** (raw/normalized/derived/state/health/log) | 네트워크 — TTL 만료 + `--force` 면 실제 호출 |
| `--no-network` | 외부 **호출** (cache miss → `blocked`) | 파일 쓰기 — health/state 는 기록됨 |
| `--force` | provider TTL + company cache 둘 다 우회 | — (`--no-network` 와 함께면 cache 는 유일 경로라 계속 사용) |

## 완료 (Phase E1)
**Multi-Sector Damodaran-Guided Actual Valuation Engine** 의 1단계 — **업종 기준점 연결 + recipe 결정 기반까지**.
배수·적정가치 **계산은 아직 없다**(E2).

- `valuation/damodaran.py` — `학습자료/damodaran_allsectors.json`(업종 **54개**) +
  `damodaran_benchmarks.json`(반도체/반도체장비/시장전체 심화 + `usage_rules`) 로더.
  `Benchmark` 은 `industry` 포함 **18 필드**를 항상 노출하고 **누락은 0 이 아니라 `None`**,
  나머지 원본 컬럼은 `extra` 로 보존. 업종 없으면 **예외 아닌 `None`**,
  파일 자체가 없으면 **`DamodaranDataMissing`**(설정 오류는 조용히 넘기지 않는다).
- `valuation/recipes.py` — recipe **7종**(`Semiconductor`/`Software`/`Bank`/`Insurance`/`REIT`/`Energy`/`Default`).
  업종→recipe 는 추론이 아니라 **명시적 패턴 테이블**(`INDUSTRY_PATTERNS`), 미매치는
  `Default` + `low_sector_specificity` / `recipe_fallback_default` 로 **표기하며** degrade.
- `valuation/context.py` — covered → `damodaran_industry`(+`_alt`) · `benchmark`(+`_alt`) ·
  `recipe`(+`_alt`) · `mapping_confidence`(high/medium/low) · `mapping_warnings[]`.
  출력은 방어적으로 `store.redact()` 통과.
- 매핑: samsung·skhynix·micron → `Semiconductor`(OK/high) ·
  sandisk → `Computers/Peripherals`(OK/**medium**, `ambiguous_industry_mapping`, alt=`Semiconductor`).

**전제** — Damodaran 은 **정답이 아니라 업종 기준점/가드레일**이다.
이 엔진은 **multi-sector** 구조이며 메모리 기업 전용이 아니다.
actual valuation input 은 SEC/OpenDART/market data 의 **actual 값만** — forward estimate·목표주가·
컨센서스는 섞지 않는다(`pe_forward`·`exp_growth_5y`·`peg` = `FORWARD_LOOKING_FIELDS` 포함).
스냅샷은 `as_of=2026-01` · **US industry aggregates(USD)** 라 KR 종목은 통화·CRP 조정이 필요하고,
**매년 1월 갱신**이 필요하다.

## 아직 안 한 것 (Phase E2+)
**TTM financials**(삼성·SK 반기누적→분기환산 선행) · **EV / market cap** ·
**actual-only multiples**(P/E TTM·P/B·EV/EBIT·EV/Sales) ·
**sector benchmark comparison**(recipe primary 순 · KR 은 통화·CRP 조정 표기) ·
**fair range calculator**(점 추정 아닌 범위, 가정은 ASSUMPTION 라벨 + 가드레일 동반).
그 밖: recipe 커버리지 확장(54개 업종 중 41개가 아직 `Default`) · Damodaran 매년 1월 갱신 루틴화 /
consensus revision·broker dispersion·news-event 매핑 / 분기 history 축적 → trailing_pe·pb·drawdown /
스케줄러 자동화 / (승인 시) index.html `var ACTUAL` 렌더 + `LN()` DS 훅.
