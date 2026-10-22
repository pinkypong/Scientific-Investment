#!/bin/sh
# 클론 직후 이 저장소를 "다른 PC와 같은 상태"로 만든다. 여러 번 실행해도 안전하다.
#
#   sh scripts/bootstrap.sh
#   SKIP_VERIFY=1 sh scripts/bootstrap.sh     # 검증 생략(빠름)
#
# 하는 일: 커밋 훅 활성화 → 파이썬 의존성 → store 재생성(네트워크·키 불필요) → 검증.
# 자격증명은 **점검만** 한다. 어떤 키가 비었는지 이름만 알려주고, 값은 절대 읽거나
# 출력하지 않는다 (docs/workflow.md "절대 금지"). 값은 사람이 직접 채운다.
set -e
cd "$(dirname "$0")/.."

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

step() { printf '\n=== %s ===\n' "$1"; }

# ── 1. 커밋 훅 ────────────────────────────────────────────────────────
# core.hooksPath 는 git 이 동기화하지 않는 클론별 설정이다. 안 하면 pre-commit
# 시크릿 차단이 조용히 비활성된다. 기존 스크립트를 재사용한다.
step "커밋 훅 활성화"
sh scripts/setup-hooks.sh

# ── 2. 파이썬 의존성 ──────────────────────────────────────────────────
step "파이썬 의존성 설치"
echo "현재: $(python --version 2>&1)   (CI 는 3.12 — 크게 다르면 3.12 를 권장)"
python -m pip install --upgrade pip --quiet
python -m pip install -r data_sources/requirements.txt --quiet
echo "data_sources/requirements.txt 설치 완료"

# ── 3. raw mtime 정렬 ─────────────────────────────────────────────────
# Phase D 의 company-level raw cache 는 **파일 mtime** 으로 신선도를 본다
# (raw_cache_ttl_sec = 7일). git 은 mtime 을 보존하지 않으므로:
#   · 갓 클론한 PC  → raw mtime = 체크아웃 시각 = "방금" → cache hit → 테스트 통과
#   · 오래된 작업트리 → raw mtime 이 수십 일 전 → TTL 만료 → blocked
#     → test_phase_d::test_ttl_skip_and_cache_hit_are_distinct 가 깨진다
# 즉 같은 커밋인데도 PC 마다 결과가 달라진다. mtime 을 현재로 맞춰 갓 클론한
# 상태와 같게 만든다. **내용은 건드리지 않는다** (git 은 mtime 을 추적하지 않음).
step "raw 파일 mtime 정렬 (갓 클론한 PC 와 동일하게)"
raw_count=$(find data_sources/store/raw -type f | wc -l | tr -d ' ')
find data_sources/store/raw -type f -exec touch {} +
echo "raw 파일 ${raw_count} 개의 mtime 을 현재로 맞췄다 (내용 변경 없음)"

# ── 4. store 재생성 ───────────────────────────────────────────────────
# 레포에는 store/raw/ 만 들어 있다. normalized·derived 는 아래 한 줄로 복구된다.
step "store 재생성 (네트워크·키 불필요)"
python -m data_sources.run_sync --all --force --no-network --force-derived

# ── 5. 자격증명 점검 — 이름만, 값은 절대 출력하지 않는다 ──────────────
step "자격증명 점검"

ENV_FILE=data_sources/.env
ENV_EXAMPLE=data_sources/.env.example

if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "data_sources/.env 가 없어서 .env.example 을 복사했다."
  echo "→ 편집기로 열어 값을 채운다. 이 파일은 커밋되지 않는다."
fi

# 주석이 아닌 KEY= 줄에서 키 이름만 뽑는다. 값은 흘리지 않는다.
key_names() { sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*=.*/\1/p' "$1" | sort -u; }
# 값이 비어 있지 않은 키 이름만.
filled_keys() { sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*=[[:space:]]*[^[:space:]].*/\1/p' "$1" | sort -u; }
# .env.example 의 자리표시자를 그대로 둔 키. 값이 '있어서' filled_keys 에는 걸리지만
# 실제로는 못 쓴다 (예: SEC_EDGAR_USER_AGENT 의 <CONTACT_EMAIL>). 이름만 뽑는다.
placeholder_keys() {
  sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*=.*\(CONTACT_EMAIL\|여기에_\|<.*>\).*/\1/p' "$1" | sort -u
}

want=$(mktemp); have=$(mktemp)
key_names "$ENV_EXAMPLE" > "$want"
filled_keys "$ENV_FILE" > "$have"
needed=$(comm -23 "$want" "$have")
rm -f "$want" "$have"
placeheld=$(placeholder_keys "$ENV_FILE")

if [ -z "$needed" ] && [ -z "$placeheld" ]; then
  echo "data_sources/.env : .env.example 의 키가 모두 채워져 있다."
fi
if [ -n "$needed" ]; then
  echo "data_sources/.env 에서 비어 있는 키:"
  echo "$needed" | sed 's/^/  - /'
  echo "  발급 경로는 $ENV_EXAMPLE 의 주석 참고. 재생성·테스트에는 없어도 된다."
fi
if [ -n "$placeheld" ]; then
  echo "자리표시자가 그대로인 키 — 실제 값으로 바꿔야 한다:"
  echo "$placeheld" | sed 's/^/  - /'
fi

# VGS 는 .env 를 읽지 않고 셸 환경변수만 본다 — 별도 점검.
if [ -f .secrets.sh ]; then
  echo ".secrets.sh 있음 (VGS 용). 셸에 적용: . ./.secrets.sh"
else
  echo "VGS 실수집을 하려면 .secrets.ps1.example 을 참고해 .secrets.sh 를 만든다."
  echo "  (VGS 는 data_sources/.env 를 읽지 않는다 — 셸 환경변수만 본다)"
fi

# ── 6. 검증 ───────────────────────────────────────────────────────────
if [ -n "$SKIP_VERIFY" ]; then
  echo ""
  echo "SKIP_VERIFY 지정 — 검증 생략."
else
  step "검증 (ci.yml 과 같은 게이트)"
  for phase in b c d e1 e2; do
    echo "--- test_phase_$phase"
    python -m "data_sources.tests.test_phase_$phase"
  done
  echo "--- build_dashboard_data --check"
  python -m data_sources.build_dashboard_data --check
  echo "--- valuation.context --check"
  python -m data_sources.valuation.context --check
fi

step "완료"
echo "훅·의존성·store 는 다른 PC와 같은 상태다."
echo "남은 것은 자격증명 값뿐 — 위 목록이 비어 있지 않으면 사람이 직접 채운다."
