# 다음 세션 참고 — AI주식리서치 data_sources

> 갱신: 2026-08-30 · 전체 스펙: `docs/research/valuation/pipeline-spec.md` §9(Phase D)·§10(Phase E1)

## 지금 상태

- **Phase A·B·C·D 완료 · Phase E1 완료.** 남은 blocker 없음.
- test_phase_b **18/18** · test_phase_c **15/15** · test_phase_d **26/26** · test_phase_e1 **43/43**.
  Python 3.14, **pytest 없음** → 내장 `_run()` 러너.
- 모든 명령은 **레포/프로젝트 루트**에서 `python -m data_sources.*`. Windows 콘솔은 `PYTHONUTF8=1`.
- **git repo + GitHub Codespaces 로 이관됨** (2026-08-30). 아래 "Codespace 에서 시작" 참고.

## Phase D 로 바뀐 것 (핵심만)

- **company 단위 raw cache**: `common/cache.py` `stable_key()`(secret 자동 제외) +
  `raw_fallback()`. 엔트리는 `raw_ref` 포인터라 raw 가 유일 원본. cache hit 이면
  API 재호출 없이 normalized 재생성.
- **`--no-network`**: `common/netguard.py` 가 어댑터 HTTP 진입점에서 강제. cache miss 는
  호출 대신 `blocked`. `--dry-run --no-network` = 완전 무해 점검.
- **TTL 두 축**: `update_policy_sec`(얼마나 자주 시도) vs `raw_cache_ttl_sec`(스냅샷을 얼마나
  오래 믿나). `--force` 는 둘 다 우회.
- **`store.redact()`** 완전 재귀(dict/list/tuple/set). URL 은 secret query param 만 치환.
- **health cache stats**: `cache_hits/cache_misses/company_count/skipped_companies/
  no_network_blocked_count`. enum 신설 없음.
- 프로토타입: `python -m data_sources.prototypes.build_ds_prototype` →
  `prototypes/DS_hook_prototype.html` (§D1 Company-level Raw Cache 패널 추가).

## Phase E1 로 바뀐 것 (핵심만)

- 새 패키지 **`data_sources/valuation/`** — Phase E 전체 이름은
  **Multi-Sector Damodaran-Guided Actual Valuation Engine**. E1 범위는
  **업종 benchmark 연결 + recipe 결정까지**, 배수/적정가치 **계산은 아직 없다**.
- `damodaran.py` 학습자료 2파일 로더(업종 54개 + 반도체 심화/`usage_rules`) ·
  `recipes.py` recipe 7종 + 패턴 테이블 · `context.py` covered→context · `__main__.py`.
- **Damodaran 은 정답이 아니라 업종 기준점/가드레일**. `pe_forward`·`exp_growth_5y`·`peg` 는
  forward 파생이라 actual valuation input 금지(context 전용).
- **multi-sector 전제** — 메모리 전용 아님. 지금 54개 중 13개만 특화 recipe, 41개는 `Default`.
- 매핑: samsung·skhynix·micron → `Semiconductor` (benchmark OK / high) ·
  sandisk → `Computers/Peripherals` (benchmark OK, `ambiguous_industry_mapping` /
  **medium** / alt=`Semiconductor`). SanDisk 는 실질은 반도체지만 Damodaran 분류가
  WD 계열 스토리지를 Computers/Peripherals 로 집계 → config 값 primary + Semiconductor alt 병기.
- config `covered` 4개에 `damodaran_industry` alias 추가(기존 `sector_damodaran` 유지),
  sandisk 만 `damodaran_industry_alt` + `_damodaran_note`.
- 데이터 스냅샷 `as_of=2026-01` · **US industry aggregates(USD)** — KR 종목은 통화·CRP 조정 필요.
  **매년 1월 갱신 필요.**

## Codespace 에서 시작

```bash
pip install -r data_sources/requirements.txt
python -m data_sources.run_sync --all --force --no-network --force-derived
```

레포에는 `store/raw/`(공시 원문)와 재생성 불가한 `_migrated.jsonl`·`archive/` 만 들어 있다.
normalized·derived 는 위 한 줄로 복구된다 — **네트워크·API 키 불필요**(Phase D company cache + netguard).
`raw_fallback` 이 파일 mtime 을 보므로, git 이 mtime 을 보존하지 않는 클론 환경에서는 raw 가 항상
신선해 보인다. **최신 데이터가 필요하면 `--no-network` 를 빼고 `--force`** (그때는 키 필요).

## 새 명령

```bash
python -m data_sources.valuation.context --check      # covered 업종→benchmark→recipe 매핑 표
python -m data_sources.valuation --check              # 위와 동일
python -m data_sources.valuation.damodaran --list     # 업종 54개
python -m data_sources.valuation.recipes --list       # recipe 7종
```

## 절대 하지 말 것

- API 키 원문 출력 / `.env` 내용을 보고에 붙여넣기. 실제 키는 `data_sources/.env` 에만.
- `반도체_메모리_대시보드/index.html` · `web_deploy/index.html` 무단 수정 (사용자 승인 필요).
- `store/` 의 raw/normalized/derived 삭제.
- 덮어쓰기 전 먼저 프로토타입으로 보여주고 승인받기.
- **Damodaran 업종 평균을 그 기업의 '적정가치'로 쓰기** — 기준점/가드레일일 뿐이다.
  사이클 peak 이익에 업종 배수를 곱하지 말 것(`Benchmark.guardrails()` 를 항상 함께 읽기).
- **forward/컨센서스/목표주가를 actual valuation input 에 섞기** (`pe_forward`·`exp_growth_5y`·`peg` 포함).
- US aggregate 기준 WACC/배수를 **통화·CRP 조정 없이** KR 종목에 적용.

## 데이터 규모 (변동 없음)

normalized: sec_edgar 2,444 · opendart 336 · _migrated 4 / derived: actual_metrics 911 ·
mc_dashboard 20(legacy) / archive report 21. `--check`: 4종목(micron·sandisk 24 metric,
samsung·skhynix 22 + PRICE), DS 56 노드.

## 다음 후보 (Phase E2, pipeline-spec.md §11-1)

**TTM financials**(삼성·SK 반기누적→분기환산 선행) · **EV/market cap** ·
**actual-only multiples**(P/E TTM·P/B·EV/EBIT·EV/Sales) · **sector benchmark comparison**(KR 은 통화·CRP 표기) ·
**fair range calculator**(점 추정 아닌 범위, 가정은 ASSUMPTION 라벨).
그 밖: recipe 커버리지 확장(41개가 Default) · Damodaran 매년 1월 갱신 루틴화 ·
분기 history → trailing_pe/pb/drawdown · market_cap/volume 스냅샷 · 스케줄러 자동화 ·
(승인 시) index.html 에 `var ACTUAL`+`LN()` 훅 주입.
