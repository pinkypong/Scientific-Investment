"""Provider Independence (스펙 §21).

business logic 은 구체 클라이언트(HankyungConsensusClient 등)를 직접 부르지 않고
아래 인터페이스만 호출한다. 새 공급자 추가 = 구현체 추가만 (dashboard core 무수정, 스펙 §22).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .schema import NormalizedRecord


class BaseProvider(ABC):
    name: str = "base"
    source_label: str = "base"

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def normalize(self, raw) -> list[NormalizedRecord]:
        """provider 원본 → NormalizedRecord[]. 파서 위임 가능."""

    # 선택: 증분 동기화 지원 여부
    supports_incremental: bool = False


class ResearchReportProvider(BaseProvider):
    """한경 컨센서스 등 sell-side 리서치."""

    @abstractmethod
    def list_reports(self, *, ticker: str, name: str | None,
                     since: str, until: str, limit: int) -> list[dict]:
        ...

    @abstractmethod
    def fetch_report(self, report_ref: dict) -> dict:
        """PDF/원문 확보 → {raw_ref, pdf_path, text, meta}."""


class MarketDataProvider(BaseProvider):
    """bigdata.com 등 가격 · 비율 · 컨센서스 집계."""

    @abstractmethod
    def fetch_quote(self, *, entity_id: str) -> dict:
        ...

    @abstractmethod
    def fetch_consensus(self, *, entity_id: str) -> dict:
        ...


class NewsProvider(BaseProvider):
    """한경 글로벌마켓 뉴스 · bigdata search 뉴스."""

    @abstractmethod
    def search(self, *, query: str, since: str, until: str, limit: int) -> list[dict]:
        ...


class FundamentalProvider(BaseProvider):
    """향후 SEC EDGAR · OpenDART 등 1차 재무."""

    @abstractmethod
    def fetch_statements(self, *, entity_id: str, statement: str) -> dict:
        ...


# ── 레지스트리 ─────────────────────────────────────────────────────────
_REGISTRY: dict[str, type[BaseProvider]] = {}


def register(key: str):
    def deco(cls: type[BaseProvider]):
        _REGISTRY[key] = cls
        cls.name = key
        return cls
    return deco


def get_provider(key: str, config: dict | None = None) -> BaseProvider:
    if key not in _REGISTRY:
        raise KeyError(f"미등록 provider: {key} (등록됨: {sorted(_REGISTRY)})")
    return _REGISTRY[key](config)


def available() -> list[str]:
    return sorted(_REGISTRY)
