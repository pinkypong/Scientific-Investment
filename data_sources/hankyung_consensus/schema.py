"""한경 컨센서스 원본 필드 → 공통 필드 매핑 참고.

목록 페이지(consensus.hankyung.com/analysis/list) 표 컬럼(2026-08 확인):
  작성일 | 분류 | 제목 | 작성자 | 제공출처   (+ 상세/PDF 링크 report_idx)
PDF: /analysis/downpdf?report_idx=<N>

※ 목표주가 / 투자의견 컬럼은 목록에 항상 노출되지 않음 → PDF 본문 또는 상세 페이지에서 보완.
※ 실제 DOM class/구조는 --dump-html 로 1회 보정 후 SELECTORS 확정.
"""

# 분류(한글) → document_type
REPORT_TYPE_MAP = {
    "기업": "company",
    "산업": "industry",
    "시장": "strategy",
    "투자전략": "strategy",
    "경제": "macro",
    "채권": "macro",
    "파생": "strategy",
    "스몰캡": "company",
}

# skinType 파라미터
SKIN_TYPE = {
    "company": "business",
    "industry": "industry",
    "strategy": "market",
    "macro": "economy",
}

# 목록 표 파싱용 후보 셀렉터 (보정 시 조정)
SELECTORS = {
    "row": "table.table_style tbody tr, .board_list tbody tr",
    "date": "td.first, td.date, td:nth-child(1)",
    "category": "td.division, td:nth-child(2)",
    "title_link": "td.text_l a, td.title a, a.tit",
    "author": "td.author, td.writer",
    "broker": "td.company, td.source, td:last-child",
    "pdf_link": "a[href*='downpdf']",
    "paging_next": "a.next, .paging a[rel='next']",
}
