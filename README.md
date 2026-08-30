# AI주식리서치

**Multi-Sector Damodaran-Guided Actual Valuation Engine** + 반도체·메모리 리서치 대시보드.

관측·공시된 **actual 값만** 밸류에이션 입력으로 쓴다. forward estimate·목표주가·컨센서스는
`core_eligible=false` 로 격리하고 섞지 않는다. Damodaran 업종 데이터는 정답이 아니라
**기준점/가드레일**이다.

## 클론 직후 (Codespaces 포함)

```bash
pip install -r data_sources/requirements.txt

# raw 에서 normalized/derived 재생성 — 네트워크·API 키 모두 불필요
python -m data_sources.run_sync --all --force --no-network --force-derived
```

레포에는 **`store/raw/`(공시 원문)만** 들어 있고 normalized·derived 는 위 한 줄로 복구된다.
Phase D 의 company-level raw cache + `netguard` 덕분에 외부 호출이 0건이다.

> `raw_fallback` 은 파일 mtime 으로 신선도를 판단하는데 git 은 mtime 을 보존하지 않는다.
> 클론 직후 raw 는 항상 "방금 받은 것"으로 보이므로 재생성은 늘 성공하지만, 그만큼
> `raw_cache_ttl_sec`(7일)이 클론 환경에서는 무의미하다. **최신 데이터가 필요하면**
> `--no-network` 를 빼고 `--force` 로 실수집해야 한다(그때는 키가 필요).

## 확인

```bash
for t in b c d e1; do python -m data_sources.tests.test_phase_$t; done   # 18 / 15 / 26 / 43
python -m data_sources.build_dashboard_data --check                      # DS 56 노드 / 4 종목
python -m data_sources.valuation.context --check                         # covered 4개 업종·recipe 매핑
```

## 자격증명

`data_sources/.env` 는 **커밋되지 않는다**. Codespaces 에서는 Repository secret 으로 넣는다
(Settings → Secrets and variables → Codespaces):

| 이름 | 필요성 |
|---|---|
| `OPENDART_API_KEY` | 한국 공시 **실수집** 시에만. 재생성·테스트에는 불필요 |
| `SEC_EDGAR_USER_AGENT` | SEC 정책상 이름+이메일. 예: `AI Stock Research you@example.com` |

로컬은 `data_sources/.env.example` 을 `.env` 로 복사해 채운다.

## 어디서부터 읽나

1. `AGENTS.md` — 항상 적용 규칙
2. `docs/research/valuation/next-session.md` — 새 세션 시작점 (현재 Phase A~E1 완료)
3. 필요할 때만 `docs/research/valuation/pipeline-spec.md` — 전체 스펙
4. `data_sources/README.md` — 파이프라인 레이아웃·명령

긴 문서를 처음부터 전문 요약하지 말 것. 지금 필요한 부분만 읽는다.

## 레이아웃

| 경로 | 내용 |
|---|---|
| `data_sources/` | 수집·정규화·검증·스토어 파이프라인 (SEC EDGAR · OpenDART) + `valuation/` |
| `data_sources/store/` | append-only 스토어. **원본 덮어쓰기 금지, 갱신 = append** |
| `학습자료/` | Damodaran 업종 데이터(JSON + 생성 파이프라인) · 밸류에이션 스터디 |
| `docs/research/valuation/` | 스펙 · 다음 세션 인계 |
| `반도체_메모리_대시보드/` | 대시보드 `index.html` (승인 없이 수정 금지) |
| `web_deploy/` | 배포용 사본 (동일 파일) |
