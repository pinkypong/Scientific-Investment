"""Markdown and CSV rendering."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable


DISCLAIMER = """---
**Powered by Bigdata.com** - https://bigdata.com

## Disclaimer

This output is for informational and research-assistance purposes only. It does **not** constitute investment, legal, tax, accounting, or other professional advice, and it is **not** a recommendation to buy, sell, or hold any security or instrument or to pursue any strategy. Information may be incomplete, estimated, delayed, or inaccurate. Past performance does not guarantee future results. Verify material facts independently and consult qualified advisors before making decisions.
"""


def _pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1%}"


def _num(value: Any, digits: int = 2) -> str:
    return "N/A" if value is None else f"{float(value):,.{digits}f}"


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(_flatten(value, path))
        else:
            rows.append((path, value))
    return rows


def render_markdown(result: dict[str, Any]) -> str:
    security = result.get("security", {})
    computed = result["computed"]
    ticker = security.get("ticker", "UNKNOWN")
    name = security.get("name", ticker)
    score = computed["objective_score"]
    lines = [
        f"# {ticker} — {name} 가치·안전마진 스크린",
        "",
        f"- 기준일: {result.get('as_of') or 'N/A'}",
        f"- 판정: **{computed['decision']}**",
        f"- 객관 근거 점수: **{score['total']:.2f}/100**",
        f"- 위험조정 기회점수: **{computed['risk_adjusted_opportunity_score']:.2f}/100**",
        f"- 확률가중 적정가치: **{_num(computed.get('probability_weighted_fair_value'))}**",
        f"- 기대 상승여력: **{_pct(computed.get('upside'))}**",
        f"- Base 안전마진: **{_pct(computed.get('margin_of_safety'))}**",
        f"- 데이터 완전성: **{_pct(computed.get('data_completeness'))}**",
        f"- 출처 연결률: **{_pct(computed.get('provenance_coverage'))}**",
        "",
        "> 객관 근거 점수는 원자료와 그 산술 파생치만 사용합니다. 적정가치·상승여력·안전마진은 아래 주관적 시나리오 가정에 의존하므로 별도 표시합니다.",
        "",
        "## 시나리오 가치평가",
        "",
        "| 시나리오 | 확률 | 주당 적정가치 | 현 주가 대비 | Terminal 비중 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in computed.get("scenario_valuation", []):
        lines.append(
            f"| {row['name']} | {_pct(row['probability'])} | {_num(row['fair_value_per_share'])} | "
            f"{_pct(row.get('upside'))} | {_pct(row.get('terminal_value_share'))} |"
        )
    lines.extend([
        "",
        f"Reverse DCF 내재 초기 매출성장률: **{_pct(computed.get('reverse_dcf_implied_initial_growth'))}**",
        "",
        "### 상대가치 교차검증",
        "",
    ])
    cross = computed.get("relative_cross_check")
    if cross:
        lines.append(
            f"- 방법: `{cross['method']}` · 주당 적정가치: **{_num(cross['fair_value_per_share'])}** · "
            f"상승여력: **{_pct(cross.get('upside'))}**"
        )
    else:
        lines.append("- 상대가치 가정이 없어 계산하지 않음")
    wacc = computed.get("wacc_build")
    lines.extend(["", "### WACC 구성", ""])
    if wacc:
        lines.append(
            f"- 자기자본비용 {_pct(wacc['cost_of_equity'])}, 세후부채비용 {_pct(wacc['after_tax_cost_of_debt'])}, "
            f"자기자본 비중 {_pct(wacc['equity_weight'])}, 부채 비중 {_pct(wacc['debt_weight'])}, "
            f"산출 WACC **{_pct(wacc['wacc'])}**"
        )
    else:
        lines.append("- 객관적 자본시장 입력이 불완전하여 산출하지 않음")
    lines.extend([
        "",
        "## 객관 근거 점수",
        "",
        "| 구성 | 점수 | 최대 |",
        "|---|---:|---:|",
        f"| 수익성·현금전환 품질 | {score['quality']:.2f} | 30 |",
        f"| 성장·추정치 변화 | {score['growth_and_revisions']:.2f} | 20 |",
        f"| 재무안정성 | {score['balance_sheet']:.2f} | 20 |",
        f"| 시장위험·분산효과 | {score['market_risk_and_diversification']:.2f} | 20 |",
        f"| 기관·고용·미디어 보조신호 | {score['auxiliary_signals']:.2f} | 10 |",
        "",
        "## 객관적 원자료",
        "",
        "| 필드 | 값 |",
        "|---|---:|",
    ])
    for path, value in _flatten(result.get("objective", {})):
        rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
        lines.append(f"| `{path}` | {rendered} |")
    lines.extend(["", "## 주관적 가정", "", "| 필드 | 값 |", "|---|---:|"])
    for path, value in _flatten(result.get("assumptions", {})):
        rendered = f"{value:.6g}" if isinstance(value, float) else str(value)
        lines.append(f"| `{path}` | {rendered} |")
    lines.extend(["", "## 데이터 품질·위험 플래그", ""])
    flags = result.get("flags", [])
    if flags:
        lines.extend(["| 심각도 | 코드 | 설명 |", "|---|---|---|"])
        for flag in flags:
            lines.append(f"| {flag['severity']} | `{flag['code']}` | {flag['message']} |")
    else:
        lines.append("- 탐지된 플래그 없음")
    lines.extend(["", "## Data sources", ""])
    sources = result.get("sources", [])
    if sources:
        for source in sources:
            label = source.get("provider", "source")
            locator = source.get("url") or source.get("document_id") or "N/A"
            observed = source.get("observed_at", "N/A")
            fields = ", ".join(source.get("fields", [])) or "unspecified"
            lines.append(f"- {label}: {locator} (관측 {observed}; 필드 {fields})")
    else:
        lines.append("- 출처 메타데이터 없음 — 실투자 판정 전에 원자료 검증 필요")
    lines.extend(["", DISCLAIMER.rstrip(), ""])
    return "\n".join(lines)


def render_ranking_csv(results: Iterable[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["rank", "ticker", "name", "decision", "objective_score", "opportunity_score", "fair_value",
                     "upside", "margin_of_safety", "completeness", "provenance_coverage", "critical_flags"])
    for rank, result in enumerate(results, 1):
        c = result["computed"]
        critical = sum(flag["severity"] == "critical" for flag in result.get("flags", []))
        writer.writerow([rank, result.get("security", {}).get("ticker"), result.get("security", {}).get("name"),
                         c["decision"], c["objective_score"]["total"], c["risk_adjusted_opportunity_score"],
                         c.get("probability_weighted_fair_value"),
                         c.get("upside"), c.get("margin_of_safety"), c["data_completeness"],
                         c["provenance_coverage"], critical])
    return buffer.getvalue()
