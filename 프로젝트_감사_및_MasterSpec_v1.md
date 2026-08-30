# 프로젝트 감사(Audit) & Master Specification — AI주식리서치

> 작성 2026-08-19 · 코드 미수정(audit only) · 대화기록 + 실제 프로젝트 파일 대조.
> 상태표기: **Requested** / **Partially Implemented** / **Implemented** / **Not Implemented**
> 근거: 실제 존재 파일 = `index.html`(대시보드 v9), `mc.json`, `cdata.json`, `AGENTS.md`, `플랫폼_설계서_v1.md`, `데이터계보_감사_설계서_v1.md`, `README_핸드오프.md`, 원본 리포트 3종 PDF, 계정 저장 스킬 `semiconductor-ai-investment-research`.

---

## 1. 핵심 시스템 요구사항 (플랫폼 설계서 §0-1, §37)
| 요구사항 | 상태 | 근거/비고 |
|---|---|---|
| Mission: 시장-내재 기대 vs 증거 지지 미래의 격차 탐색 | **Partially** | Expectations Gap이 1차 근사(MC평균 vs 현재가)로만 존재 |
| Rule 1 — 라벨 분리(FACT/CONSENSUS/MODEL/ASSUMPTION/SCENARIO/IMPLIED/UNVERIFIED/INSUFF.) | **Implemented** | 헤더 범례·Governance 탭·Audit 팝업 배지 |
| Rule 2 — 임의 숫자 금지 / Insufficient Evidence 유지 | **Implemented** | INSUFF. 9곳, 미커버 섹터 빈칸 유지 |
| Rule 3 — News는 valuation 직접 변경 안 함 | **Partially** | 원칙만 명시(Governance/설계서). 뉴스 엔진 부재 |
| Rule 4 — 모든 valuation 변경 추적(prev/new/date/source/reason/confidence/impact) | **Not Implemented** | 앱 내 변경이력·waterfall 없음 |
| 파이프라인(Market→Narrative→Evidence→Probability→…→Ranking) | **Partially** | Narrative/Evidence/Probability 일부, DCF·Reverse·Ranking 미완 |

## 2. Memory Semiconductor Dashboard
| 요구사항 | 상태 | 근거 |
|---|---|---|
| 4개 기업(삼성·SK·Micron·SanDisk) | **Implemented** | cobar 기업선택 |
| 탭 구조(개요/MARKET/COMPANY/VALUATION/PROBABILITY/THESIS) | **Implemented** | mtabs |
| 기업 선택 토글 → 탭 전체 반영 | **Implemented** | 전역 cur |
| 탭 클릭 시 단일 화면만 표시 | **Implemented** | display 직접제어(CSS display:none 미작동 버그 수정) |
| 4기업 비교표 공통(각 탭) | **Implemented** | cmpM/C/V |
| 산업지표(HBM/CoWoS capacity, 빅테크 capex, NAND) | **Implemented** | 차트+KPI |
| 리포트 검산(키움·삼성·미래에셋·한화 SanDisk) | **Implemented** | 매출브릿지·OPM·컨센 2028 피크아웃 |
| 실시간 시세(real-data) | **Implemented** | Bigdata.com 2026-08-19 |
| 단일 페이지 in-place 업데이트 | **Implemented** | 동일 artifact 갱신 |
| 초보 눈높이 설명 | **Implemented** | easy 박스 |

## 3. Cross-sector Screener (플랫폼 설계서 §22-26)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| Screener 랭킹표(현재가/Exp FV/Upside/P(>가)/P(±20)/Gap/Confidence) | **Partially** | Memory 4종만, 타 섹터 INSUFF. |
| 정렬 기준 사용자 변경 | **Not Implemented** | 고정(기대수익 내림차순) |
| 다요소 Opportunity Ranking(Fundamental/Growth/Revision/Industry/Valuation/Gap/Risk) | **Not Implemented** | 현재 기대수익+Confidence만 |
| 구성요소 노출(§25, 블랙박스 금지) | **Partially** | Confidence 표기, 세부 구성요소 분해 미구현 |
| 2nd/3rd-order 수혜주 탐색 | **Not Implemented** | — |
| 20개 섹터 커버리지 | **Not Implemented** | Memory/Storage만 |

