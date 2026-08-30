# hankyung_global/ — 한경 글로벌마켓 어댑터 (NEWS / 수치 섹션은 SECONDARY_PROFESSIONAL)

해외(미국) 종목 **예상실적 컨센서스 수치**. PDF 없음.
`www.hankyung.com/globalmarket/equities/americas/<ticker>` — "예상실적(EPS)" 섹션.

## 확인된 제약 (WebFetch, 2026-08)
- 예상실적 컨센서스 표 · 목표주가 · 투자의견 · PER 은 **JS 렌더링 + 로그인 게이트** (비로그인 시 `—`).
- 손익/재무상태/현금흐름은 서버 렌더.
→ **Playwright(Chromium headless)** 로 "예상실적" 탭 클릭 후 렌더된 표를 읽는다. XHR JSON 엔드포인트가 잡히면 `store/raw/hankyung_global/xhr_*.json` 저장(향후 requests 직결 최적화).

## 세션
`config.providers.hankyung_global.storage_state`(Playwright storage state JSON) 또는 `user_data_dir`(영속 프로파일). 없으면 비로그인 진행 + 게이트 필드는 `gated_fields` → `NumberType.INSUFFICIENT` 레코드로 남김(값 None, 지어내지 않음). 로그인 절차(아이디/비번) 자체는 자동화하지 않음.

## 보정 / 실행
```bash
python -m data_sources.hankyung_global.adapter --ticker MU --dump-html
python -m data_sources.hankyung_global.adapter --ticker MU --storage-state state.json
```
`--dump-html` → `store/raw/hankyung_global/page_MU.html` 확인 후 `schema.py` SELECTORS / `parser.py` 조정.
