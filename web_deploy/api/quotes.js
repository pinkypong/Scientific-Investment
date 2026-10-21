// Vercel serverless function: GET /api/quotes
//
// US prices from Alpaca's free (IEX) market data, Korean prices from the 한국투자증권 (KIS)
// Open API. The response is cached at Vercel's edge for a few hours, so the phone dashboard
// refreshes without any commit to main. Keys live only in Vercel environment variables and
// never reach the browser:
//   ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY        (US)
//   KIS_APP_KEY, KIS_APP_SECRET, KIS_ENV=real|mock  (KR; KIS_ENV defaults to real)
// Either market can be configured alone. If a market fails, the other is still returned and
// the dashboard falls back to /data/manual_quotes.json for whatever is missing.
//
// Only symbols in the allow-lists are served, so the endpoint cannot be used to spend quota
// on arbitrary tickers. Only read-only quote endpoints are called; nothing here can trade.

const US_SYMBOLS = ["MU", "SNDK", "GOOGL", "MRVL", "ADI", "NVDA", "QCOM"];
const KR_CODES = { "005930": "삼성전자", "000660": "SK하이닉스" };
const ALPACA_ENDPOINT = "https://data.alpaca.markets/v2/stocks/snapshots";
const KIS_BASE = {
  real: "https://openapi.koreainvestment.com:9443",
  mock: "https://openapivts.koreainvestment.com:29443",
};
const KIS_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price";
const KIS_PRICE_TR_ID = "FHKST01010100"; // same id for real and mock
const CACHE_SECONDS = 3 * 60 * 60; // edge cache: at most one upstream round per 3 hours

function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

// Alpaca snapshots → {SYMBOL: {...}}. Unknown or malformed entries are dropped, not guessed.
function normalizeSnapshots(body, symbols) {
  const quotes = {};
  for (const symbol of symbols) {
    const snap = body && body[symbol];
    const price = snap && snap.latestTrade && Number(snap.latestTrade.p);
    if (!Number.isFinite(price) || price <= 0) continue;
    const prev = snap.prevDailyBar && Number(snap.prevDailyBar.c);
    quotes[symbol] = {
      market: "US", currency: "USD", price,
      prev_close: Number.isFinite(prev) && prev > 0 ? prev : null,
      change_pct: Number.isFinite(prev) && prev > 0 ? round(price / prev - 1, 6) : null,
      as_of: String(snap.latestTrade.t || ""),
    };
  }
  return quotes;
}

// KIS inquire-price body → one quote, or null. KIS returns every field as a string.
function normalizeKisPrice(body, code, fetchedAt) {
  if (!body || body.rt_cd !== "0" || !body.output) return null;
  const price = Number(body.output.stck_prpr);
  if (!Number.isFinite(price) || price <= 0) return null;
  const base = Number(body.output.stck_sdpr);
  const rate = Number(body.output.prdy_ctrt);
  return {
    market: "KR", currency: "KRW", name: KR_CODES[code], price,
    prev_close: Number.isFinite(base) && base > 0 ? base : null,
    change_pct: Number.isFinite(rate) ? round(rate / 100, 6) : null,
    as_of: fetchedAt, // KIS gives no trade time here; this is when we asked
  };
}

async function fetchUs(fetchImpl, keyId, secret) {
  const url = `${ALPACA_ENDPOINT}?symbols=${US_SYMBOLS.join(",")}&feed=iex`;
  const response = await fetchImpl(url, {
    headers: { "APCA-API-KEY-ID": keyId, "APCA-API-SECRET-KEY": secret },
  });
  if (!response.ok) throw new Error(`alpaca ${response.status}`);
  return normalizeSnapshots(await response.json(), US_SYMBOLS);
}

// Access tokens last a day; reuse one while this function instance stays warm.
let kisToken = null; // {value, base, appKey, expiresAt}