## 4. Valuation / DCF / Reverse DCF (§13-15, §18-19)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| 다중 밸류에이션 football field(P/E·Cycle-adj·P/B·Hist·TP·EV/EBITDA) | **Implemented** | 삼성 6방법, SK/Micron/SanDisk 3~4방법 |
| 신뢰도 가중 종합 밴드 | **Implemented** | synth |
| Cycle-adjusted / normalized EPS | **Partially** | football field의 cycle-adj P/E로만 |
| DCF 엔진(Revenue→OP→NOPAT→FCF→WACC→TV→per share) | **Not Implemented** | — |
| Reverse DCF → Market-Implied Expectations | **Not Implemented** | 삼성 정성적 역-밸류 코멘트만 |
| Expectations Gap(정식: market-implied vs evidence model) | **Partially** | 1차 근사(MC평균 vs 현재가), 라벨로 명시 |
| 섹터별 valuation method | **Partially** | Memory only |

## 5. Scenario / Monte Carlo (§8, §16-17, §21)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| Monte Carlo(≥10,000 sims, 백분위, P(>price)/P(±)) | **Implemented** | 20,000회, 4기업, mc.json |
| Distribution integrity(변수 correlation) | **Partially** | SanDisk regime-mixture만, 일반 상관 미반영 |
| Structural Scenario Matrix(Axis A×B) | **Partially** | Home에 Axis A/B 정성 표기, 매트릭스 미구현 |
| Bull/Base/Bear scenario valuation + Expected Value | **Partially** | 초기 명시적 시나리오→현재 MC 분포로 대체 |
| Sensitivity / Tornado | **Implemented** | tornado + audit 팝업 민감도(사이클 P/E 1변수) |
| Decision Tree | **Not Implemented** | — |
| Data Center pipeline(12단계) / China DRAM 시나리오 모듈 | **Not Implemented** | 설계서만 |

## 6. Probability Estimation Protocol (스킬 §7, 플랫폼 §7)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| 8-STEP protocol(Event정의→Base rate→Evidence→Quality→Bayesian→Output→Insufficient→Version) | **Partially** | Bayesian(SanDisk) 완전 실행(prior25→post59.5, LR). 나머지 event에 체계적 미적용 |
| Bayesian update(prior→posterior, LR) | **Implemented** | SanDisk |
| Probability Governance(Empirical/Model/Judgment 구분) | **Implemented** | Governance 탭·팝업 라벨 |
| Base rate 우선 | **Partially** | 대부분 INSUFF.(historical 데이터 부재) |
| 근거없는 numerical prob 금지 | **Implemented** | 원칙 준수 |
| Probability version control(변경 이력) | **Not Implemented** | — |

## 7. News / X Intelligence (플랫폼 §5, §30)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| News Intelligence 탭 + Analyze/Search 버튼 | **Not Implemented** | 앱 내 뉴스 레이어 없음 |
| Event schema(source/author/date/variable/direction/reliability/confirmation) | **Not Implemented** | — |
| Mosaic 분석(중복 원본 제거) | **Partially** | 채팅에서 1회 수행(사용자 제공 제목 리스트), 앱 미탑재 |

## 8. Data Source & Source Hierarchy (§4, §11-15, §19)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| Source Tier A-D 체계 | **Implemented** | Governance 탭 |
| Bigdata.com(주가·컨센서스) | **Implemented** | 실측 08-19 |
| 리포트 4종(키움/삼성/미래에셋/한화) | **Implemented** | 원본자료/ |
| OpenDART / SEC EDGAR 1차 공시 연결 | **Not Implemented** | Governance에 "미연결" 명시(커넥터 필요) |
| Provider adapter 아키텍처(normalized schema) | **Not Implemented** | 설계서만 |
| Consensus vs Actual 분리 저장 | **Partially** | 개념적 분리, DB 미구현 |
| Data Priority Rules 강제 | **Partially** | 문서화(설계서), 코드 강제 없음 |
| Industry Data adapter(DRAM/NAND price 등) | **Not Implemented** | 리포트 인용치만 |

