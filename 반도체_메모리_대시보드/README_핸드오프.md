# 반도체·메모리 투자 리서치 대시보드 — 핸드오프

> 이 문서 + `index.html`(+ `data/`, `원본자료/`)만 있으면 어느 기기에서든 이어서 작업 가능.
> **최종 업데이트: 2026-08-21 · 대시보드 버전 v18 · 프레임워크: `semiconductor-ai-investment-research` 스킬(계정 저장).**

## 0. 다른 기기에서 이어서 작업하는 법 (중요)
이 세션은 **로컬 Cowork 세션**(내 PC의 파일·셸에 직접 접근)이라 채팅 자체는 클라우드 동기화가 안 됨. 노트북에서 이어가려면 3개가 필요:
1. **이 OneDrive 폴더** (컨텍스트+대시보드+데이터+원본 PDF) — OneDrive로 자동 동기화됨.
2. **노트북 Claude 데스크톱 앱에 같은 계정 로그인** — 폴더엔 없는 걸 가져옴: 저장된 **스킬**(`semiconductor-ai-investment-research`), **커넥터**(Bigdata.com), 계정에 붙은 **라이브 아티팩트**(`semi-ai-research-dashboard`).
3. 데스크톱 앱에서 **이 폴더로 새 Cowork 세션**을 열고 → "이 핸드오프 읽고 이어서 작업해줘".
→ 실시간 버튼(시세/뉴스/분석)은 **데스크톱 Cowork 전용**. 웹/모바일 브라우저에선 스냅샷 열람만 됨(`window.cowork` 브리지 부재).

## 1. 이 프로젝트가 뭐야
증권사 리포트 숫자를 **그대로 믿지 않고 primitives(출하×ASP)로 재구성·검산**하고, 주가가 이미 요구하는 기대치를 **역산(Reverse DCF)**하며, **확률(Monte Carlo·Bayesian)**로 upside/downside를 평가하는 개인용 리서치 대시보드. 대상: **삼성전자·SK하이닉스·Micron·SanDisk** (HBM/DRAM/NAND 사이클).

## 2. 파일 지도
- `index.html` — 단일 페이지 대시보드(플랫폼 nav: Home·Screener·Memory·Governance·📐설계·Sectors + Memory 하위탭: 개요·MARKET·COMPANY·VALUATION·PROBABILITY·THESIS). 자립형, 브라우저로 바로 열림.
- `data/mc.json` — 4개 기업 Monte Carlo 결과(백분위·확률·히스토그램) + 현재가/EV/기대수익/사이클P·E.
- `data/cdata.json` — 기업별 밸류에이션 football field(`val`) + 재무/과낙관 체크(`fin`: eps·pe27·opt).
- `data/samsung_dcf.json` — 삼성 정식 DCF/Reverse DCF 입력·결과·민감도·검증(Phase A).
- `원본자료/` — 리포트 3종 PDF(키움·삼성·미래에셋). ※ 한화 SanDisk는 캡처만.
- 상위 폴더: `플랫폼_설계서_v1.md`(지배문서) · `데이터계보_감사_설계서_v1.md` · `프로젝트_감사_및_MasterSpec_v1.md`(SSOT) · `검증시스템_설명.md` · `AGENTS.md`(출력위치·스킬 상시적용 규칙) · `web_deploy/`(Vercel 정적본).
- **밸류에이션 툴 종합**: `밸류에이션_툴_종합인덱스_v1.md`(모든 가치평가 도구를 한 눈에·종합 7단계) · `학습자료/`(다모다란 스터디·`damodaran_allsectors.json` 54섹터 벤치마크·`섹터별_밸류에이션_방법지도_v1.md`·`_damodaran_pipeline/` 재생성).

## 3. 실측 데이터 (Bigdata.com, 2026-08-21 기준 스냅샷)
| 기업 | 현재가(스냅샷) | Fwd P/E(27) | MC 기대수익 | P(상승) | 애널 TP |
|---|---|---|---|---|---|
| 삼성전자 | 247,500원 | 3.6x | **+68%** | 82% | 400,000(삼성證) |
| SK하이닉스 | 1,500,000원 | 11.2x | +2% | 52% | 3,000,000(삼성證) |
| Micron | $940.8 | 5.7x | +13% | 64% | — |
| SanDisk | $1,625.8 | 7.3x | +27% | 66% | $2,432.96(한화) |

**컨센서스 EPS(정정본·슈퍼사이클 반영)**: 삼성 26/27/28 = **48,000 / 69,276 / 70,901** · SK = 100,692 / 133,406 / 125,913 · Micron(FY,$) = 65.9 / 163.8 / 173.4 · SanDisk(fwd,$) ≈ 221.7.
※ 실시간 시세 새로고침(🔄)은 `price_performance.current_market.current_price` 경로에서 읽음(v18에서 버그 수정 — 이전엔 0/4 갱신).

## 4. ⚠️ 가장 중요한 히스토리 — 삼성 "슈퍼사이클" 정정(v15)
이전 버전에서 삼성 2026 컨센서스(매출 +119%, 순마진 44%, EPS +615%)를 "불가능/과낙관"으로 **DATA CONFLICT 처리**하고 정규화 DCF로 FV 71k(−71%)를 냈었음. → 오빠 지시로 **TrendForce + Bigdata 분기실적·가이던스 교차검증** 결과, 이게 **내 오류**였음이 드러남: 2026 실적은 실제 슈퍼사이클(2Q26 삼성 OP 89.5조, H1 146.7조; TrendForce DRAM +60% QoQ; DRAM ASP 급등). → EPS/P·E/opt/DCF/Reverse-DCF를 전부 정정. **교훈: 컨센이 "말도 안 되게" 높아도 분기 실적·가이던스로 먼저 교차검증할 것.** samsung_dcf.json의 `data_conflicts`는 옛 판정 기록으로 남아있음(참고용).

