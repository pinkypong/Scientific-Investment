"""covered 기업 → valuation context (업종 · Damodaran benchmark · recipe · 신뢰도 · 경고).

config/data_sources.json 의 `covered` 를 읽어 기업마다 다음을 만든다:
  slug, ticker, name, market, currency,
  damodaran_industry           primary 업종 (config 의 damodaran_industry, 없으면 sector_damodaran 폴백)
  damodaran_industry_alt       교차검증용 대체 업종 (있을 때만)
  benchmark / benchmark_alt    Damodaran 업종 기준점 dict (없으면 None)
  recipe                       업종별 metric 우선순위 dict
  mapping_confidence           high | medium | low
  mapping_warnings[]           ambiguous_industry_mapping / benchmark_missing / recipe_fallback_default …

원칙:
- benchmark 가 없다고 죽지 않는다. Default recipe + warning 으로 degrade 하고 그 사실을 표에 남긴다.
- 하위호환: 기존 필드 `sector_damodaran` 은 그대로 읽는다. `damodaran_industry` 는 alias 다.
- 출력에는 secret 이 없어야 한다 — covered 항목은 원래 secret 을 담지 않지만
  방어적으로 store.redact() 를 한 번 통과시킨다.

실행:
  python -m data_sources.valuation.context --check      # covered 매핑 표 (파일 미수정)
  python -m data_sources.valuation.context --json       # 전체 context JSON
  python -m data_sources.valuation --check              # 위 --check 와 동일
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..common import store
from . import damodaran, recipes

_HERE = Path(__file__).resolve().parent
_DS_ROOT = _HERE.parent
_CFG_PATH = _DS_ROOT / "config" / "data_sources.json"

# config 에서 업종을 읽는 순서. 앞이 우선 — damodaran_industry(신규 alias) → sector_damodaran(기존).
INDUSTRY_FIELDS = ("damodaran_industry", "sector_damodaran")
INDUSTRY_ALT_FIELD = "damodaran_industry_alt"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# ── SanDisk 업종 매핑 판단 근거 (코드에 남긴다) ────────────────────────
# SanDisk 는 NAND 플래시를 직접 설계·생산하는 메모리 기업이다(Western Digital 에서 분사,
# Kioxia 와 합작 팹 운영). 경제적 실질 — capex 사이클, 웨이퍼 원가, 비트 공급 증가율,
# ASP 변동 — 은 Micron/삼성/SK하이닉스와 같은 `Semiconductor` 쪽에 가깝다.
# 반면 Damodaran 자신의 분류 체계는 Western Digital 계열 스토리지 업체를
# `Computers/Peripherals` 에 넣는다. 벤치마크 숫자(마진·배수)는 그 분류로 집계된 값이므로,
# "Damodaran 표를 읽는다"는 목적에서는 그의 분류를 primary 로 유지하는 것이 정직하다.
#   → config 의 기존 값(Computers/Peripherals)을 primary 로 두고,
#     Semiconductor 를 damodaran_industry_alt 로 함께 노출해 교차검증한다.
#     이 모호성 때문에 mapping_confidence 는 medium 으로 낮춘다.
AMBIGUOUS_MAPPING_WARNING = "ambiguous_industry_mapping"
DEFAULT_ALT_RATIONALE = (
    "Damodaran 분류(primary)와 사업 실질(alt)이 갈리는 종목이다. 두 업종 벤치마크를 "
    "함께 보고, 결론이 어느 쪽 기준인지 반드시 표기할 것."
)
ALT_RATIONALE = {
    "sandisk": (
        "SanDisk 는 NAND 플래시를 설계·생산하는 메모리 기업(Western Digital 분사, "
        "Kioxia 합작 팹)이라 경제적 실질은 Semiconductor 에 가깝다. 다만 Damodaran 의 "
        "분류 체계는 WD 계열 스토리지 업체를 Computers/Peripherals 로 집계하므로 "
        "config 값을 primary 로 유지하고 Semiconductor 를 교차검증용 alt 로 둔다."
    ),
}


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or _CFG_PATH).read_text(encoding="utf-8"))


def covered(cfg: dict | None = None) -> list[dict]:
    return list((cfg or load_config()).get("covered") or [])


def pick_industry(entry: dict) -> str | None:
    """damodaran_industry(신규) 우선, 없으면 sector_damodaran(기존) 폴백."""
    for f in INDUSTRY_FIELDS:
        v = entry.get(f)
        if v:
            return str(v)
    return None


def build_context(entry: dict) -> dict:
    """covered 항목 하나 → valuation context dict."""
    slug = entry.get("slug") or ""
    warnings: list[str] = []

    industry = pick_industry(entry)
    if not industry:
        warnings.append("industry_not_configured")

    bm = damodaran.get_benchmark(industry) if industry else None
    if industry and bm is None:
        warnings.append("benchmark_missing")

    alt_name = entry.get(INDUSTRY_ALT_FIELD)
    alt_bm = damodaran.get_benchmark(alt_name) if alt_name else None
    if alt_name and alt_bm is None:
        warnings.append("benchmark_alt_missing")

    # recipe 는 benchmark 유무와 무관하게 업종명으로 고른다. 업종을 못 찾으면 Default.
    if bm is not None:
        recipe, why = recipes.select_recipe_with_reason(bm.industry)
    elif industry:
        recipe, why = recipes.select_recipe_with_reason(industry)
    else:
        recipe, why = recipes.get_recipe(recipes.DEFAULT), {
            "industry": None, "matched": False, "pattern": None, "fallback": True}
    if why["fallback"]:
        warnings.append("recipe_fallback_default")

    alt_recipe = recipes.select_recipe(alt_name) if alt_name else None

    # 신뢰도: 기본 high → 대체 업종이 있으면(분류 모호) medium → benchmark 자체가 없으면 low.
    confidence = CONFIDENCE_HIGH
    if alt_name:
        confidence = CONFIDENCE_MEDIUM
        warnings.append(AMBIGUOUS_MAPPING_WARNING)
        warnings.append(ALT_RATIONALE.get(slug, DEFAULT_ALT_RATIONALE))
    if bm is None:
        confidence = CONFIDENCE_LOW

    ctx = {
        "slug": slug,
        "ticker": entry.get("ticker"),
        "name": entry.get("name"),
        "market": entry.get("market"),
        "currency": entry.get("currency"),
        "damodaran_industry": bm.industry if bm is not None else industry,
        "damodaran_industry_alt": alt_bm.industry if alt_bm is not None else alt_name,
        "benchmark": bm.to_dict() if bm is not None else None,
        "benchmark_alt": alt_bm.to_dict() if alt_bm is not None else None,
        "recipe": recipe.to_dict(),
        "recipe_alt": alt_recipe.to_dict() if alt_recipe is not None else None,
        "recipe_match": why,
        "mapping_confidence": confidence,
        "mapping_warnings": warnings,
        "damodaran_note": entry.get("_damodaran_note"),
    }
    # 방어적 redaction — covered 는 secret 을 담지 않지만 출력 경로에서 한 번 더 막는다.
    return store.redact(ctx)


def build_all(cfg: dict | None = None) -> list[dict]:
    return [build_context(e) for e in covered(cfg)]


def benchmark_status(ctx: dict) -> str:
    """표에 찍는 한 단어 상태.  OK / WARNING / MISSING."""
    if ctx.get("benchmark") is None:
        return "MISSING"
    if ctx.get("mapping_warnings"):
        return "WARNING"
    return "OK"


# ── CLI ──────────────────────────────────────────────────────────────
def _short_warnings(ws: list[str]) -> str:
    """표에는 코드성 경고(짧은 토큰)만 찍는다. 근거 문장은 아래 상세에서 보여준다."""
    codes = [w for w in ws if " " not in w]
    return ", ".join(codes) if codes else "-"


def print_check(contexts: list[dict]) -> None:
    mc = damodaran.market_context()
    print(f"valuation context — covered {len(contexts)}개 "
          f"(Damodaran as_of={mc.get('as_of')})\n")
    head = (f"{'slug':<10} {'industry':<24} {'recipe':<14} "
            f"{'benchmark':<9} {'conf':<7} warnings")
    print(head)
    print("-" * len(head))
    for c in contexts:
        print(f"{(c['slug'] or '-'):<10} "
              f"{(c['damodaran_industry'] or '-'):<24} "
              f"{c['recipe']['name']:<14} "
              f"{benchmark_status(c):<9} "
              f"{c['mapping_confidence']:<7} "
              f"{_short_warnings(c['mapping_warnings'])}")

    for c in contexts:
        detail = [w for w in c["mapping_warnings"] if " " in w]
        if c.get("damodaran_industry_alt") or detail:
            print(f"\n· {c['slug']}: alt={c.get('damodaran_industry_alt') or '-'}"
                  f" (alt recipe={(c.get('recipe_alt') or {}).get('name', '-')})")
            for d in detail:
                print(f"    근거: {d}")
            if c.get("damodaran_note"):
                print(f"    config note: {c['damodaran_note']}")

    print("\nrecipe primary metric:")
    for c in contexts:
        print(f"  {c['slug']:<10} {', '.join(c['recipe']['primary'])}"
              f"   | warn: {', '.join(c['recipe']['warnings'])}")
    print("\n주의: Damodaran 값은 정답이 아니라 업종 기준점/가드레일이다. "
          "forward/컨센서스 파생 필드는 actual valuation input 으로 쓰지 않는다.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="covered 기업의 업종 → benchmark → recipe 매핑 점검 (파일 미수정)")
    ap.add_argument("--check", action="store_true", help="매핑 표 출력")
    ap.add_argument("--json", action="store_true", help="전체 context JSON 출력")
    ap.add_argument("--slug", help="특정 기업만")
    a = ap.parse_args(argv)

    contexts = build_all()
    if a.slug:
        contexts = [c for c in contexts if c["slug"] == a.slug]
        if not contexts:
            print(f"WARNING: covered 에 slug={a.slug!r} 없음")
            return 1

    if a.json:
        print(json.dumps(contexts, ensure_ascii=False, indent=2))
        return 0

    print_check(contexts)          # --check 는 기본 동작이기도 하다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