## 9. 숫자 출처 / Data Lineage / Audit Popup (데이터계보 설계서 §1-27)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| Interactive metric → Popup(Type/Formula/Inputs/Calc/Source/AsOf/Confidence) | **Partially** | Probability 탭 KPI 6종만(data-audit 8곳, openAudit) |
| Number type 배지 | **Implemented** | lbc 칩 |
| Source preview(원문 링크 open) | **Partially** | source·asof 표기, "원문/filing 열기" 링크 없음 |
| Calculation Lineage / Dependency Tree | **Not Implemented** | grep Dependency=0 |
| Assumption 팝업 + Sensitivity | **Partially** | 사이클 P/E 1변수 민감도만 |
| Probability 팝업(protocol 전체) | **Partially** | 라벨·note만, 8-step 팝업 아님 |
| Verification status indicator | **Partially** | 팝업 내 표기, 모든 숫자 옆 배지 아님 |
| Source Conflict Detection | **Not Implemented** | — |
| Valuation Confidence / Coverage 점수 | **Partially** | Confidence 카드+팝업, Coverage 팝업 내 언급, 완전 componentized 아님 |
| Audit Valuation 체크리스트 버튼 | **Not Implemented** | — |
| As of / STALE flag | **Partially** | As of 표기, STALE 자동 flag 없음 |
| Missing ≠ 0 | **Implemented** | 원칙 준수(INSUFF.) |

## 10. UI / UX (§30-31)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| 플랫폼 nav(Home/Screener/Memory/Governance/Sectors) | **Implemented** | pnav |
| 탭 단일 화면 전환 | **Implemented** | — |
| Apple-style clean / progressive disclosure | **Partially** | 깔끔한 레이아웃, 드릴다운은 팝업만(Full Audit tree 없음) |
| 숫자 클릭→Calculation/Source/Assumption/Sensitivity/Full Audit | **Partially** | 앞 4개 팝업 통합, Full Audit tree 미구현 |
| 모바일 접근 | **Partially** | OneDrive 동기화 + Netlify 우회. Cowork 아티팩트 자체는 폰 미표시(플랫폼 한계) |
| 초보 눈높이 설명 | **Implemented** | easy 박스 |

## 11. Anti-hallucination / Validation (§33-34, 스킬 §28)
| 요구사항 | 상태 | 근거 |
|---|---|---|
| 10대 금지(임의충전·출처없는 확률/WACC·루머=fact·중복 evidence·현재가 맞춤 조작·기계적 20/60/20·과잉정밀·저confidence 확정표기) | **Implemented(원칙 준수)** | 예: LS증권 데일리 7건→1~2 축약, 확률 근거 명시 |
| Fact/Estimate/Assumption 분리 | **Implemented** | 라벨 체계 |
| Probability governance 3분류 | **Implemented** | — |
| 산출물 검증(JS node --check, verify_artifact) | **Implemented(프로세스)** | 매 배포 전 검증 |
| Kill Conditions / 무효화 조건 | **Implemented** | THESIS 탭 |

## 12. 아직 구현되지 않은 요구사항 (Not Implemented) — 종합
- DCF 엔진, Reverse DCF, 정식 Expectations Gap(market-implied)
- News/X Intelligence 인앱 레이어(탭·버튼·event schema)
- OpenDART·SEC·FMP **provider adapter**, Source Inbox, Add Source, auto cross-check, Source Conflict
- Calculation Dependency Tree / Full Audit tree
- 타 섹터 데이터(20개), 다요소 Opportunity Ranking, 2nd-order 탐색
- Valuation version control / change attribution waterfall (Rule 4)
- Data Center 12단계 파이프라인, China DRAM 시나리오 모듈, Decision Tree
- Audit Valuation 체크리스트 버튼, STALE 자동 flag, Scenario Matrix(Axis A×B)

## 13. 부분적으로만 구현된 요구사항 (Partially) — 종합
Screener(Memory만) · Audit Popup(Probability 탭만) · Expectations Gap(1차 근사) · Scenario(정성 Axis만) · Probability Protocol(Bayesian만) · Valuation Confidence/Coverage(부분 componentized) · Source Hierarchy(문서화, 코드 강제 X) · Progressive disclosure(팝업까지) · Mobile(우회) · Mosaic(채팅 1회).

