# hankyung_consensus/ — 한경 컨센서스 어댑터 (SECONDARY_PROFESSIONAL)

국내 증권사 리서치 리포트: PDF + 목표주가/투자의견/추정치.
`consensus.hankyung.com/analysis/list` (서버 렌더) · PDF `= /analysis/downpdf?report_idx=<N>`.

## 동작
1. `list_reports()` — 기간·`pagenum` 파라미터로 목록 페이지 요청 → `parser.parse_list_html` 로 표 파싱.
2. `fetch_report()` — PDF 다운로드 → `store/raw/hankyung_consensus/pdf_<idx>.pdf` → `parser.extract_from_pdf`(pymupdf, 앞 3p)로 목표주가·투자의견·핵심문장 추출. 연도별 추정표는 대개 **이미지** → `estimates={}` + `extraction_confidence` 낮춤(세션에서 Claude 가 PDF 직접 판독).
3. `normalize()` — 리포트 1건 → 레코드 여러 개(target_price · rating · 연도별 estimate · 문서 레코드).

## 보정 (최초 1회)
```bash
python -m data_sources.hankyung_consensus.adapter --ticker 005930 --name 삼성전자 \
       --since 2026-06-01 --until 2026-08-27 --max 5 --dump-html
# → store/raw/hankyung_consensus/list_*.html 확인 후 schema.py SELECTORS 조정
```

## 안전
robots.txt 확인 · `User-Agent` 명시 · `request_delay_sec`(기본 1.5s) · `max_per_ticker`. 로그인 필요 시 `config.providers.hankyung_consensus.cookie_file` (Netscape). 로그인 절차 자체는 자동화하지 않음.
