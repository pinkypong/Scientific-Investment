"""Financial data ingestion architecture (파일 기반).

레이어:  Source Adapter → Parser → Normalization → Validation → Store(append-only JSONL)
        → build_dashboard_data (derive) → 대시보드 인라인 주입(MC/CD/DS/SRC/HEALTH)

설계서: 데이터소스_아키텍처_리팩터_설계서_v1.md  (Phase 0–2)
불변 규칙: Missing ≠ 0 · 원본 덮어쓰기 금지 · 파생/원본 분리 · 모든 값은 출처까지 역추적.
"""

__all__ = ["common"]
