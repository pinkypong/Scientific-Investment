"""Valuation 레이어 — 업종 기준점(Damodaran) · 업종별 metric recipe · 기업별 context.

구성:
  damodaran.py  학습자료/damodaran_*.json 로더. 업종 → Benchmark 조회.
  recipes.py    업종별로 "무엇을 먼저 볼 것인가"(primary/secondary/warnings) 레지스트리.
  context.py    config 의 covered 기업 → (업종, benchmark, recipe, 신뢰도, 경고) 결합.

원칙:
- Damodaran 값은 **정답이 아니라 업종 기준점/가드레일**이다. 개별 기업 가치의 근거가 아니라
  "우리 숫자가 업종 대비 어디쯤인가"를 재는 자다.
- 목표주가·컨센서스·forward EPS 는 actual valuation input 으로 쓰지 않는다.
  (Damodaran 의 pe_forward / exp_growth_5y 도 forecast 파생이므로 context 전용.)
- 계산은 이 단계에서 완성하지 않는다. 여기서는 "어떤 metric 을 볼지"까지만 확정한다.

실행:
  python -m data_sources.valuation --check
  python -m data_sources.valuation.context --check
  python -m data_sources.valuation.damodaran --list
"""

__all__ = ["damodaran", "recipes", "context"]
