"""업종별 valuation recipe 레지스트리 — "이 업종은 무엇을 먼저 보는가".

각 recipe 는 세 가지를 갖는다:
  primary    이 업종의 가치를 판단할 때 **중심에 두는** metric.
  secondary  보조 확인용. primary 와 어긋나면 왜 어긋나는지 설명이 필요하다.
  warnings   이 업종에서 흔히 틀리는 지점(사이클 peak, EV 미적용, 적자 등).

설계 원칙:
- 여기는 **선택(selector)** 레이어다. 계산은 하지 않는다. 이 단계의 성공 기준은
  "covered 기업마다 올바른 recipe 가 나온다" 까지다.
- 업종 → recipe 매핑은 추론이 아니라 **명시적 패턴 테이블**(INDUSTRY_PATTERNS)이다.
  Damodaran 업종명(54개)이 입력이며, 못 찾으면 조용히 추측하지 않고
  Default recipe + low_sector_specificity 경고로 degrade 한다.
- recipe 이름은 안정적(stable)이다. 저장물/로그가 이 문자열을 참조하므로 함부로 바꾸지 않는다.

실행:
  python -m data_sources.valuation.recipes --list
  python -m data_sources.valuation.recipes --industry "Bank (Money Center)"
"""
from __future__ import annotations

import argparse
import re
from dataclasses import asdict, dataclass, field

# recipe 이름 상수 — 오타로 조용히 새 recipe 가 생기는 것을 막는다.
SEMICONDUCTOR = "Semiconductor"
SOFTWARE = "Software"
BANK = "Bank"
INSURANCE = "Insurance"
REIT = "REIT"
ENERGY = "Energy"
DEFAULT = "Default"


@dataclass(frozen=True)
class Recipe:
    """업종 하나의 metric 우선순위. 불변 — 레지스트리 객체를 호출측이 수정하지 않게 한다."""

    name: str
    primary: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    note: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)   # 같은 recipe 를 가리키는 다른 이름

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("primary", "secondary", "warnings", "aliases"):
            d[k] = list(getattr(self, k))
        return d


REGISTRY: dict[str, Recipe] = {
    SEMICONDUCTOR: Recipe(
        name=SEMICONDUCTOR,
        aliases=("Semiconductor/Manufacturing",),
        primary=("EV/EBIT", "EV/Sales", "P/B", "ROIC"),
        secondary=("P/E TTM", "EV/FCF", "FCF margin"),
        warnings=("cyclical_peak", "capex_heavy", "negative_fcf"),
        note=("사이클 업종. peak 이익에 배수를 곱하면 과대평가된다 — 정상화(사이클 평균) "
              "이익 기준으로 보고, capex/감가상각 구조 때문에 EBITDA 보다 EV/EBIT 를 앞세운다."),
    ),
    SOFTWARE: Recipe(
        name=SOFTWARE,
        primary=("EV/Sales", "FCF margin", "revenue_growth"),
        secondary=("P/E TTM", "Rule of 40"),
        warnings=("loss_making", "sbc_heavy"),
        note=("회계 적자여도 현금흐름은 흑자인 경우가 많다. SBC(주식보상)를 비용에서 "
              "빼고 보면 FCF 가 과대계상된다."),
    ),
    BANK: Recipe(
        name=BANK,
        primary=("P/B", "ROE", "P/E TTM"),
        secondary=("dividend_yield",),
        warnings=("EV_not_applicable", "credit_cycle"),
        note=("부채가 원재료인 업종 — EV/EBITDA 계열은 의미가 없다. 자기자본 기준(P/B x ROE)으로 본다."),
    ),
    INSURANCE: Recipe(
        name=INSURANCE,
        primary=("P/B", "ROE", "P/E TTM"),
        secondary=("book_value_growth",),
        warnings=("reserve_quality",),
        note="책임준비금 가정이 이익을 좌우한다. 장부가의 질(reserve adequacy)이 핵심 리스크.",
    ),
    REIT: Recipe(
        name=REIT,
        primary=("P/FFO", "NAV discount", "dividend_yield"),
        secondary=("debt_to_assets",),
        warnings=("EPS_not_primary",),
        note="감가상각이 커서 EPS 가 현금창출력을 과소표시한다 → FFO/NAV 로 본다.",
    ),
    ENERGY: Recipe(
        name=ENERGY,
        primary=("EV/EBITDA", "FCF yield", "reserve_life"),
        secondary=("P/B",),
        warnings=("commodity_cycle",),
        note="원자재 가격이 이익을 지배한다. 스팟 가격 기준 이익에 배수를 곱하지 않는다.",
    ),
    DEFAULT: Recipe(
        name=DEFAULT,
        primary=("P/E TTM", "P/B", "EV/EBIT", "EV/Sales"),
        secondary=("ROE", "ROIC", "FCF margin"),
        warnings=("low_sector_specificity",),
        note=("업종 특화 recipe 를 찾지 못했을 때의 범용 조합. 결론에 업종 특성이 "
              "반영되지 않았다는 사실을 반드시 함께 표시한다."),
    ),
}


