// Tests for web_deploy/api/quotes.js (Vercel function). Run: node --test scripts/test_quotes_function.mjs
// Kept outside web_deploy/ so Vercel never deploys it as an endpoint. No network: every
// upstream call goes to a fake fetch.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const handler = require("../web_deploy/api/quotes.js");
const { normalizeSnapshots, normalizeKisPrice, US_SYMBOLS, KR_CODES } = handler;

const SECRETS = {
  ALPACA_API_KEY_ID: "alpaca-id-DO-NOT-LEAK", ALPACA_API_SECRET_KEY: "alpaca-secret-DO-NOT-LEAK",
  KIS_APP_KEY: "kis-key-DO-NOT-LEAK", KIS_APP_SECRET: "kis-secret-DO-NOT-LEAK",
};
const ENV_KEYS = [...Object.keys(SECRETS), "KIS_ENV"];
const NOW = Date.parse("2026-10-22T01:00:00Z");

beforeEach(() => handler._resetTokenCache());

function fakeRes() {
  return {
    statusCode: 0, headers: {}, body: "",
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    end(text) { this.body = text; },
    json() { return JSON.parse(this.body); },
  };
}

async function withEnv(env, fn) {
  const saved = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
  for (const k of ENV_KEYS) delete process.env[k];
  Object.assign(process.env, env);
  try { return await fn(); } finally {
    for (const k of ENV_KEYS) saved[k] === undefined ? delete process.env[k] : (process.env[k] = saved[k]);
  }
}

function assertNoSecret(text) {
  for (const value of Object.values(SECRETS)) assert.ok(!text.includes(value), `secret leaked: ${value}`);
}

const json = (body, ok = true, status = 200) => ({ ok, status, json: async () => body, text: async () => JSON.stringify(body) });
const ALPACA_ALL = Object.fromEntries(US_SYMBOLS.map((s, i) => [s, { latestTrade: { p: 100 + i, t: "2026-10-21T19:59:00Z" }, prevDailyBar: { c: 100 } }]));
const kisPrice = (prpr, sdpr = "60000", ctrt = "1.50") => ({ rt_cd: "0", msg1: "정상처리", output: { stck_prpr: prpr, stck_sdpr: sdpr, prdy_ctrt: ctrt } });

// Routes fake upstream calls and records them.
function upstream({ alpaca = json(ALPACA_ALL), token = json({ access_token: "tok-1", expires_in: 86400 }), kis = {} } = {}) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    if (url.startsWith("https://data.alpaca.markets/")) { if (alpaca instanceof Error) throw alpaca; return alpaca; }
    if (url.endsWith("/oauth2/tokenP")) return token;
    const code = new URL(url).searchParams.get("FID_INPUT_ISCD");
    return kis[code] || json(kisPrice("61000"));
  };
  return { fetchImpl, calls };
}

test("normalize: Alpaca keeps valid prices and drops malformed ones", () => {
  const quotes = normalizeSnapshots({
    MU: { latestTrade: { p: 110, t: "t" }, prevDailyBar: { c: 100 } },
    SNDK: { latestTrade: { p: 50, t: "t" } },
    NVDA: { latestTrade: { p: "x" } },
    QCOM: { latestTrade: { p: -1 } },
  }, ["MU", "SNDK", "NVDA", "QCOM"]);
  assert.deepEqual(Object.keys(quotes).sort(), ["MU", "SNDK"]);
  assert.equal(quotes.MU.change_pct, 0.1);
  assert.equal(quotes.SNDK.prev_close, null);
});

test("normalize: KIS strings become numbers; failures are dropped", () => {
  const q = normalizeKisPrice(kisPrice("61000", "60000", "-1.25"), "005930", "2026-10-22T01:00:00.000Z");
  assert.deepEqual(q, { market: "KR", currency: "KRW", name: "삼성전자", price: 61000, prev_close: 60000,
                        change_pct: -0.0125, as_of: "2026-10-22T01:00:00.000Z" });
  assert.equal(normalizeKisPrice({ rt_cd: "1", msg1: "오류", output: { stck_prpr: "61000" } }, "005930", "t"), null);
  assert.equal(normalizeKisPrice({ rt_cd: "0", output: { stck_prpr: "0" } }, "005930", "t"), null);
});

test("nothing configured: 503, not cached, no upstream call", async () => {
  await withEnv({}, async () => {
    const res = fakeRes();
    await handler({}, res, () => { throw new Error("must not call upstream"); }, NOW);
    assert.equal(res.statusCode, 503);
    assert.equal(res.headers["cache-control"], "no-store");
  });
});

