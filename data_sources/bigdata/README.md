# bigdata/ — Bigdata.com 어댑터 (MARKET_DATA)

Bigdata 는 **브라우저에서** `window.cowork.callMcpTool` 로 호출된다 (index.html `refreshQuotes`/`loadNews`).
서버측에서 임의로 MCP 를 부르지 않는다.

## 역할
- `tool(name)` / `call_args_tearsheet` / `call_args_search` — MCP tool 이름을 `config.providers.bigdata.mcp_server` + entity_id 로 조립. **하드코딩 UUID 제거**(설계서 C4). 브라우저는 `SRC.mcp_server` 로 주입받음.
- `normalize(raw)` — tearsheet 파싱 결과 → `NormalizedRecord[]` (price=FACT, 컨센서스=CONSENSUS).
- `save_snapshot(slug, tearsheet_json)` — 브라우저/세션에서 받은 응답을 append-only 스토어에 적재 → **이력 축적**(설계서 C3). raw 원본도 보존.
- `save_feed_snapshot(results)` — search 결과를 뉴스/리포트로 분류해 문서 레코드로 적재.

## 사용
```bash
# 브라우저에서 tearsheet 응답을 JSON 파일로 저장한 뒤:
python -m data_sources.bigdata.adapter --snapshot tearsheet_samsung.json --slug samsung --as-of 2026-08-27
```

## 파싱 경로
`schema.py` 의 `PRICE_PATHS` / `CONSENSUS_PATHS` — tearsheet 구조가 sections 파라미터에 따라 달라져 관대하게 탐색. 현재 대시보드가 실제 읽는 값은 `price_performance.current_market.current_price`.
