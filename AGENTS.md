# AGENTS.md — 항상 적용 규칙 (AI주식리서치)

이 파일의 규칙은 이 프로젝트에서 작업할 때 **항상 우선 적용**한다.

## 1. 저장 위치 (document-output-location)

이 프로젝트는 **OneDrive에서 로컬 개발 저장소로 이관됨(2026-08-30)**. OneDrive 사본은 삭제됨.
**먼저 어디서 돌고 있는지 확인하고** 그 환경의 루트를 쓴다.

| 환경 | 루트 | 용도 |
|---|---|---|
| 로컬 개발 (Windows) | `C:\Users\eigoo\Documents\AI주식리서치` | 코드·데이터·설계문서 등 **모든 개발 작업의 SSOT** |
| GitHub Codespaces / 컨테이너 | 레포 루트 `/workspaces/Scientific-Investment` | 경로 하드코딩 금지, 레포 상대경로. 파이썬은 레포 루트에서 `python -m data_sources.*` |
| OneDrive | `C:\Users\eigoo\OneDrive\문서\Claude\Projects\...` | **최종 리포트·PDF·핸드오프·모바일 열람본만 선택적으로** 복사 (개발 산출물 상시 저장 금지) |

- 로컬 사용자는 `eigoo`. `Documents`(=`C:\Users\eigoo\Documents`)는 OneDrive로 리다이렉트되지 않은 순수 로컬 경로다.
- 기본 작업·커밋은 로컬 저장소에서. GitHub 원격은 `pinkypong/Scientific-Investment`.
- 모바일에서 봐야 하는 완성본만 OneDrive로 내보낸다.
- **개발·테스트는 로컬 오프라인, 커밋·푸시·CI/CD 는 GitHub** — 로컬 머신은 아웃바운드 네트워크가
  차단돼 라이브 동기화(`run_sync` 실수집)를 못 한다. 상세: `docs/workflow.md`.
- 시크릿(`data_sources/.env` 의 `OPENDART_API_KEY`·`SEC_EDGAR_USER_AGENT`)은 **커밋 금지**. 실제
  값은 로컬 `.env` 와 GitHub Actions secret 두 곳에만. 키 값을 출력·문서·커밋 메시지에 기재하지 않는다.
- 클론 직후 `scripts/setup-hooks.sh`(또는 `.ps1`)로 pre-commit 훅을 켠다 — 시크릿·쓰레기 raw 스냅샷 차단.

## 2. 폴더 구조 규칙

작업 단위로 하위 폴더를 만들고 루트에 파일을 흩뿌리지 않는다.
```
Projects\<프로젝트명>\
  └─ <세부주제>\
       ├─ README_핸드오프.md   ← 맥락·데이터·다음 할 일 (이어작업용)
       ├─ <산출물>.html/.md/.docx/.pptx/.xlsx
       ├─ data\                ← json/csv 등 데이터
       └─ 원본자료\             ← 업로드 PDF·캡처·참고자료 원본
```
- 프로젝트/폴더명은 나중에 제목만 봐도 알아볼 수 있게 구체적으로.
- **원본 자료도 함께** 넣어 폴더 하나로 맥락이 복원되게 한다.

## 3. 저장 후

- 완성본만 정리하고, 중간 임시파일은 스크래치패드에서 처리.
- 기존 파일 덮어쓰기 전 사용자 확인. 삭제 권한 없을 수 있음 → 잔여물은 사용자에게 안내.
- 모바일 열람이 필요한 최종본은 그때만 OneDrive로 복사한다.

## 4. 분석 규칙

- 반도체/메모리/AI 종목·리포트 분석은 **semiconductor-ai-investment-research 스킬**(계정 저장, 모바일에서도 작동)의 13블록·검산·확률 프레임워크를 따른다.
- 목표주가·컨센서스는 진실이 아님. 확률은 근거를 밝히고 subjective/frequency를 구분.