test("both markets: full answer, KIS request shape, long edge cache, no secret in body", async () => {
  await withEnv(SECRETS, async () => {
    const { fetchImpl, calls } = upstream();
    const res = fakeRes();
    await handler({ query: { symbols: "AAPL" } }, res, fetchImpl, NOW);  // query ignored
    assert.equal(res.statusCode, 200);
    const body = res.json();
    assert.deepEqual(body.missing, []);
    assert.equal(body.quotes["005930"].price, 61000);
    assert.equal(body.quotes["000660"].name, "SK하이닉스");
    assert.equal(body.quotes.MU.market, "US");
    assert.match(res.headers["cache-control"], /s-maxage=10800/);
    const token = calls.find((c) => c.url.endsWith("/oauth2/tokenP"));
    assert.equal(token.url, "https://openapi.koreainvestment.com:9443/oauth2/tokenP");  // real by default
    assert.deepEqual(JSON.parse(token.init.body), { grant_type: "client_credentials",
      appkey: SECRETS.KIS_APP_KEY, appsecret: SECRETS.KIS_APP_SECRET });
    const price = calls.find((c) => c.url.includes("inquire-price"));
    assert.equal(price.init.headers.tr_id, "FHKST01010100");
    assert.equal(price.init.headers.custtype, "P");
    assert.equal(price.init.headers.authorization, "Bearer tok-1");
    assert.match(price.url, /FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=005930$/);
    assert.ok(calls.every((c) => !c.url.includes("order")), "only quote endpoints may be called");
    assertNoSecret(res.body);
  });
});

test("KIS_ENV=mock uses the mock server", async () => {
  await withEnv({ KIS_APP_KEY: SECRETS.KIS_APP_KEY, KIS_APP_SECRET: SECRETS.KIS_APP_SECRET, KIS_ENV: "mock" }, async () => {
    const { fetchImpl, calls } = upstream();
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.ok(calls.every((c) => c.url.startsWith("https://openapivts.koreainvestment.com:29443/")));
    assert.match(res.json().sources[0].name, /모의/);
  });
});

test("token is reused while valid and reissued after expiry", async () => {
  await withEnv({ KIS_APP_KEY: "k", KIS_APP_SECRET: "s" }, async () => {
    const { fetchImpl, calls } = upstream();
    await handler({}, fakeRes(), fetchImpl, NOW);
    await handler({}, fakeRes(), fetchImpl, NOW + 3 * 3600_000);
    assert.equal(calls.filter((c) => c.url.endsWith("/oauth2/tokenP")).length, 1);
    await handler({}, fakeRes(), fetchImpl, NOW + 25 * 3600_000);
    assert.equal(calls.filter((c) => c.url.endsWith("/oauth2/tokenP")).length, 2);
  });
});

test("one market failing does not hide the other; partial answers cache briefly", async () => {
  await withEnv(SECRETS, async () => {
    const { fetchImpl } = upstream({ alpaca: new Error(`boom ${SECRETS.ALPACA_API_SECRET_KEY}`) });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.equal(res.statusCode, 200);
    const body = res.json();
    assert.ok("005930" in body.quotes);
    assert.deepEqual(body.errors, ["US upstream failed: network error"]);  // exception text is never echoed
    assert.deepEqual(body.missing, US_SYMBOLS);
    assert.equal(res.headers["cache-control"], "public, s-maxage=600");
    assertNoSecret(res.body);
  });
});

test("KIS error answer for one code drops only that code", async () => {
  await withEnv({ KIS_APP_KEY: "k", KIS_APP_SECRET: "s" }, async () => {
    const { fetchImpl } = upstream({ kis: { "000660": json({ rt_cd: "1", msg1: "초당 거래건수 초과" }) } });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.deepEqual(Object.keys(res.json().quotes), ["005930"]);
    assert.deepEqual(res.json().missing, ["000660"]);
    assert.deepEqual(res.json().errors, ["KR 000660: rt_cd 1"]);  // free text msg1 is not echoed
  });
});

