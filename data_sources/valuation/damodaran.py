"""Damodaran 업종 벤치마크 로더 (학습자료/damodaran_*.json).

두 파일을 함께 읽는다:
  damodaran_allsectors.json   넓고 평평 — 54개 업종 x 공통 지표. **기본 조회면**.
  damodaran_benchmarks.json   좁고 깊음 — 반도체/반도체장비/시장전체 심화 + caveat/usage_rules.
                              → 해당 업종이면 Benchmark.deep 에 붙고 가드레일 텍스트로 노출.

중요 — 이 값들은 **정답이 아니라 업종 기준점/가드레일**이다:
- 개별 기업의 적정가치를 산출하는 입력이 아니라, 우리 숫자가 업종 평균 대비 어디쯤인지
  재는 자(ruler)다. "반도체 EV/EBITDA 42.7x" 를 메모리 peak EBITDA 에 곱하는 식의
  사용은 금지(usage_rules 참조).
- US aggregate(USD) 기준이다. KR 기업(삼성/SK하이닉스)에 쓸 때는 통화·CRP 조정이 필요하다.
- `pe_forward` / `exp_growth_5y` 는 forecast 파생이므로 **actual valuation input 으로 쓰지 말 것**
  (FORWARD_LOOKING_FIELDS). 업종 분위기를 읽는 context 로만 사용한다.
- 연 1회(매년 1월) 갱신되는 스냅샷이다. as_of 를 항상 함께 표시한다.

실행:
  python -m data_sources.valuation.damodaran --list
  python -m data_sources.valuation.damodaran --industry Semiconductor
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_DS_ROOT = _HERE.parent                       # data_sources/
_CFG_PATH = _DS_ROOT / "config" / "data_sources.json"

# data_sources/ 기준 상대경로. config 의 dashboard.damodaran_sectors 가 있으면 그쪽이 우선.
DEFAULT_ALLSECTORS_REL = "../학습자료/damodaran_allsectors.json"
BENCHMARKS_FILENAME = "damodaran_benchmarks.json"

# benchmarks.json 의 심화 키 → allsectors 의 업종명. 명시적 테이블(자동 추측 금지).
DEEP_KEY_TO_INDUSTRY = {
    "semiconductor": "Semiconductor",
    "semiconductor_equip": "Semiconductor Equip",
    "total_market_us": "Total Market",
}

# Benchmark 이 반드시 노출하는 필드(누락 시 None).
CORE_FIELDS = (
    "n_firms", "beta", "cost_of_equity", "wacc", "equity_weight", "pretax_cost_of_debt",
    "pbv", "roe", "roic", "pe_current", "pe_trailing", "pe_forward",
    "net_margin", "operating_margin_pretax", "ebitda_margin", "ev_ebitda", "ev_ebit",
)

# forecast 파생 필드 — actual valuation input 으로 쓰지 않는다(프로젝트 불변 규칙).
FORWARD_LOOKING_FIELDS = ("pe_forward", "exp_growth_5y", "peg")

_FORWARD_GUARD = ("pe_forward · exp_growth_5y · peg 는 컨센서스/forward 추정 파생이다. "
                  "actual valuation input 으로 쓰지 말고 업종 context 로만 볼 것.")


class DamodaranDataMissing(FileNotFoundError):
    """학습자료의 Damodaran 스냅샷 파일을 찾지 못했다. 경로만 알리고 내용은 노출하지 않는다."""


# ── 업종명 정규화 ────────────────────────────────────────────────────
def _compact(name: str) -> str:
    """대소문자/공백/구두점에 관용적인 조회 키.

    'R.E.I.T.' → 'reit' · 'Semiconductor Equip' → 'semiconductorequip'
    · 'semiconductor_equip' → 'semiconductorequip' · ' computers/peripherals ' →
    'computersperipherals'.  원래 표기는 인덱스가 따로 보존한다."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


# ── 파일 로드 (프로세스 1회 캐시) ────────────────────────────────────
_cache: dict[str, Any] = {}


