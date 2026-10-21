// Tests for web_deploy/api/quotes.js (Vercel function). Run: node --test scripts/test_quotes_function.mjs
// Kept outside web_deploy/ so Vercel never deploys it as an endpoint.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const handler = require("../web_deploy/api/quotes.js");
const { normalizeSnapshots, ALLOWED } = handler;

const KEY_ID = "test-key-id-DO-NOT-LEAK";
const SECRET = "test-secret-DO-NOT-LEAK";

function fakeRes() {
  return {
    statusCode: 0, headers: {}, body: "",
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    end(text) { this.body = text; },
    json() { return JSON.parse(this.body); },
  };
}

function withEnv(env, fn) {
  const saved = { id: process.env.ALPACA_API_KEY_ID, secret: process.env.ALPACA_API_SECRET_KEY };
  for (const [k, v] of Object.entries(env)) v === undefined ? delete process.env[k] : (process.env[k] = v);
  return fn().finally(() => {
    saved.id === undefined ? delete process.env.ALPACA_API_KEY_ID : (process.env.ALPACA_API_KEY_ID = saved.id);
    saved.secret === undefined ? delete process.env.ALPACA_API_SECRET_KEY : (process.env.ALPACA_API_SECRET_KEY = saved.secret);
  });
}

const configured = (fn) => withEnv({ ALPACA_API_KEY_ID: KEY_ID, ALPACA_API_SECRET_KEY: SECRET }, fn);

test("normalize keeps valid prices and computes change from the previous close", () => {
  const quotes = normalizeSnapshots({
    MU: { latestTrade: { p: 110, t: "2026-10-21T19:59:00Z" }, prevDailyBar: { c: 100 } },
    SNDK: { latestTrade: { p: 50, t: "t" } },              // no previous bar
    NVDA: { latestTrade: { p: "not a number" } },          // malformed → dropped
    QCOM: { latestTrade: { p: -1 } },                      // impossible → dropped
    EVIL: { latestTrade: { p: 1 } },                       // not requested → ignored
  }, ["MU", "SNDK", "NVDA", "QCOM"]);
  assert.deepEqual(Object.keys(quotes).sort(), ["MU", "SNDK"]);
  assert.equal(quotes.MU.change_pct, 0.1);
  assert.equal(quotes.SNDK.prev_close, null);
  assert.equal(quotes.SNDK.change_pct, null);
});

test("without keys the function says so and is not cached", async () => {
  await withEnv({ ALPACA_API_KEY_ID: undefined, ALPACA_API_SECRET_KEY: undefined }, async () => {
    const res = fakeRes();
    await handler({}, res, () => { throw new Error("must not call upstream"); });
    assert.equal(res.statusCode, 503);
    assert.equal(res.headers["cache-control"], "no-store");
  });
});

test("success: only allow-listed symbols, keys sent upstream only, edge-cached", async () => {
  await configured(async () => {
    let seenUrl, seenHeaders;
    const fetchImpl = async (url, init) => {
      seenUrl = url; seenHeaders = init.headers;
      return { ok: true, json: async () => ({ MU: { latestTrade: { p: 101.5, t: "x" }, prevDailyBar: { c: 100 } } }) };
    };
    const res = fakeRes();
    await handler({ query: { symbols: "AAPL,TSLA" } }, res, fetchImpl);  // query is ignored
    assert.equal(res.statusCode, 200);
    assert.match(seenUrl, /symbols=MU,SNDK,GOOGL,MRVL,ADI,NVDA,QCOM&feed=iex$/);
    assert.equal(seenHeaders["APCA-API-KEY-ID"], KEY_ID);
    assert.match(res.headers["cache-control"], /s-maxage=10800/);
    const body = res.json();
    assert.equal(body.quotes.MU.price, 101.5);
    assert.deepEqual(body.missing, ALLOWED.filter((s) => s !== "MU"));
    assert.ok(!res.body.includes(KEY_ID) && !res.body.includes(SECRET), "key leaked into response");
  });
});

test("upstream error is reported without echoing its body or caching", async () => {
  await configured(async () => {
    const res = fakeRes();
    await handler({}, res, async () => ({ ok: false, status: 403, text: async () => `bad key ${KEY_ID}` }));
    assert.equal(res.statusCode, 502);
    assert.equal(res.headers["cache-control"], "no-store");
    assert.ok(!res.body.includes(KEY_ID));
  });
});

test("network failure is a 502, not a crash", async () => {
  await configured(async () => {
    const res = fakeRes();
    await handler({}, res, async () => { throw new Error(`socket ${SECRET}`); });
    assert.equal(res.statusCode, 502);
    assert.ok(!res.body.includes(SECRET));
  });
});
