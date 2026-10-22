# 클론 직후 이 저장소를 "다른 PC와 같은 상태"로 만든다. 여러 번 실행해도 안전하다.
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -SkipVerify   # 검증 생략(빠름)
#
# 하는 일: 커밋 훅 활성화 → 파이썬 의존성 → store 재생성(네트워크·키 불필요) → 검증.
# 자격증명은 **점검만** 한다. 어떤 키가 비었는지 이름만 알려주고, 값은 절대 읽거나
# 출력하지 않는다 (docs/workflow.md "절대 금지"). 값은 사람이 직접 채운다.
param([switch]$SkipVerify)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Windows 콘솔에서 한글·UTF-8 깨짐 방지 (docs/workflow.md 요구사항)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

# ── 1. 커밋 훅 ────────────────────────────────────────────────────────
# core.hooksPath 는 git 이 동기화하지 않는 클론별 설정이다. 안 하면 pre-commit
# 시크릿 차단이 조용히 비활성된다. 기존 스크립트를 재사용한다.
Step "커밋 훅 활성화"
& (Join-Path $PSScriptRoot "setup-hooks.ps1")

# ── 2. 파이썬 의존성 ──────────────────────────────────────────────────
Step "파이썬 의존성 설치"
$pyVersion = (python --version 2>&1)
Write-Host "현재: $pyVersion   (CI 는 3.12 — 크게 다르면 3.12 를 권장)"
python -m pip install --upgrade pip --quiet
python -m pip install -r data_sources/requirements.txt --quiet
Write-Host "data_sources/requirements.txt 설치 완료"

# ── 3. raw mtime 정렬 ─────────────────────────────────────────────────
# Phase D 의 company-level raw cache 는 **파일 mtime** 으로 신선도를 본다
# (raw_cache_ttl_sec = 7일). git 은 mtime 을 보존하지 않으므로:
#   · 갓 클론한 PC  → raw mtime = 체크아웃 시각 = "방금" → cache hit → 테스트 통과
#   · 오래된 작업트리 → raw mtime 이 수십 일 전 → TTL 만료 → blocked
#     → test_phase_d::test_ttl_skip_and_cache_hit_are_distinct 가 깨진다
# 즉 같은 커밋인데도 PC 마다 결과가 달라진다. mtime 을 현재로 맞춰 갓 클론한
# 상태와 같게 만든다. **내용은 건드리지 않는다** (git 은 mtime 을 추적하지 않아
# diff 가 생기지 않는다).
Step "raw 파일 mtime 정렬 (갓 클론한 PC 와 동일하게)"
$now = Get-Date
$rawCount = 0
Get-ChildItem "data_sources/store/raw" -Recurse -File | ForEach-Object {
    $_.LastWriteTime = $now
    $rawCount++
}
Write-Host "raw 파일 $rawCount 개의 mtime 을 현재로 맞췄다 (내용 변경 없음)"

# ── 4. store 재생성 ───────────────────────────────────────────────────
# 레포에는 store/raw/ 만 들어 있다. normalized·derived 는 아래 한 줄로 복구된다.
# 네트워크·API 키 모두 불필요 (netguard 가 외부 호출을 막는다).
Step "store 재생성 (네트워크·키 불필요)"
python -m data_sources.run_sync --all --force --no-network --force-derived

# ── 5. 자격증명 점검 — 이름만, 값은 절대 출력하지 않는다 ──────────────
Step "자격증명 점검"

function Get-EnvKeyNames($file) {
    # 주석(#)이 아닌 KEY=... 줄에서 키 이름만 뽑는다. 값은 버린다.
    if (-not (Test-Path $file)) { return @() }
    $names = @()
    foreach ($line in (Get-Content $file -Encoding UTF8)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { $names += $Matches[1] }
    }
    return $names
}

