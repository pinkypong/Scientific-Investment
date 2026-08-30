"""Common Data Interface (설계서 스펙 §2).

provider 별 원본 포맷이 달라도 내부에서는 NormalizedRecord 하나로 수렴한다.
모든 필드가 모든 데이터에 필요하지는 않으므로 대부분 optional.
단, source/provider/original_url/retrieved_at/as_of_date 는 최대한 항상 채운다.

기존 대시보드 LN() 노드 스키마
  {label,value,type,confidence,formula,calc,source,sourceDate,verification,
   why[],evidence[],contra[],parents[],missing[],method}
와 손실 없이 상호 변환 가능해야 한다 (to_ln_node / from 참고).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "rec") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class NormalizedRecord:
    """정규화 레코드 1건 = (기업, metric, period) 한 시점의 관측/추정/파생값."""

    # ── 필수(가능한 한 항상) ──────────────────────────────────────────────
    source: str                      # "한경 컨센서스" | "한경 글로벌마켓" | "bigdata.com" ...
    provider: str                    # 구현체 키: "hankyung_consensus" | "hankyung_global" | "bigdata"
    retrieved_at: str = field(default_factory=now_iso)
    as_of_date: Optional[str] = None       # 이 값이 "언제 기준"인지 = period end (YYYY-MM-DD)
    available_date: Optional[str] = None   # 스펙 §7: 시장에서 이용 가능해진 시점 = filing_date (분기말 아님)
    original_url: Optional[str] = None

    # ── 분류 ────────────────────────────────────────────────────────────
    source_type: Optional[str] = None      # classification.SourceClass 값
    number_type: Optional[str] = None      # classification.NumberType 값 (FACT/CONSENSUS/...)
    document_type: Optional[str] = None    # "company" | "industry" | "strategy" | "macro" | "news" | "filing" | "market"

    # ── 시간 ────────────────────────────────────────────────────────────
    published_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ── 대상 ────────────────────────────────────────────────────────────
    ticker: Optional[str] = None           # KR 6자리 코드 또는 해외 티커
    slug: Optional[str] = None             # 대시보드 종목 슬러그 (samsung/skhynix/micron/sandisk ...)
    company_name: Optional[str] = None
    market: Optional[str] = None           # "KR" | "US" | ...
    currency: Optional[str] = None         # "KRW" | "USD"

    # ── 값 ──────────────────────────────────────────────────────────────
    metric: Optional[str] = None           # normalization.canon_metric 결과 (canonical)
    value: Any = None                      # 숫자 또는 문자열. Missing 이면 None (0 아님)
    unit: Optional[str] = None             # "KRW" | "USD" | "x" | "%" | "억원" ...
    period: Optional[str] = None           # "FY2027" | "2027-Q2" | "2026-08-15" | "TTM" ...

    # ── 리서치 문서 메타 ────────────────────────────────────────────────
    report_id: Optional[str] = None
    report_title: Optional[str] = None
    analyst: Optional[str] = None
    broker: Optional[str] = None
    rating: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_path: Optional[str] = None

    # ── 파생 표식 (스펙 §9) ────────────────────────────────────────────
    is_derived: bool = False
    formula: Optional[str] = None
    input_record_ids: list[str] = field(default_factory=list)
    calculated_at: Optional[str] = None

    # ── 품질 ────────────────────────────────────────────────────────────
    confidence: Optional[str] = None       # "Low" | "Medium" | "High" | 0-100
    validation_status: Optional[str] = None  # "VALID" | "WARNING" | "ERROR"
    validation_notes: list[str] = field(default_factory=list)
    verification: Optional[str] = None      # "Verified" | "Cross-Checked" | "Estimated" | "Model-Derived" | "Unverified"

    # ── raw 보존 (스펙 §17) ────────────────────────────────────────────
    raw_ref: Optional[str] = None          # raw/<source>/<key> 상대경로
    raw_value: Any = None                  # 파싱 전 원본 표기 ("47,500" 등)
    source_metric: Optional[str] = None    # 원본 계정/XBRL 태그 (예: RevenueFromContractWithCustomer...) — 삭제 금지

    # ── 공시 재무 메타 (Phase B) ──────────────────────────────────────
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None    # "Q1" | "Q2" | "Q3" | "Q4" | "FY"
    original_period: Optional[str] = None  # provider 원본 표기 (예: "2026Q3", "11014")
    form: Optional[str] = None             # "10-K" | "10-Q" | "사업보고서" ...
    filing_date: Optional[str] = None
    accession: Optional[str] = None        # SEC accession / DART rcept_no
    fs_div: Optional[str] = None           # "CFS"(연결) | "OFS"(별도)
    revision_status: Optional[str] = None  # "original" | "restated" | "superseded"

    # ── Phase B: legacy/estimate 의존 표식 ───────────────────────────
    deprecated_for_actual_dashboard: bool = False

    # ── 계보 UI 부가 (LN() 호환) ──────────────────────────────────────
    why: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    contra: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    # ── 식별 ────────────────────────────────────────────────────────────
    record_id: str = field(default_factory=lambda: new_id("rec"))

    # ------------------------------------------------------------------
    def dedup_key(self) -> str:
        """스펙 §15: 단순 title matching 금지 — 다중 필드 조합 해시."""
        parts = [
            self.provider or "",
            self.original_url or self.pdf_url or "",
            self.report_id or self.accession or "",
            (self.report_title or "").strip(),
            self.published_at or self.as_of_date or "",
            self.broker or "",
            self.ticker or self.slug or "",
            self.metric or "",
            self.source_metric or "",
            self.period or "",
            str(self.fiscal_year or ""),
            self.fiscal_period or "",
            self.fs_div or "",
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "NormalizedRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_ln_node(self) -> dict:
        """대시보드 DS[slug][key] 로 들어갈 계보 노드(JS LN() 형식)."""
        node = {
            "label": self.report_title or self.metric or "value",
            "value": self.value if self.value is not None else "—",
            "type": (self.number_type or "UNVERIFIED"),
            "confidence": self.confidence or "—",
        }
        if self.formula:
            node["formula"] = self.formula
        if self.source:
            node["source"] = self.source + (f" ({self.broker})" if self.broker else "")
        if self.as_of_date:
            node["sourceDate"] = self.as_of_date
        if self.original_url or self.pdf_url:
            node["url"] = self.original_url or self.pdf_url
        if self.verification:
            node["verification"] = self.verification
        # Phase B provenance
        for src_key, dst_key in (
            ("source_metric", "source_metric"), ("currency", "currency"),
            ("period", "period"), ("form", "form"),
            ("filing_date", "filing_date"), ("retrieved_at", "retrieved_at"),
            ("available_date", "available_date"),
            ("accession", "accession"), ("fs_div", "fs_div"),
            ("revision_status", "revision_status"), ("raw_ref", "raw_ref"),
            ("record_id", "record_id"),
        ):
            v = getattr(self, src_key)
            if v not in (None, ""):
                node[dst_key] = v
        if self.source_type:
            node["source_type"] = self.source_type
        if self.validation_status:
            node["validation_status"] = self.validation_status
        if self.validation_notes:
            node["validation_notes"] = list(self.validation_notes)
        if self.deprecated_for_actual_dashboard:
            node["deprecated_for_actual_dashboard"] = True
            node["core_eligible"] = False
        for k in ("why", "evidence", "contra", "missing"):
            v = getattr(self, k)
            if v:
                node[k] = list(v)
        if self.is_derived and self.input_record_ids:
            node["input_record_ids"] = list(self.input_record_ids)
        return node


@dataclass
class DerivedMetric:
    """원본을 잃지 않기 위해 계산 결과 + formula + 입력 id 를 함께 저장 (스펙 §9)."""

    name: str
    value: Any
    formula: str
    input_record_ids: list[str]
    calculated_at: str = field(default_factory=now_iso)
    unit: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_normalized(self, **overrides) -> NormalizedRecord:
        base = dict(
            source="derived",
            provider="analytics_engine",
            source_type="DERIVED",
            number_type="MODEL",
            metric=self.name,
            value=self.value,
            unit=self.unit,
            is_derived=True,
            formula=self.formula,
            input_record_ids=list(self.input_record_ids),
            calculated_at=self.calculated_at,
            why=list(self.notes),
        )
        base.update(overrides)
        return NormalizedRecord(**base)


def dumps(records: list[NormalizedRecord]) -> str:
    return "\n".join(json.dumps(r.to_json(), ensure_ascii=False) for r in records)


def loads(text: str) -> list[NormalizedRecord]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(NormalizedRecord.from_json(json.loads(line)))
    return out
