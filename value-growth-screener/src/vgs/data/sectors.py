"""Sector and industry classification from SEC SIC codes.

The SIC code and its description are reported facts (SEC submissions). Mapping a SIC code to
an industry and sector is a rule kept in ``config/sectors.json``; first matching rule wins.
A per-ticker override in ``config/sector_overrides.json`` is a human decision and must say
why. The original SIC is always kept next to the result, and nothing is ever guessed: a code
that no rule covers is reported as ``unclassified``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_SIC = "sec_sic"
SOURCE_OVERRIDE = "override"
SOURCE_UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class SectorMap:
    version: str
    sectors: tuple[dict[str, str], ...]          # ordered for display
    industries: dict[str, dict[str, str]]        # key -> {label, sector}
    rules: tuple[tuple[int, int, str], ...]      # (sic_from, sic_to, industry), first match wins

    def sector_label(self, key: str) -> str:
        return next(s["label"] for s in self.sectors if s["key"] == key)

    def industry_for(self, sic: int) -> str | None:
        return next((industry for low, high, industry in self.rules if low <= sic <= high), None)

    def catalog(self) -> list[dict[str, Any]]:
        """Sectors in display order, each with its industries (for viewers that build tabs)."""
        return [{"key": s["key"], "label": s["label"],
                 "industries": [{"key": k, "label": v["label"]} for k, v in self.industries.items()
                                if v["sector"] == s["key"]]}
                for s in self.sectors]


def load_sector_map(path: str | Path) -> SectorMap:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sectors = tuple({"key": s["key"], "label": s["label"]} for s in data["sectors"])
    sector_keys = {s["key"] for s in sectors}
    if len(sector_keys) != len(sectors):
        raise ValueError("duplicate sector key")
    industries: dict[str, dict[str, str]] = {}
    for item in data["industries"]:
        if item["key"] in industries:
            raise ValueError(f"duplicate industry key: {item['key']}")
        if item["sector"] not in sector_keys:
            raise ValueError(f"industry {item['key']} points to unknown sector {item['sector']}")
        industries[item["key"]] = {"label": item["label"], "sector": item["sector"]}
    rules = []
    for rule in data["rules"]:
        low, high, industry = int(rule["sic_from"]), int(rule["sic_to"]), rule["industry"]
        if not 100 <= low <= high <= 9999:
            raise ValueError(f"bad SIC range {low}-{high}")
        if industry not in industries:
            raise ValueError(f"rule {low}-{high} points to unknown industry {industry}")
        rules.append((low, high, industry))
    sector_map = SectorMap(str(data.get("version", "")), sectors, industries, tuple(rules))
    # A rule that no SIC code can reach is an ordering mistake (a wider rule above it).
    for index, (low, high, industry) in enumerate(sector_map.rules):
        earlier = sector_map.rules[:index]
        if all(any(a <= code <= b for a, b, _ in earlier) for code in range(low, high + 1)):
            raise ValueError(f"rule {low}-{high} -> {industry} is unreachable (covered by earlier rules)")
    return sector_map


def load_overrides(path: str | Path, sector_map: SectorMap) -> dict[str, dict[str, str]]:
    file = Path(path)
    if not file.exists():
        return {}
    raw = json.loads(file.read_text(encoding="utf-8")).get("overrides", {})
    overrides: dict[str, dict[str, str]] = {}
    for ticker, item in raw.items():
        symbol = ticker.strip().upper()
        if item.get("industry") not in sector_map.industries:
            raise ValueError(f"override {symbol}: unknown industry {item.get('industry')!r}")
        if not str(item.get("reason") or "").strip():
            raise ValueError(f"override {symbol}: a reason is required")
        overrides[symbol] = {"industry": item["industry"], "reason": str(item["reason"]).strip(),
                             "decided_on": str(item.get("decided_on") or "")}
    return overrides


def sic_from_submissions(payload: dict[str, Any]) -> tuple[int | None, str | None]:
    """SEC submissions JSON -> (sic, sicDescription). Missing or non-numeric SIC gives None."""
    raw = str(payload.get("sic") or "").strip()
    sic = int(raw) if raw.isdigit() else None
    description = str(payload.get("sicDescription") or "").strip() or None
    return sic, description


def classify(symbol: str, sic: int | None, sic_description: str | None, sector_map: SectorMap,
             overrides: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """One security's classification. The SIC facts are always carried through unchanged."""
    result: dict[str, Any] = {"symbol": symbol.strip().upper(), "sic": sic, "sic_description": sic_description,
                              "sic_industry": sector_map.industry_for(sic) if sic is not None else None}
    override = (overrides or {}).get(result["symbol"])
    if override:
        industry, source = override["industry"], SOURCE_OVERRIDE
        result["override_reason"] = override["reason"]
        result["override_decided_on"] = override["decided_on"]
    elif result["sic_industry"]:
        industry, source = result["sic_industry"], SOURCE_SIC
    else:
        result.update({"industry": None, "industry_label": None, "sector": None, "sector_label": None,
                       "source": SOURCE_UNCLASSIFIED, "map_version": sector_map.version})
        return result
    sector = sector_map.industries[industry]["sector"]
    result.update({"industry": industry, "industry_label": sector_map.industries[industry]["label"],
                   "sector": sector, "sector_label": sector_map.sector_label(sector),
                   "source": source, "map_version": sector_map.version})
    return result