async function kisAccessToken(fetchImpl, base, appKey, appSecret, nowMs) {
  if (kisToken && kisToken.base === base && kisToken.appKey === appKey && kisToken.expiresAt - 60_000 > nowMs) {
    return kisToken.value;
  }
  const response = await fetchImpl(`${base}/oauth2/tokenP`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grant_type: "client_credentials", appkey: appKey, appsecret: appSecret }),
  });
  if (!response.ok) throw new Error(`kis token ${response.status}`);
  const body = await response.json();
  if (!body.access_token) throw new Error("kis token missing");
  const lifetimeMs = (Number(body.expires_in) > 0 ? Number(body.expires_in) : 86_400) * 1000;
  kisToken = { value: body.access_token, base, appKey, expiresAt: nowMs + lifetimeMs };
  return kisToken.value;
}

async function fetchKr(fetchImpl, appKey, appSecret, env, nowMs) {
  const base = KIS_BASE[env] || KIS_BASE.real;
  const token = await kisAccessToken(fetchImpl, base, appKey, appSecret, nowMs);
  const fetchedAt = new Date(nowMs).toISOString();
  const quotes = {};
  for (const code of Object.keys(KR_CODES)) { // sequential: KIS limits calls per second
    const url = `${base}${KIS_PRICE_PATH}?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=${code}`;
    const response = await fetchImpl(url, {
      headers: {
        "Content-Type": "application/json", authorization: `Bearer ${token}`,
        appkey: appKey, appsecret: appSecret, tr_id: KIS_PRICE_TR_ID, custtype: "P",
      },
    });
    if (!response.ok) continue;
    const quote = normalizeKisPrice(await response.json(), code, fetchedAt);
    if (quote) quotes[code] = quote;
  }
  return quotes;
}

function send(res, status, payload, cacheControl) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", cacheControl);
  res.end(JSON.stringify(payload));
}

async function handler(req, res, fetchImpl = globalThis.fetch, nowMs = Date.now()) {
  const env = process.env;
  const usReady = Boolean(env.ALPACA_API_KEY_ID && env.ALPACA_API_SECRET_KEY);
  const krReady = Boolean(env.KIS_APP_KEY && env.KIS_APP_SECRET);
  if (!usReady && !krReady) {
    return send(res, 503, { error: "quotes not configured" }, "no-store");
  }
  const quotes = {};
  const sources = [];
  const errors = []; // short labels only; never upstream bodies or keys
  if (usReady) {
    try {
      Object.assign(quotes, await fetchUs(fetchImpl, env.ALPACA_API_KEY_ID, env.ALPACA_API_SECRET_KEY));
      sources.push({ market: "US", name: "Alpaca market data (IEX feed)" });
    } catch (error) {
      errors.push("US upstream failed");
    }
  }
  if (krReady) {
    const kisEnv = env.KIS_ENV === "mock" ? "mock" : "real";
    try {
      Object.assign(quotes, await fetchKr(fetchImpl, env.KIS_APP_KEY, env.KIS_APP_SECRET, kisEnv, nowMs));
      sources.push({ market: "KR", name: `한국투자증권 Open API (${kisEnv === "mock" ? "모의" : "실전"})` });
    } catch (error) {
      errors.push("KR upstream failed");
    }
  }
  const wanted = [...(usReady ? US_SYMBOLS : []), ...(krReady ? Object.keys(KR_CODES) : [])];
  const missing = wanted.filter((symbol) => !(symbol in quotes));
  if (!Object.keys(quotes).length) {
    return send(res, 502, { error: "upstream unavailable", errors }, "no-store");
  }
  // A partial answer is cached only briefly, so a passing failure is retried soon.
  const cache = missing.length ? "public, s-maxage=600" : `public, s-maxage=${CACHE_SECONDS}, stale-while-revalidate=3600`;
  return send(res, 200, {
    fetched_at: new Date(nowMs).toISOString(),
    cache_seconds: missing.length ? 600 : CACHE_SECONDS,
    sources, quotes, missing, errors,
  }, cache);
}

function _resetTokenCache() { kisToken = null; }

module.exports = handler;
module.exports.normalizeSnapshots = normalizeSnapshots;
module.exports.normalizeKisPrice = normalizeKisPrice;
module.exports.US_SYMBOLS = US_SYMBOLS;
module.exports.KR_CODES = KR_CODES;
module.exports._resetTokenCache = _resetTokenCache;