function Get-FilledEnvKeys($file) {
    # 값이 **비어 있지 않은** 키 이름만. 값 자체는 변수에 담지도, 출력하지도 않는다.
    if (-not (Test-Path $file)) { return @() }
    $names = @()
    foreach ($line in (Get-Content $file -Encoding UTF8)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            if ($Matches[2].Length -gt 0) { $names += $Matches[1] }
        }
    }
    return $names
}

function Get-PlaceholderEnvKeys($file) {
    # .env.example 의 자리표시자를 그대로 둔 키. 값이 '있으므로' 위 함수는 채워진 것으로
    # 보지만 실제로는 못 쓴다 (예: SEC_EDGAR_USER_AGENT 의 <CONTACT_EMAIL> — SEC 는
    # 식별 가능한 실제 이메일을 요구한다). 이름만 반환하고 값은 출력하지 않는다.
    if (-not (Test-Path $file)) { return @() }
    $names = @()
    foreach ($line in (Get-Content $file -Encoding UTF8)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            # $Matches 는 다음 -match 에서 덮어쓰이므로 **먼저** 꺼내 둔다.
            $name = $Matches[1]
            $value = $Matches[2]
            if ($value -match 'CONTACT_EMAIL|여기에_|<.*>') { $names += $name }
        }
    }
    return $names
}

$envFile = "data_sources/.env"
$envExample = "data_sources/.env.example"

if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "data_sources/.env 가 없어서 .env.example 을 복사했다." -ForegroundColor Yellow
    Write-Host "→ 메모장으로 열어 값을 채운다. 이 파일은 커밋되지 않는다."
}

$wanted = Get-EnvKeyNames $envExample
$filled = Get-FilledEnvKeys $envFile
$needed = @($wanted | Where-Object { $filled -notcontains $_ })
$placeholder = @(Get-PlaceholderEnvKeys $envFile)

if ($needed.Count -eq 0 -and $placeholder.Count -eq 0) {
    Write-Host "data_sources/.env : .env.example 의 키가 모두 채워져 있다." -ForegroundColor Green
}
if ($needed.Count -gt 0) {
    Write-Host "data_sources/.env 에서 비어 있는 키 ($($needed.Count)개):" -ForegroundColor Yellow
    foreach ($name in $needed) { Write-Host "  - $name" }
    Write-Host "  발급 경로는 $envExample 의 주석 참고. 재생성·테스트에는 없어도 된다."
}
if ($placeholder.Count -gt 0) {
    Write-Host "자리표시자가 그대로인 키 ($($placeholder.Count)개) — 실제 값으로 바꿔야 한다:" -ForegroundColor Yellow
    foreach ($name in $placeholder) { Write-Host "  - $name" }
}

# VGS 는 .env 를 읽지 않고 셸 환경변수만 본다 — 별도 점검.
if (Test-Path ".secrets.ps1") {
    Write-Host ".secrets.ps1 있음 (VGS 용). 셸에 적용: . .\.secrets.ps1" -ForegroundColor Green
} else {
    Write-Host "VGS 실수집을 하려면 .secrets.ps1.example 을 .secrets.ps1 로 복사해 채운다." -ForegroundColor Yellow
    Write-Host "  (VGS 는 data_sources/.env 를 읽지 않는다 — 셸 환경변수만 본다)"
}

# ── 6. 검증 ───────────────────────────────────────────────────────────
if ($SkipVerify) {
    Write-Host "`n-SkipVerify 지정 — 검증 생략." -ForegroundColor Yellow
} else {
    Step "검증 (ci.yml 과 같은 게이트)"
    foreach ($phase in @("b", "c", "d", "e1", "e2")) {
        Write-Host "--- test_phase_$phase"
        python -m "data_sources.tests.test_phase_$phase"
    }
    Write-Host "--- build_dashboard_data --check"
    python -m data_sources.build_dashboard_data --check
    Write-Host "--- valuation.context --check"
    python -m data_sources.valuation.context --check
}

Step "완료"
Write-Host "훅·의존성·store 는 다른 PC와 같은 상태다."
Write-Host "남은 것은 자격증명 값뿐 — 위 목록이 비어 있지 않으면 사람이 직접 채운다."
