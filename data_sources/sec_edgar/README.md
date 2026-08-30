# sec_edgar/ — SEC EDGAR 어댑터 (PRIMARY_OFFICIAL, 미국)

미국 covered 기업(Micron·SanDisk)의 **실제 공시 재무**. 인증 불필요.
SEC 정책상 `User-Agent`(이름+이메일) 필수 → `SEC_EDGAR_USER_AGENT` 또는 `config.providers.sec_edgar.user_agent`.

## 동작
1. `resolve_cik(tickers)` — `company_tickers.json` 으로 ticker→CIK. (config `covered[].sec_cik` 에 저장됨: MU=0000723125, SNDK=0002023554)
2. `fetch_statements(entity_id=CIK)` — metric 별 후보 XBRL 태그(`common/xbrl_map.SEC_TAGS`)를 `companyconcept/CIK{cik}/us-gaap/{tag}.json` 로 순회, 첫 히트 사용.
3. `parser.facts_for_metric` — fact 의 `fy/fp` 는 **보고서** 기준이라 신뢰 안 함. `start`/`end` 날짜로 기간 도출(`common/periods.sec_frame`). flow=분기(~90d)/연간(~365d) 만, 누적(YTD-Q) 제외. stock=instant.
4. restatement: 같은 `period` 를 여러 filing 이 보고 → **전부 저장**, 최신 `filed` = `revision_status:"latest"`, 이전 = `"superseded"` (+ 값 다르면 note).
5. `_validate` — 연속 period 극단 변화(§19) WARNING. 삭제 안 함.

레코드: `source_type=PRIMARY_OFFICIAL`, `number_type=FACT`, `source_metric`=XBRL 태그(보존), `currency=USD`, `original_url`=filing index, `fiscal_year/fiscal_period/form/filing_date/accession`.

## 실행
```bash
export SEC_EDGAR_USER_AGENT="Your Name <CONTACT_EMAIL>"
python -m data_sources.sec_edgar.adapter --all
python -m data_sources.sec_edgar.adapter --resolve-cik MU SNDK
python -m data_sources.run_sync --provider sec_edgar
```

## 결과 (2026-08-27 실제 호출)
Micron 14개 metric × FY2009~FY2025 + 분기 · SanDisk 14개 metric × FY2023~FY2026. 총 ~2,444 레코드 → `store/normalized/sec_edgar.jsonl`.
⚠ SanDisk FY2026 revenue(+175% YoY)는 spin-off 전후 재무 불연속 가능 → validation WARNING, bigdata cross-check 권장.
