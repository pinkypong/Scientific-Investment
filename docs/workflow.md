# 개발 워크플로우 — 로컬 개발 → GitHub CI/CD

> 배경: GitHub Codespaces 에서 작업하려 했으나 **로컬 머신의 아웃바운드 네트워크가 차단**되어
> (`PermissionError 10013`) Codespace 도 실패. 그래서 개발·테스트는 로컬에서 오프라인으로,
> 커밋·푸시·CI/CD 는 GitHub 에서 하는 모델을 쓴다.

## 한눈에

| 하는 일 | 어디서 | 네트워크 | 시크릿 |
|---|---|---|---|
| 코드 작성, 테스트, `--check` 빌드 | **로컬** | 불필요 (`--no-network`) | 불필요 |
| `git commit` / `git push` | **로컬 CLI** → `origin/main` | git 만 | 불필요 |
| 테스트·빌드 검증 (`ci.yml`) | GitHub Actions | 불필요 | **불필요** |
| 시크릿 스캔 (`secret-scan.yml`) | GitHub Actions | 릴리스 다운로드만 | 불필요 |
| 라이브 공시 동기화 (`data-refresh.yml`) | GitHub Actions | 필요 | `OPENDART_API_KEY`, `SEC_EDGAR_USER_AGENT` |

로컬은 라이브 동기화(`run_sync` 실수집)를 **못 한다**. 최신 공시 데이터가 필요하면
`data-refresh` 워크플로우를 GitHub 에서 돌려 새 `store/raw/` 스냅샷을 커밋백받고,
로컬에서 `git pull` → `run_sync --all --force --no-network --force-derived` 로 재생성한다.

## 로컬 루프

```bash
# 클론 직후 1회 — 커밋 훅 활성화
scripts/setup-hooks.sh            # Windows PowerShell: scripts\setup-hooks.ps1

# raw → normalized/derived 재생성 (네트워크·키 불필요)
python -m data_sources.run_sync --all --force --no-network --force-derived

# 작업 → 검증
for t in b c d e1; do python -m data_sources.tests.test_phase_$t; done   # 18 / 15 / 26 / 43
python -m data_sources.build_dashboard_data --check                      # DS 56 노드
python -m data_sources.valuation.context --check

# 커밋 → 푸시 (pre-commit 훅이 시크릿/쓰레기 raw 를 차단)
git add -A && git commit -m "..."
git push origin main
```

Windows 콘솔은 `PYTHONUTF8=1` 필요.

## pre-commit 훅 (`.githooks/pre-commit`)

`git config core.hooksPath .githooks` 로 활성화(위 setup-hooks 스크립트). 스테이징된 blob 을 검사해
아래를 **차단**한다:

1. OpenDART 키로 보이는 문자열 (키 이름 또는 인증키 파라미터 + 40자리 hex), 실제 이메일이 담긴
   `SEC_EDGAR_USER_AGENT=`
2. 경로가 `/.env` 로 끝나는 파일
3. `data_sources/store/raw/` 밑 2KB 미만 파일 또는 `_meta.result_count`/`concept_count == 0`
   (네트워크 실패 스텁 — 2026-08-30 에 실제로 이런 스텁이 커밋 직전까지 갔었다)

확인된 오탐이면 `git commit --no-verify`. 매칭된 문자열은 로그에 찍지 않는다.

## GitHub Actions

### `ci.yml` — push/PR 마다
`test_phase_{b,c,d,e1}` + `build_dashboard_data --check` + `valuation.context --check`.
전부 오프라인, 커밋된 `store/raw/` 만 사용 → **시크릿 참조 없음**. python 3.12.

### `secret-scan.yml` — push/PR 마다
gitleaks 바이너리(릴리스, MIT)를 받아 `gitleaks dir .` (작업 트리) + `gitleaks git .` (전체 히스토리).
`--redact` 로 값 비노출. 룰: 기본 룰셋 + OpenDART 40-hex (`​.gitleaks.toml`). `.env.example` 만 allowlist.

### `data-refresh.yml` — 매주 일 18:00 UTC(월 03:00 KST) + 수동(`workflow_dispatch`)
1. `run_sync --all --force --force-derived` (온라인, secrets 사용)
2. `source_health.json` 게이트 — `ERROR`/`NOT_CONFIGURED` 면 실패
3. `build --check` + `test_phase_{b,c,d,e1}` 회귀 검사
4. **diff-scope 가드** — `git status` 변경이 전부 `data_sources/store/` 밑이 아니면 커밋 없이 중단
   (데이터 잡은 코드·`.env`·대시보드를 절대 안 건드린다)
5. `github-actions[bot]` 으로 커밋 → rebase 후 push (충돌 시 3회 재시도)

정규화/파생 JSONL 은 `.gitignore` 대상이라 커밋백에는 **새 `store/raw/` 스냅샷만** 담긴다.
다음 `ci.yml` 이 그걸로 오프라인 재생성한다.

## 시크릿 등록 (1회, GitHub 웹)

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| 이름 | 값 |
|---|---|
| `OPENDART_API_KEY` | https://opendart.fss.or.kr 무료 인증키 (40 hex) |
| `SEC_EDGAR_USER_AGENT` | `AI Stock Research <실제이메일>` (SEC 정책상 식별 가능해야 함) |

`ci.yml` · `secret-scan.yml` 은 이 시크릿이 없어도 돌아간다. `data-refresh.yml` 만 필요.

## 절대 금지

- `data_sources/.env` 커밋. 실제 키는 로컬 `data_sources/.env` 와 GitHub Actions secret **두 곳에만**.
- 키 값을 문서·리포트·터미널 출력·커밋 메시지에 기재.
- `data-refresh` 잡에서 `store/` 밖 파일 커밋.
- `반도체_메모리_대시보드/index.html` · `web_deploy/index.html` 무단 수정 (사용자 승인 필요).
