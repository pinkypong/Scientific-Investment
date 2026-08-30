# opendart/ — OpenDART 어댑터 (PRIMARY_OFFICIAL, 한국)

한국 covered 기업(삼성전자·SK하이닉스)의 **실제 공시 재무**(전자공시 DART).

## ⚠ 현재 BLOCKED — API 키 필요
1. https://opendart.fss.or.kr 회원가입 → **인증키 신청**(무료, 즉시 발급, 일 20,000건)
2. `data_sources/.env` 생성(`.env.example` 복사) → `OPENDART_API_KEY=발급키`
3. `python -m data_sources.opendart.adapter --all`

키 없으면 어댑터는 `BLOCKED` 안내만 출력하고 종료(구현은 완료).

## 동작 (키 있을 때)
1. `resolve_corp(stock_codes)` — `corpCode.xml`(zip) 로 종목코드→corp_code. (config `covered[].dart_corp_code` 에 예비값: 삼성 00126380, SK하이닉스 00164779 — **키 확보 후 resolve-corp 로 검증 권장**)
2. `fetch_statements(corp_code)` — `fnlttSinglAcntAll.json` 을 (연도 × reprt_code) 매트릭스로 호출. **연결(CFS) 우선**, 없으면 별도(OFS) fallback + `notes` 표기.
3. `parser.parse_acnt_all` — `account_id`(IFRS 표준계정, `common/xbrl_map.DART_ACCOUNT_ID`) 우선, 없으면 `account_nm`(한글 계정명) 매칭. `thstrm_amount` = **절대값(원 단위)** 문자열 → 숫자.
4. 기간: `reprt_code` → `common/periods.dart_frame` (11011=FY, 11013=Q1, 11012=반기(누적), 11014=Q3).

레코드: `source_type=PRIMARY_OFFICIAL`, `number_type=FACT`, `source_metric`=account_id 보존, `currency=KRW`, `fs_div=CFS|OFS`, `accession`=rcept_no, `original_url`=DART 공시 뷰어.

## 실행
```bash
python -m data_sources.opendart.adapter --resolve-corp 005930 000660
python -m data_sources.opendart.adapter --all
python -m data_sources.run_sync --provider opendart
```