## 5. 핵심 결론 (현행 v18)
- **MC 기대수익 순위**: 삼성 +68% > SanDisk +27% > Micron +13% > SK +2%. 삼성이 최상단인 이유 = 피크 EPS(69,276)에 사이클 P/E 평균 6.0x 적용 시 공정가치 ≈416,598원, 현재가 247,500원 대비 큰 갭.
- **삼성 판정 = "실적 검증됨(슈퍼사이클)"** (과거 "과낙관 高"에서 정정). 단 Reverse DCF: 현재가가 요구하는 정상 FCFF ≈ 시장이 과거(~33조)보다 훨씬 높은 지속 FCFF를 요구 → 사이클 지속성이 관건.
- **SanDisk Bayesian**: "이익 구조적(durable)인가" P(사전25%)→**사후 59.5%**, 적정 P/E 7.3→9.0x. 근거 LR = NAND 플로어가격 장기계약·자본환원 클러스터·FY28–30 GM80% 프레임. **주의: 배당 아닌 자사주 → 고점 자사주 가치파괴 위험.**
- **Micron**: 과낙관 아님(멀티플 보수적, EPS 2028까지 상승). **SK**: 대체로 정합, 랠리로 재평가 완료 → 중립.

## 6. 확률(Probability) 산정 기준 — 투명 공개
확률 = ① forward EPS 분포(컨센서스 low/mean/high, **실측**) × ② 사이클 P/E 분포(**주관적 가정**: 삼성6.0·SK11.5·Micron6.5·SanDisk 9.0) 의 Monte Carlo(20,000회). ③ 리포트 과낙관 체크는 각 VALUATION 탭 CHECK 패널에 정성 표기(현재 확률엔 **간접** 반영). SanDisk만 Bayesian으로 ③을 멀티플에 **직접** 반영. Governance: Empirical / Model(MC) / Judgment(Bayesian) 라벨 구분, 혼용 금지.

## 7. v18에서 새로 된 것 (데스크톱 Cowork 전용 기능)
- **🔄 실시간 시세** — Bigdata tearsheet로 4개 종목 현재가 갱신 → cur_pe·기대수익·P(상승) 재계산 후 rerender. (v18 가격 경로 버그 수정)
- **📰 최신 피드** — 모달을 **📑 리포트 / 📰 뉴스 2개 탭으로 분리**. 최근 **2일(D-2)** 이내만. 이 인덱스는 `INVESTMENT-RESEARCH` 타입이 우리 종목 기준 0건이라, NEWS를 가져와 **내용 기반 분류**(증권사명·목표주가·투자의견·애널리스트 등 리서치 신호 → 리포트, 나머지 → 뉴스).
- **🔬 리포트 분석하기** — 리포트 탭 상단 버튼. `askClaude`로 발췌를 우리 방법론(숫자추출·검산·**리포트 간 충돌/괴리 분석**·Assumption Review 후보)으로 1차 분석(Haiku·스니펫 기반). **§Rule3대로 valuation 가정 자동변경 없음.**
- **클릭 데이터 계보** — 핵심 숫자 클릭 → Type/Formula/Inputs/Calc/Source/Why/부모 drill/Full Audit 팝오버.
- **📐설계 탭** — 프롬프트·넘버 검증 방법론 문서화.

## 8. 다음 할 일 (TODO)
- [ ] **SK·Micron·SanDisk 분기실적 교차검증 + 정식 DCF** (현재 삼성만 Phase A 완료; 나머지 컨센서스도 슈퍼사이클일 가능성 재확인 필요).
- [ ] **과낙관 페널티 모드**: 과낙관 高 종목 EPS 분포에 haircut/Bear 확률↑ 직접 반영 옵션.
- [ ] 삼성 HBM4 NVIDIA 퀄 상태 리서치 → 확률/옵션가치 업데이트.
- [ ] 차트(canvas) 클릭 계보 연결(현재 텍스트 숫자만 클릭 가능).
- [ ] 새 리포트 PDF 본문 확보 시 13블록 검산 후 반영(뉴스 발췌보다 깊게).
- [ ] 배포 자동화 결정: Vercel 수동(`npx vercel --prod`) vs Netlify/GitHub 자동배포.

## 9. 배포/동기화 메모
- 정적 웹본: `web_deploy/index.html` → Vercel 수동 배포(`scientific-investment.vercel.app`). Git 미연결이라 업데이트할 때마다 수동 재배포 필요.
- 대시보드 수정 파이프라인: `outputs/semi-dashboard.html` 편집 → `<script>` `node --check` → `update_artifact` → `verify_artifact` → 프로젝트 `반도체_메모리_대시보드/index.html` + `web_deploy/index.html` 복사.
- 원문 URL 차단: einfomax globalmonitor는 web_fetch 차단 → 해외리포트는 이미지 캡처로 판독.

## 10. 데이터 소스
- 실측: Bigdata.com(주가·컨센서스 EPS/EBITDA/PE/PB·tearsheet·search). TrendForce(현물가·수급 교차검증).
- 리포트: 키움(박유악, Memory Split 2027) · 삼성(이종욱, Tech Talk "버틴 자가 먹는 열매") · 미래에셋(김영건, 데이터센터 투자여력) · 한화(박제인, SanDisk Earnings Flash, 캡처).
