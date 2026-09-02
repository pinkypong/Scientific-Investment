# GitHub Actions 기반 데이터 수집 (VGS)

`Scientific-Investment` 저장소를 **실행 호스트로만** 재사용한다. 그 저장소의
Repository Secrets를 워크플로 실행 중에만 주입받아 SEC / FRED / Alpaca 어댑터를
클라우드에서 돌리고, 결과(`data/`)를 artifact로 내려받는다. 로컬에서는 자격증명이
필요 없는 `analyze` / `screen`만 실행한다.

## 격리 보장

| 항목 | 대시보드(기존) | VGS(신규) |
|---|---|---|
| 워크플로 파일 | 기존 그대로 | `.github/workflows/vgs-collect-us-data.yml` |
| 워크플로 name | 기존 그대로 | `vgs-collect-us-data` |
| concurrency group | 기존 그대로 | `vgs-collect-us-data` |
| artifact 이름 | 기존 그대로 | `vgs-data-<mode>-<run_id>` |
| 출력 경로 | 기존 그대로 | `value-growth-screener/data/` (저장소 루트 미사용) |
| 스케줄 | 기존 그대로 | 없음 (수동 dispatch만). VGS 전용 cron이 필요하면 이 워크플로에만 추가 |
| 코드 | 기존 그대로 | `value-growth-screener/` 하위 폴더에 격리 |
| 저장소 쓰기 | 해당 없음 | `permissions: contents:read`, 커밋백 없음 |

두 프로젝트의 분석 파이프라인·산출물은 합치지 않는다. 공유 자원은 **Repository Secrets 값 하나뿐**이다.

## 1회 통합 절차 (로컬에서)

```powershell
# 1. Scientific-Investment 클론 (이미 있으면 생략)
git clone https://github.com/pinkypong/Scientific-Investment.git
cd Scientific-Investment
git switch -c vgs-pipeline

# 2. VGS 프로젝트를 하위 폴더로 복사 (data/ 산출물은 빼고 코드만)
#    Windows 예: robocopy 사용, /XD 로 산출물 폴더 제외
robocopy "C:\Users\eigoo\Documents\Codex\Investment-Report\Value-Growth-Screener" ".\value-growth-screener" /E /XD data\raw data\cache data\normalized data\reports .git __pycache__

# 3. 워크플로를 저장소 루트로 배치 (파일은 반드시 루트 .github/workflows/ 에 있어야 GitHub이 인식)
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Copy-Item ".\value-growth-screener\ci\vgs-collect-us-data.yml" ".\.github\workflows\vgs-collect-us-data.yml" -Force

# 4. 커밋 & 푸시
git add value-growth-screener .github/workflows/vgs-collect-us-data.yml
git commit -m "Add isolated VGS data-collection workflow"
git push -u origin vgs-pipeline
```

> 대시보드 워크플로와 파일명·`name`·concurrency group이 겹치지 않는지 푸시 전 확인한다.

## 2. Secrets 이름 맞추기

워크플로가 참조하는 이름(대소문자 정확히):

| 워크플로 참조 | 용도 | 비고 |
|---|---|---|
| `SEC_USER_AGENT` | SEC EDGAR User-Agent | `"이름 email@example.com"` 형식. 비밀은 아니지만 SEC가 식별 연락처 요구 |
| `FRED_API_KEY` | FRED/ALFRED | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ALPACA_API_KEY_ID` | Alpaca | Key ID |
| `ALPACA_API_SECRET_KEY` | Alpaca | Secret |

저장소 **Settings → Secrets and variables → Actions**에서 이름을 확인한다.
GitHub은 기존 값을 보여주지 않으므로, 이름이 다르면 **삭제 후 올바른 이름으로 재등록**해야 하고
이때 원본 값이 다시 필요하다(Alpaca 대시보드 / FRED 계정에서 재확인 또는 재발급).

기존 대시보드가 다른 이름(예: `ALPACA_KEY`)으로 쓰고 있고 값을 공유만 하고 싶다면,
같은 값을 위 4개 이름으로 **추가** 등록한다(대시보드 시크릿은 그대로 둔다).

## 3. 실행

- **Actions 탭 → vgs-collect-us-data → Run workflow**
  - 처음엔 `mode = smoke` (GOOGL 1종목, 짧은 기간) 로 계정·rate limit·스키마 검증
  - `as_of` 는 기준일(기본 `2026-09-01`)
- CLI로도 가능:
  ```powershell
  gh workflow run vgs-collect-us-data.yml -f mode=smoke -f as_of=2026-09-01
  gh run watch
  ```
- 각 데이터 스텝은 `continue-on-error: true` 라 키 하나가 틀려도 나머지는 진행되고,
  마지막 스텝이 "아무것도 못 받았으면" 실패로 표시한다. 스텝 로그에서 어떤 시크릿이 문제인지 확인.

## 4. Artifact 로컬 반영

```powershell
# 최신 run의 artifact 다운로드 (gh 사용 시)
gh run download -n vgs-data-smoke-<run_id> -D "C:\Users\eigoo\Documents\Codex\Investment-Report\Value-Growth-Screener"
# -> value-growth-screener/data/normalized/*.jsonl 등이 로컬 data/ 에 들어감
```

또는 Actions 실행 페이지 하단 **Artifacts**에서 zip을 받아 `Value-Growth-Screener\` 아래에 풀면
`data\normalized\...` 로 병합된다.

이후 로컬에서 (자격증명 불필요):

```powershell
$env:PYTHONPATH = "src"
# 실데이터로 정규화 입력을 만드는 어댑터 배선은 아직 미구현(핸드오프 §4).
# 현재는 data/normalized 산출물을 직접 점검하거나, inputs/ 수기 입력으로 screen 실행.
python -m vgs.cli screen inputs\*.json --config config/default.json --output ranking.csv
```

## 5. smoke → full 승격

smoke가 3개 스텝 모두 성공하고 `data/normalized`에 파일이 생기면:

```powershell
gh workflow run vgs-collect-us-data.yml -f mode=full -f as_of=2026-09-01
```

full = `GOOGL MRVL MU SNDK ADI NVDA QCOM`, 일봉 `2023-01-01..as_of`, FRED `2020-01-01..as_of` 6개 시리즈.

## 6. (선택) VGS 전용 스케줄

주기 수집이 필요하면 **이 워크플로 파일에만** 추가한다(대시보드 cron과 시간대를 겹치지 않게):

```yaml
on:
  workflow_dispatch:
    # ... 위와 동일 ...
  schedule:
    - cron: "17 6 * * 1"   # 매주 월요일 06:17 UTC (대시보드와 분리된 시각)
```

스케줄 실행은 `inputs`가 없으므로 기본값(`mode=smoke`, `as_of=2026-09-01`)으로 돈다.
고정 `as_of` 대신 실행일 기준이 필요하면 파라미터 해석 스텝에서 `date -u +%F` 로 대체한다.

## 로컬 `.secrets.ps1` 방식

`scripts\run-us-data.ps1` + `.secrets.ps1` 는 오프라인/개인 키 사용 시 대체 경로로 남겨둔다.
GitHub 경로를 쓰는 동안에는 건드리지 않아도 된다.