# ── 업종 → recipe 매핑 (명시적 패턴 테이블) ──────────────────────────
# 키는 Damodaran 업종명을 compact 정규화(소문자·영숫자만)한 문자열에 대한 정규식.
# 위에서부터 첫 매치가 이긴다 — 더 좁은 패턴을 위에 둔다.
#
#   'Semiconductor'                        → semiconductor
#   'Semiconductor Equip'                  → semiconductorequip
#   'Computers/Peripherals'                → computersperipherals
#   'Bank (Money Center)' / 'Banks (Regional)' → bankmoneycenter / banksregional
#   'R.E.I.T.'                             → reit
#   'Oil/Gas (Production and Exploration)' → oilgasproductionandexploration
#   'Software (System & Application)' 등    → softwaresystemapplication
#   'Insurance (General|Life|Prop/Cas.)'   → insurance...
INDUSTRY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^semiconductor", SEMICONDUCTOR),          # Semiconductor, Semiconductor Equip
    (r"^computersperipherals", SEMICONDUCTOR),   # 스토리지/메모리 실질 (SanDisk 등)
    (r"^reit", REIT),                            # R.E.I.T.
    (r"^bank", BANK),                            # Bank (Money Center), Banks (Regional)
    (r"^insurance", INSURANCE),                  # Insurance (General/Life/Prop-Cas.)
    (r"^software", SOFTWARE),                    # Software (Entertainment/Internet/System…)
    (r"^oilgas", ENERGY),                        # Oil/Gas (Production and Exploration)
    (r"^energy", ENERGY),
)


def _compact(name: str) -> str:
    """damodaran._compact 와 동일 규칙. 두 모듈이 같은 정규화를 쓰도록 여기서도 정의한다."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def list_recipes() -> list[str]:
    """등록된 recipe 이름 목록(Default 포함)."""
    return list(REGISTRY.keys())


def get_recipe(name: str) -> Recipe:
    """recipe 이름으로 직접 조회. 없으면 Default."""
    return REGISTRY.get(name) or REGISTRY[DEFAULT]


def match_industry(industry: str | None) -> tuple[str, str | None]:
    """업종명 → (recipe 이름, 매치된 패턴).  매치 실패면 (DEFAULT, None)."""
    key = _compact(industry or "")
    if not key:
        return DEFAULT, None
    for pattern, recipe_name in INDUSTRY_PATTERNS:
        if re.search(pattern, key):
            return recipe_name, pattern
    return DEFAULT, None


def select_recipe(industry: str | None) -> Recipe:
    """Damodaran 업종명 → Recipe. 못 찾으면 Default(warnings 에 low_sector_specificity)."""
    return REGISTRY[match_industry(industry)[0]]


def select_recipe_with_reason(industry: str | None) -> tuple[Recipe, dict]:
    """select_recipe + 왜 그렇게 매핑됐는지(감사용).

    reason = {matched: bool, pattern: str|None, industry: str|None, fallback: bool}"""
    name, pattern = match_industry(industry)
    return REGISTRY[name], {
        "industry": industry,
        "matched": pattern is not None,
        "pattern": pattern,
        "fallback": pattern is None,
    }


# ── CLI ──────────────────────────────────────────────────────────────
def _print_recipe(r: Recipe) -> None:
    print(f"[{r.name}]")
    print(f"  primary   : {', '.join(r.primary) or '-'}")
    print(f"  secondary : {', '.join(r.secondary) or '-'}")
    print(f"  warnings  : {', '.join(r.warnings) or '-'}")
    if r.aliases:
        print(f"  aliases   : {', '.join(r.aliases)}")
    if r.note:
        print(f"  note      : {r.note}")


def main() -> None:
    ap = argparse.ArgumentParser(description="업종별 valuation recipe 레지스트리")
    ap.add_argument("--list", action="store_true", help="전체 recipe 출력")
    ap.add_argument("--industry", help="Damodaran 업종명 → 어떤 recipe 로 가는지 확인")
    a = ap.parse_args()

    if a.industry:
        r, why = select_recipe_with_reason(a.industry)
        tag = f"pattern={why['pattern']}" if why["matched"] else "매치 실패 → Default fallback"
        print(f"{a.industry!r} → {r.name}   ({tag})")
        _print_recipe(r)
        return

    print(f"recipe {len(REGISTRY)}개: {', '.join(list_recipes())}\n")
    for r in REGISTRY.values():
        _print_recipe(r)
        print()


if __name__ == "__main__":
    main()