test("diagnostics: token rejection shows the status and KIS error code, never the body text", async () => {
  await withEnv({ KIS_APP_KEY: SECRETS.KIS_APP_KEY, KIS_APP_SECRET: SECRETS.KIS_APP_SECRET }, async () => {
    const { fetchImpl } = upstream({ token: json({ error_code: "EGW00103", error_description: `bad ${SECRETS.KIS_APP_SECRET}` }, false, 403) });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.deepEqual(res.json().errors, ["KR upstream failed (real): kis token http 403 EGW00103"]);
    assertNoSecret(res.body);
  });
});

test("diagnostics: per-code KIS failure carries rt_cd and msg_cd; hostile codes are dropped", async () => {
  await withEnv({ KIS_APP_KEY: "k", KIS_APP_SECRET: "s" }, async () => {
    const { fetchImpl } = upstream({ kis: {
      "005930": json({ rt_cd: "1", msg_cd: "EGW00201", msg1: "초당 거래건수 초과" }),
      "000660": json({ rt_cd: "1", msg_cd: "<script>alert(1)</script>" }),
    } });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.equal(res.statusCode, 502);  // nothing usable at all
    assert.deepEqual(res.json().errors, ["KR 005930: rt_cd 1 EGW00201", "KR 000660: rt_cd 1"]);
  });
});

test("diagnostics: HTTP error on a price call is reported with its status", async () => {
  await withEnv({ KIS_APP_KEY: "k", KIS_APP_SECRET: "s" }, async () => {
    const { fetchImpl } = upstream({ kis: { "005930": json({ msg_cd: "EGW00123" }, false, 500) } });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.deepEqual(res.json().errors, ["KR 005930: http 500 EGW00123"]);
    assert.ok("000660" in res.json().quotes);
  });
});

test("diagnostics: the mode (real or mock) is stated so a wrong KIS_ENV is obvious", async () => {
  await withEnv({ KIS_APP_KEY: "k", KIS_APP_SECRET: "s", KIS_ENV: "mock" }, async () => {
    const { fetchImpl } = upstream();
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.equal(res.json().sources[0].env, "mock");
  });
});

test("token failure and total failure: 502, not cached, no secret", async () => {
  await withEnv({ KIS_APP_KEY: SECRETS.KIS_APP_KEY, KIS_APP_SECRET: SECRETS.KIS_APP_SECRET }, async () => {
    const { fetchImpl } = upstream({ token: json({ error_description: `bad ${SECRETS.KIS_APP_SECRET}` }, false, 403) });
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    assert.equal(res.statusCode, 502);
    assert.equal(res.headers["cache-control"], "no-store");
    assert.deepEqual(res.json().errors, ["KR upstream failed (real): kis token http 403"]);
    assertNoSecret(res.body);
  });
});

test("pasted keys with stray whitespace still work; KIS_ENV is case/space tolerant", async () => {
  await withEnv({ KIS_APP_KEY: "  key-with-space \n", KIS_APP_SECRET: "\tsecret\r\n", KIS_ENV: " Mock ",
                  ALPACA_API_KEY_ID: " id ", ALPACA_API_SECRET_KEY: "sec\n" }, async () => {
    const { fetchImpl, calls } = upstream();
    const res = fakeRes();
    await handler({}, res, fetchImpl, NOW);
    const token = calls.find((c) => c.url.endsWith("/oauth2/tokenP"));
    assert.ok(token.url.startsWith("https://openapivts.koreainvestment.com:29443"), "KIS_ENV ' Mock ' should mean mock");
    assert.deepEqual(JSON.parse(token.init.body), { grant_type: "client_credentials", appkey: "key-with-space", appsecret: "secret" });
    const price = calls.find((c) => c.url.includes("inquire-price"));
    assert.equal(price.init.headers.appkey, "key-with-space");
    const alpaca = calls.find((c) => c.url.startsWith("https://data.alpaca.markets/"));
    assert.equal(alpaca.init.headers["APCA-API-KEY-ID"], "id");
    assert.equal(alpaca.init.headers["APCA-API-SECRET-KEY"], "sec");
  });
});

test("a key that is only whitespace counts as not configured", async () => {
  await withEnv({ KIS_APP_KEY: "   ", KIS_APP_SECRET: "\n" }, async () => {
    const res = fakeRes();
    await handler({}, res, () => { throw new Error("must not call upstream"); }, NOW);
    assert.equal(res.statusCode, 503);
  });
});

test("allow-lists are what the dashboard expects", () => {
  assert.ok(US_SYMBOLS.includes("MU") && US_SYMBOLS.includes("SNDK"));
  assert.deepEqual(Object.keys(KR_CODES), ["005930", "000660"]);
});