def _resolve_paths() -> tuple[Path, Path]:
    """(allsectors, benchmarks) 절대경로. config 에 경로가 있으면 그것을, 없으면 기본값.

    경로는 항상 data_sources/ 를 기준으로 계산하므로 cwd 가 어디든 동일하게 동작한다."""
    rel = DEFAULT_ALLSECTORS_REL
    try:
        cfg = json.loads(_CFG_PATH.read_text(encoding="utf-8"))
        rel = (cfg.get("dashboard") or {}).get("damodaran_sectors") or rel
    except Exception:  # noqa: BLE001 — config 가 없거나 깨져도 기본 경로로 동작해야 한다.
        pass
    allsectors = (_DS_ROOT / rel).resolve()
    return allsectors, (allsectors.parent / BENCHMARKS_FILENAME)


def _load(path: Path, what: str) -> dict:
    if not path.exists():
        raise DamodaranDataMissing(f"{what} 파일 없음: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DamodaranDataMissing(f"{what} 파싱 실패: {path} ({e.lineno}행)") from e


def load_allsectors(*, refresh: bool = False) -> dict:
    if refresh or "allsectors" not in _cache:
        _cache["allsectors"] = _load(_resolve_paths()[0], "damodaran_allsectors")
    return _cache["allsectors"]


def load_benchmarks(*, refresh: bool = False) -> dict:
    """심화 파일. 없어도 조회 자체는 성립하므로 {} 로 degrade 한다(deep 만 비어짐)."""
    if refresh or "benchmarks" not in _cache:
        try:
            _cache["benchmarks"] = _load(_resolve_paths()[1], "damodaran_benchmarks")
        except DamodaranDataMissing:
            _cache["benchmarks"] = {}
    return _cache["benchmarks"]


def _index(*, refresh: bool = False) -> dict[str, str]:
    """compact 키 → 원래 업종명(대소문자/구두점 보존)."""
    if refresh or "index" not in _cache:
        sectors = load_allsectors(refresh=refresh).get("sectors") or {}
        _cache["index"] = {_compact(k): k for k in sectors}
    return _cache["index"]


# ── Benchmark ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Benchmark:
    """업종 하나의 Damodaran 기준점. 누락 필드는 None 을 유지한다(Missing != 0)."""

    industry: str
    n_firms: int | None = None
    beta: float | None = None
    cost_of_equity: float | None = None
    wacc: float | None = None
    equity_weight: float | None = None
    pretax_cost_of_debt: float | None = None
    pbv: float | None = None
    roe: float | None = None
    roic: float | None = None
    pe_current: float | None = None
    pe_trailing: float | None = None
    pe_forward: float | None = None
    net_margin: float | None = None
    operating_margin_pretax: float | None = None
    ebitda_margin: float | None = None
    ev_ebitda: float | None = None
    ev_ebit: float | None = None

    extra: dict = field(default_factory=dict)      # allsectors 의 나머지 원본 필드
    deep: dict | None = None                       # benchmarks.json 심화(있을 때만)
    caveat: str | None = None                      # 심화 데이터의 개별 주의사항
    usage_rules: tuple[str, ...] = ()              # benchmarks.json 전역 사용 규칙
    meta: dict = field(default_factory=dict)       # source / as_of / region / note / market

    @property
    def has_deep(self) -> bool:
        return bool(self.deep)

    def guardrails(self) -> list[str]:
        """이 벤치마크를 쓸 때 함께 읽어야 할 경고 텍스트.

        usage_rules 는 benchmarks.json 의 **파일 전역** 규칙(내용상 반도체 중심)이라
        비반도체 업종에도 그대로 붙는다 — 경고는 과하게 보여주는 쪽이 안전하다는 판단."""
        out: list[str] = [_FORWARD_GUARD]
        if self.caveat:
            out.append(str(self.caveat))
        out.extend(self.usage_rules)
        note = (self.meta or {}).get("note")
        if note:
            out.append(str(note))
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usage_rules"] = list(self.usage_rules)
        d["has_deep"] = self.has_deep
        d["guardrails"] = self.guardrails()
        return d


# ── 공개 API ─────────────────────────────────────────────────────────
def list_industries() -> list[str]:
    """allsectors 에 존재하는 업종명(원래 표기) 정렬 목록."""
    return sorted((load_allsectors().get("sectors") or {}).keys())


def resolve_industry(industry: str | None) -> str | None:
    """관용적 입력 → 정확한 업종명. 없으면 None (예외 아님)."""
    if not industry:
        return None
    return _index().get(_compact(industry))


def market_context() -> dict:
    """무위험이자율 / implied ERP 등 시장 레벨 메타. 두 파일 모두에서 모은다."""
    a = load_allsectors()
    b = load_benchmarks()
    return {
        "as_of": a.get("as_of"),
        "region": a.get("region"),
        "allsectors_market": a.get("market") or {},
        "benchmarks_market": b.get("market") or {},
    }


def usage_rules() -> list[str]:
    """benchmarks.json 의 전역 사용 규칙(가드레일 텍스트)."""
    return list(load_benchmarks().get("usage_rules") or [])


def _deep_for(industry: str) -> dict | None:
    b = load_benchmarks()
    for key, mapped in DEEP_KEY_TO_INDUSTRY.items():
        if _compact(mapped) == _compact(industry):
            v = b.get(key)
            return dict(v) if isinstance(v, dict) else None
    return None


def get_benchmark(industry: str) -> Benchmark | None:
    """업종명으로 조회. 대소문자/공백/구두점에 관용적이되 원래 이름을 보존해 돌려준다.

    업종이 없으면 **예외가 아니라 None** — 호출측이 warning 으로 처리하고 Default recipe
    로 degrade 할 수 있어야 하기 때문이다. 반대로 파일 자체가 없으면
    DamodaranDataMissing 예외 — 그건 데이터 부재가 아니라 설정 오류이므로 조용히 넘기지 않는다."""
    name = resolve_industry(industry)
    if name is None:
        return None

    doc = load_allsectors()
    row = dict((doc.get("sectors") or {}).get(name) or {})
    core = {f: row.get(f) for f in CORE_FIELDS}
    extra = {k: v for k, v in row.items() if k not in CORE_FIELDS and k != "industry"}

    deep = _deep_for(name)
    caveat = None
    if deep is not None:
        caveat = deep.pop("caveat", None)

    bench_doc = load_benchmarks()
    meta = {
        "source": doc.get("source"),
        "as_of": doc.get("as_of"),
        "region": doc.get("region"),
        "note": doc.get("note"),
        "market": doc.get("market") or {},
        "deep_source": bench_doc.get("source") if deep else None,
        "deep_as_of": bench_doc.get("as_of") if deep else None,
    }
    return Benchmark(industry=name, extra=extra, deep=deep, caveat=caveat,
                     usage_rules=tuple(usage_rules()), meta=meta, **core)


# ── CLI ──────────────────────────────────────────────────────────────
def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Damodaran 업종 기준점 조회 (정답 아님 · 업종 가드레일)")
    ap.add_argument("--list", action="store_true", help="업종명 전체 출력")
    ap.add_argument("--industry", help="업종 하나 상세 출력 (대소문자/구두점 관용)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    a = ap.parse_args()

    if a.industry:
        bm = get_benchmark(a.industry)
        if bm is None:
            print(f"WARNING: 업종 없음 → {a.industry!r} (--list 로 확인)")
            return
        if a.json:
            print(json.dumps(bm.to_dict(), ensure_ascii=False, indent=2))
            return
        print(f"[{bm.industry}]  as_of={bm.meta.get('as_of')}  "
              f"deep={'yes' if bm.has_deep else 'no'}")
        for f in CORE_FIELDS:
            flag = "   (forward — actual input 금지)" if f in FORWARD_LOOKING_FIELDS else ""
            print(f"  {f:<26} {_fmt(getattr(bm, f))}{flag}")
        print("\n가드레일:")
        for g in bm.guardrails():
            print(f"  · {g}")
        return

    inds = list_industries()
    if a.json:
        print(json.dumps({"as_of": load_allsectors().get("as_of"), "industries": inds},
                         ensure_ascii=False, indent=2))
        return
    print(f"업종 {len(inds)}개 (as_of={load_allsectors().get('as_of')}):")
    for name in inds:
        print(f"  {name}")


if __name__ == "__main__":
    main()