## 14. 중복 / 충돌하는 요구사항
1. **Home(플랫폼) vs Memory>개요** — 둘 다 4기업 요약(중복). → 개요를 Memory 전용 상세로, Home은 cross-sector 전용으로 역할 분리 권장.
2. **Scenario 방법 전환** — 초기 명시적 Bull/Base/Bear 시나리오 테이블 → 이후 Monte Carlo 분포로 대체. 스펙(§8, §21 EV=Σ scenario×prob)과 현재 구현(MC) **병존 → 혼선 소지**. SSOT에서 "MC를 주(主), 3-시나리오는 MC 백분위(P10/50/90)로 파생" 규칙으로 통일 권장.
3. **"Expectations Gap" 이중 정의** — 설계서(Reverse-DCF market-implied vs evidence) vs 현재(MC평균 vs 현재가). 명칭 충돌 → 현재는 "1차 근사"로 라벨링해 완화, Phase 8에서 정식 교체.
4. **확률 산정 방식** — 스펙은 8-step protocol / 현재는 MC(EPS×P/E). Probability Governance 라벨로 구분했으나 protocol 미이행 → 부분 충돌.
5. **문서 다수** — 스킬(28원칙) / 플랫폼_설계서 / 데이터계보_설계서 / AGENTS.md / README. **우선순위·SSOT 불명확** → 본 Master Spec이 최상위 SSOT.
6. **저장경로 스킬 기본값** — document-output-location의 `C:\Users\eigoo\Documents\Claude_Document` vs 실제 `Admin\OneDrive\문서\Claude\Projects`. → AGENTS.md에서 교정 완료(충돌 해소됨).
7. **모바일 요구 vs 플랫폼 한계** — "모바일에서 개량" 요구 vs Cowork 로컬 아티팩트(데스크톱 전용). → OneDrive+claude.ai 프로젝트 우회로 부분 해소.

---

# MASTER SPECIFICATION (Draft v1) — Single Source of Truth

## M0. 문서 위계 (SSOT)
1. **본 Master Spec** (최상위, 충돌 시 우선)
2. `AGENTS.md` (저장경로·운영규칙)
3. `플랫폼_설계서_v1.md` (플랫폼 비전/Phase)
4. `데이터계보_감사_설계서_v1.md` (Audit/Lineage)
5. 스킬 `semiconductor-ai-investment-research` (분석 방법론 28원칙)

## M1. 목적
시장가격이 내재한 기대 vs 증거가 지지하는 미래의 **격차(Expectations Gap)**가 가장 큰 확률조정 mispricing 종목을 찾는다. 예언이 아니라 **불확실성을 숨기지 않는 구조화된 판단**.

## M2. 현재 범위(Scope)
- **커버리지**: Memory/Storage 4종(삼성전자·SK하이닉스·Micron·SanDisk). 그 외 섹터 = INSUFFICIENT EVIDENCE.
- **데이터**: 실측 = Bigdata.com(주가·컨센서스 EPS/EBITDA/PE/PB, 2026-08-19). 리포트 = 키움·삼성·미래에셋·한화. 1차 공시(OpenDART/SEC) 미연결.

## M3. 아키텍처(현재)
플랫폼 nav = Home · Screener · Memory · Governance · Sectors(roadmap).
Memory = 탭(개요/MARKET/COMPANY/VALUATION/PROBABILITY/THESIS) × 기업선택(4종). 데이터 = `mc.json`(MC), `cdata.json`(val/fin). 단일 self-contained HTML 아티팩트.

## M4. 불변 규칙(Governance) — 위반 금지
- 라벨: FACT/CONSENSUS/MODEL/ASSUMPTION/SCENARIO/IMPLIED/UNVERIFIED/INSUFF.
- 확률 3분류: Empirical / Model / Judgment (혼용 금지).
- Source Tier A-D, Tier C/D 단독 가정변경 금지, Primary filing 우선.
- Anti-hallucination 10대 금지. **Missing ≠ 0**. 근거 부족 = Insufficient Evidence.
- 목표주가·컨센서스 ≠ 진실. 확률엔 근거·종류 표기.
- 모든 배포 전 JS 검증(node --check) + verify_artifact.

