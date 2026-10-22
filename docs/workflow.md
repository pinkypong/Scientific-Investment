# 개발 워크플로우 — 로컬 개발 → GitHub CI/CD

> 배경: GitHub Codespaces 에서 작업하려 했으나 **로컬 머신의 아웃바운드 네트워크가 차단**되어
> (`PermissionError 10013`) Codespace 도 실패. 그래서 개발·테스트는 로컬에서 오프라인으로,
> 커밋·푸시·CI/CD 는 GitHub 에서 하는 모델을 쓴다.

## 한눈에

| 하는 일 | 어디서 | 네트워크 | 시크릿 |
|---|---|---|---|
| 코드 작성, 테스트, `--check` 빌드 | **로컬** | 불필요 (`--no-network`) | 불필요 |
| `git commit` / `git push` | **로컬 CLI** → **기능 브랜치**(`main` 직접 push 금지) | git 만 | 불필요 |
| 테스트·빌드 검증 (`ci.yml`) | GitHub Actions (PR) | 불필요 | **불필요** |
| 시크릿 스캔 (`secret-scan.yml`) | GitHub Actions (PR) | 액션이 처리 | 불필요 |
| 라이브 공시 동기화 (`data-refresh.yml`) | GitHub Actions | 필요 | `OPENDART_API_KEY`, `SEC_EDGAR_USER_AGENT` |
| VGS 미국 데이터 수집 (`vgs-collect-us-data.yml`) | GitHub Actions | 필요 | `SEC_USER_AGENT`, `FRED_API_KEY`, `ALPACA_*` |
| **PC 새로 추가** | 로컬 | 불필요 | 값은 사람이 직접 ([아래](#pc-를-새로-추가할-때)) |

로컬은 라이브 동기화(`run_sync` 실수집)를 **못 한다**. 최신 공시 데이터가 필요하면
`data-refresh` 워크플로우를 GitHub 에서 돌린다 → `chore/data-refresh-<날짜>` 브랜치가 생기면
**PR 을 직접 만들어** CI 통과 확인 후 병합하고, 로컬에서 `git pull` →
`run_sync --all --force --no-network --force-derived` 로 재생성한다.

## 로컬 루프

```bash
# 클론 직후 1회 — 훅·의존성·store·검증을 한 번에 (여러 번 실행해도 안전)
sh scripts/bootstrap.sh           # Windows: powershell -File scripts\bootstrap.ps1
                                  # 훅만 따로: scripts/setup-hooks.sh

# 최신 main 에서 기능 브랜치 생성
git switch main && git pull --ff-only origin main
git switch -c feature/<주제>

# raw → normalized/derived 재생성 (네트워크·키 불필요)
python -m data_sources.run_sync --all --force --no-network --force-derived

# 작업 → 검증
for t in b c d e1; do python -m data_sources.tests.test_phase_$t; done   # 18 / 15 / 26 / 43
python -m data_sources.build_dashboard_data --check                      # DS 56 노드
python -m data_sources.valuation.context --check

# 커밋 → 기능 브랜치 push (pre-commit 훅이 시크릿/쓰레기 raw 를 차단)
git add -A && git commit -m "..."
git push -u origin feature/<주제>
# → GitHub 에서 PR 생성 → CI·secret-scan·Vercel Preview 통과 → 사용자 승인 → main 병합
```

Windows 콘솔은 `PYTHONUTF8=1` 필요 (`bootstrap` 이 자동으로 설정한다).

## PC 를 새로 추가할 때

두 대 이상에서 같이 작업하면 **git 이 동기화하지 않는 것들** 때문에 환경이 갈라진다.
순서대로 하면 된다:

```bash
git clone <repo> && cd <repo>
sh scripts/bootstrap.sh           # Windows: powershell -File scripts\bootstrap.ps1
```

그다음 `bootstrap` 이 출력한 **비어 있는 키 목록**을 보고 값을 직접 채운다
(`data_sources/.env`, 필요하면 `.secrets.ps1`). 키 값은 비밀번호 관리자 같은 안전한
경로로 사람이 옮긴다 — 채팅·커밋·이슈에 붙여넣지 않는다.

`bootstrap` 이 맞춰 주는 것 / 못 맞추는 것:

| | 어떻게 |
|---|---|
| 코드·문서·`store/raw/` | git (`pull`) |
| `core.hooksPath` (pre-commit 훅) | **bootstrap** — git 이 동기화하지 않는 클론별 config. 안 하면 시크릿 차단이 조용히 비활성 |
| 파이썬 의존성 | **bootstrap** (`data_sources/requirements.txt`) |
| `store/` normalized·derived·`_cache` | **bootstrap** — raw 에서 재생성 |
| raw 파일 mtime | **bootstrap** — TTL 판정이 mtime 기반이라 오래된 작업트리는 `test_phase_d` 가 깨진다 |
| **자격증명 값** | ✋ 사람이 직접. 커밋 금지 대상이라 자동화 불가 |
| `.claude/settings.local.json` | ✋ 개인 설정 — 의도적으로 다르게 둔다 |
| 최신 공시 데이터 | ✋ 로컬은 아웃바운드 차단 → `data-refresh` 워크플로우를 GitHub 에서 돌린다 |

## 자격증명 세 곳

이름이 비슷해서 헷갈리기 쉽다. **서로 다른 메커니즘**이고 한 곳에 넣으면 다른 곳은 모른다:

| 어디 | 무엇이 읽나 | 키 |
|---|---|---|
| `data_sources/.env` | 파이썬 파이프라인, `scripts/kis_check.mjs` | `OPENDART_API_KEY` · `SEC_EDGAR_USER_AGENT` · `BIGDATA_API_KEY` · `KIS_APP_KEY` · `KIS_APP_SECRET` |
| Vercel 환경변수 | 배포된 `/api/quotes` (`web_deploy/api/quotes.js`) | `ALPACA_API_KEY_ID` · `ALPACA_API_SECRET_KEY` · `KIS_APP_KEY` · `KIS_APP_SECRET` · `KIS_ENV`(`real`\|`mock`) |
| 셸 환경변수 (`.secrets.ps1`) | `value-growth-screener` — **`.env` 를 읽지 않는다** | `SEC_USER_AGENT` · `FRED_API_KEY` · `ALPACA_API_KEY_ID` · `ALPACA_API_SECRET_KEY` |

> ⚠ SEC User-Agent 는 이름이 **두 개**다. `data_sources/` 는 `SEC_EDGAR_USER_AGENT`,
> VGS 는 `SEC_USER_AGENT`. 독립 서브시스템이라 그렇다 — 둘 다 채워야 양쪽이 돈다.

## 브랜치·PR 규칙

- **`main` 에 직접 push 하지 않는다.** 코드 변경은 항상 기능 브랜치.
- 흐름: 기능 브랜치 → push → GitHub PR 생성 → `CI` · `secret-scan` · `Vercel Preview` 통과
  → 사용자 승인 → **사용자가 직접 `Merge pull request`** → 기존 Vercel Git 연동이 Production 자동 배포.
- `data-refresh` 워크플로우도 `main` 이 아니라 `chore/data-refresh-<날짜>` 브랜치로만 push 한다.

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

### `ci.yml` — main 대상 push/PR 마다
`test_phase_{b,c,d,e1}` + `build_dashboard_data --check` + `valuation.context --check`.
전부 오프라인, 커밋된 `store/raw/` 만 사용 → **시크릿 참조 없음**. python 3.12.
`checkout@v6` · `setup-python@v6`.

### `secret-scan.yml` — main 대상 push/PR 마다
`gitleaks/gitleaks-action@v3` 사용. 이 저장소는 **개인 계정 소유 Private** 이라 gitleaks
라이선스가 필요 없다. 루트 `.gitleaks.toml` 자동 인식 (기본 룰셋 + OpenDART 40-hex 룰).
경로 통째 allowlist 는 `data_sources/.env.example` 하나뿐 — raw·대시보드 HTML 안에 실제 키가
들어가면 계속 탐지된다. PR 은 커밋 범위, push 는 히스토리를 스캔.

### `data-refresh.yml` — 매주 일 18:00 UTC(월 03:00 KST) + 수동(`workflow_dispatch`)
1. `run_sync --all --force --force-derived` (온라인, secrets 사용)
2. `source_health.json` 게이트 — `ERROR`/`NOT_CONFIGURED` 면 실패
3. `build --check` + `test_phase_{b,c,d,e1}` 회귀 검사
4. **diff-scope 가드** — `git status` 변경이 전부 `data_sources/store/` 밑이 아니면 push 없이 중단
   (데이터 잡은 코드·`.env`·대시보드를 절대 안 건드린다)
5. `github-actions[bot]` 으로 커밋 → **`chore/data-refresh-<UTC시각>` 브랜치로만 push**.
   `main` 에 직접 커밋하지 않는다. **PR 은 사용자가 직접 생성** (Actions 실행 요약에 compare 링크 출력).

정규화/파생 JSONL 은 `.gitignore` 대상이라 push 되는 브랜치에는 **새 `store/raw/` 스냅샷만** 담긴다.
그 PR 의 `ci.yml` 이 그걸로 오프라인 재생성·검증한다.

## 시크릿 등록 (1회, GitHub 웹)

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| 이름 | 값 | 쓰는 워크플로우 |
|---|---|---|
| `OPENDART_API_KEY` | https://opendart.fss.or.kr 무료 인증키 (40 hex) | `data-refresh` |
| `SEC_EDGAR_USER_AGENT` | `AI Stock Research <실제이메일>` (SEC 정책상 식별 가능해야 함) | `data-refresh` |
| `SEC_USER_AGENT` | 위와 같은 형식. **VGS 용 별도 이름** | `vgs-collect-us-data` |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html (무료) | `vgs-collect-us-data` |
| `ALPACA_API_KEY_ID` · `ALPACA_API_SECRET_KEY` | https://alpaca.markets — 읽기 전용 시세만 쓴다 | `vgs-collect-us-data` |

`ci.yml` · `secret-scan.yml` 은 이 시크릿이 없어도 돌아간다.
`data-refresh.yml` · `vgs-collect-us-data.yml` 만 필요.

## 절대 금지

- `data_sources/.env` · `.secrets.ps1` 커밋. 실제 키는 로컬 파일과 GitHub Actions secret
  (+ Vercel 환경변수) **에만**. `.gitignore` 와 pre-commit 훅이 막지만 커밋 전 `git status` 로 직접 확인.
- 키 값을 문서·리포트·터미널 출력·커밋 메시지에 기재.
- `data-refresh` 잡에서 `store/` 밖 파일 커밋.
- `반도체_메모리_대시보드/index.html` · `web_deploy/index.html` 무단 수정 (사용자 승인 필요).