def collect_sector_rows(records: list[Any], fetch_submissions: Any, sector_map: SectorMap,
                        overrides: dict[str, dict[str, str]], observed_at: str) -> list[dict[str, Any]]:
    """Classify each security record (needs ``symbol`` and ``cik``) with its SEC SIC code.

    ``fetch_submissions(cik)`` returns the SEC submissions JSON. A record without a CIK, or
    whose fetch fails, is still listed with ``note`` saying why, so nothing silently drops."""
    rows = []
    for record in records:
        cik = str(getattr(record, "cik", "") or "").strip()
        sic, description, note = None, None, None
        if not cik.isdigit():
            note = "cik_not_found"
        else:
            try:
                sic, description = sic_from_submissions(fetch_submissions(cik))
                if sic is None:
                    note = "sic_missing"
            except Exception as error:  # one failure must not stop the batch
                note = f"fetch_failed: {type(error).__name__}"
        row = classify(record.symbol, sic, description, sector_map, overrides)
        row.update({"name": getattr(record, "name", None), "cik": cik.zfill(10) if cik.isdigit() else None,
                    "provider": "SEC", "observed_at": observed_at,
                    "url": f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json" if cik.isdigit() else None})
        if note:
            row["note"] = note
        rows.append(row)
    return rows


def sector_counts(rows: list[dict[str, Any]], sector_map: SectorMap) -> list[tuple[str, int]]:
    """(sector label, count) in display order, sectors without rows left out."""
    counts = [(s["label"], sum(row.get("sector") == s["key"] for row in rows)) for s in sector_map.sectors]
    return [(label, count) for label, count in counts if count]


def is_failed(row: dict[str, Any]) -> bool:
    """The SEC lookup itself failed (no CIK, or the fetch raised), as opposed to an uncovered SIC."""
    note = str(row.get("note") or "")
    return note == "cik_not_found" or note.startswith("fetch_failed")


def summarize(rows: list[dict[str, Any]], sector_map: SectorMap) -> list[str]:
    """Human-readable lines: count per sector, then everything that needs a look."""
    lines = [f"{label}: {count}" for label, count in sector_counts(rows, sector_map)]
    for label, test in (("unclassified", lambda r: r["source"] == SOURCE_UNCLASSIFIED),
                        ("override", lambda r: r["source"] == SOURCE_OVERRIDE)):
        hits = [f"{r['symbol']}({r.get('sic') or r.get('note') or '-'})" for r in rows if test(r)]
        if hits:
            lines.append(f"{label} {len(hits)}: {', '.join(hits)}")
    return lines


_SOURCE_LABELS = {SOURCE_SIC: "규칙", SOURCE_OVERRIDE: "예외", SOURCE_UNCLASSIFIED: "미분류"}


def _cell(value: Any) -> str:
    text = "" if value is None else " ".join(str(value).split())
    return text.replace("|", "\\|")


def render_summary_markdown(rows: list[dict[str, Any]], sector_map: SectorMap) -> str:
    """Markdown run summary (GitHub step summary): sector counts and one table row per security."""
    observed = next((row.get("observed_at") for row in rows if row.get("observed_at")), "-")
    counts = sector_counts(rows, sector_map)
    lines = ["### SEC 섹터 분류", "", f"분류표 버전 `{sector_map.version or '-'}` · 조회 시각 `{observed}`", "",
             "섹터별: " + (" · ".join(f"{label} {count}" for label, count in counts) if counts else "없음"), "",
             "| 종목 | SIC | SIC 설명 | 업종 | 섹터 | 출처 | 비고 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        notes = [row.get("override_reason") if row.get("source") == SOURCE_OVERRIDE else None, row.get("note")]
        lines.append("| " + " | ".join(_cell(value) for value in (
            row.get("symbol"), row.get("sic"), row.get("sic_description"), row.get("industry_label"),
            row.get("sector_label"), _SOURCE_LABELS.get(row.get("source"), row.get("source")),
            "; ".join(str(n) for n in notes if n))) + " |")
    unclassified = sum(row.get("source") == SOURCE_UNCLASSIFIED for row in rows)
    failed = sum(is_failed(row) for row in rows)
    lines += ["", f"전체 {len(rows)}개 · 미분류 {unclassified}개 · 실패 {failed}개", ""]
    return "\n".join(lines)


def annotation_lines(rows: list[dict[str, Any]]) -> list[str]:
    """GitHub workflow commands that surface failures and unclassified rows on the run page."""
    failed = [f"{r['symbol']}({r.get('note')})" for r in rows if is_failed(r)]
    other = [f"{r['symbol']}({r.get('sic') or r.get('note') or '-'})" for r in rows
             if r.get("source") == SOURCE_UNCLASSIFIED and not is_failed(r)]
    lines = []
    if failed:
        lines.append(f"::error title=SEC sectors::{len(failed)}개 종목 실패: {', '.join(failed)}")
    if other:
        lines.append(f"::warning title=SEC sectors::{len(other)}개 종목 미분류: {', '.join(other)}")
    return lines