## M5. 확정 산정 규칙(충돌 해소)
- **확률의 主 = Monte Carlo**(forward EPS 컨센서스 분포 × 사이클 P/E 분포, 20,000회). Bull/Base/Bear는 MC 백분위(P10/P50/P90)로 파생 표기.
- 사이클 P/E 중앙값(ASSUMPTION): 삼성13 · SK11.5 · Micron6.5 · SanDisk 7→9(Bayesian).
- **Expectations Gap**: 현재 = "MC 기대값 vs 현재가"(1차, 라벨 명시). 정식(Reverse-DCF market-implied) = Phase 8.
- Bayesian(예 SanDisk): prior→posterior + LR, 근거·무효화 명시.

## M6. 현재 상태 요약
- Implemented: Memory 대시보드(4종·탭·비교·real-data), 다중 밸류에이션, Monte Carlo, Bayesian(SanDisk), 라벨/거버넌스, Audit Popup(Probability 탭), Source Tier, THESIS/Kill Conditions.
- Partially: Screener, Expectations Gap, Scenario(정성), Probability Protocol(Bayesian만), Coverage/Confidence, Audit Popup 범위, Mobile.
- Not: DCF/Reverse DCF, News/X, OpenDART/SEC/adapter/Source Inbox, Dependency Tree, 다요소 Ranking·2nd-order, Rule4 version control, Decision Tree/DC pipeline/China 모듈.

## M7. 로드맵(우선순위 제안)
1. **Phase 8 우선 — Reverse DCF → 정식 Expectations Gap**(미션 핵심; 데이터 이미 보유).
2. Audit Popup 전 숫자 확장 + Full Audit 트리.
3. OpenDART/SEC/FMP provider adapter + auto cross-check(**커넥터 필요**).
4. News/X Intelligence(버튼식) + Source Inbox.
5. Cross-sector 데이터 확장 + 다요소 Opportunity Ranking.
6. Rule 4 valuation version control(waterfall).

## M7-A. Phase A 진행 상태 (2026-08-19 업데이트)
- **Implemented**: 삼성전자 정식 DCF 엔진(Revenue→EBIT→NOPAT→FCFF→WACC→TV→EV→Equity→per share, 과거 실적 FACT 기반) · WACC 분해(rf/β/ERP/kd/weights) · TV 비중 · Reverse DCF(현재가→FCFF 10y CAGR 역산, WACC·g 고정) · Formal Expectations Gap(market-implied vs evidence, ≠upside) · 민감도(WACC/g/margin) · Sanity check(A28) · Validation(A27 PASS) · DATA CONFLICT 차단(컨센서스 오염 자동 거부).
- **핵심 검증 결과**: 삼성 현재가 247,500원은 WACC 11.9%·g 2.5% 고정 시 **향후 10년 FCFF CAGR ≈ 28%**를 요구(시장=공격적 업사이클 반영). 정규화 가정 DCF는 FV≈71,000원(−71%, **Low Confidence·REVIEW REQUIRED** — 정규화 마진 14%가 피크 과소반영 가능).
- **Partially**: 감사 팝업은 Probability 탭 KPI + DCF 섹션 인라인. Calculation Trace/Dependency Tree 미구현. Version Control(A21-24) 미구현(스냅샷 samsung_dcf.json만).
- **Not (컨센서스 오염으로 보류)**: SK·Micron·SanDisk DCF → feed sanity check 미통과 위험 → INSUFFICIENT RELIABLE FORECAST 표기. 신뢰 가능한 전망 확보 시 확장.
- **재현성**: `data/samsung_dcf.json` 스냅샷 보존(입력·가정·결과).

## M8. 데이터 최신성
주가·컨센서스: 2026-08-19(Bigdata.com). 리포트: 2026-08. 오래되면 STALE 표기 필요(미구현 → Phase).
