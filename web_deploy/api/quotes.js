// Vercel serverless function: GET /api/quotes
//
// US prices from Alpaca's free (IEX) market data, cached at Vercel's edge for a few hours so
// the phone dashboard refreshes without any commit to main. The API keys live only in Vercel
// environment variables (ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY) and never reach the browser.
//
// Only symbols in ALLOWED are served, so the endpoint cannot be used to spend our quota on
// arbitrary tickers. Korean prices are not here: they are entered by hand in
// /data/manual_quotes.json.

const ALLOWED = ["MU", "SNDK", "GOOGL", "MRVL", "ADI", "NVDA", "QCOM"];
const ENDPOINT = "https://data.alpaca.markets/v2/stocks/snapshots";
const CACHE_SECONDS = 3 * 60 * 60; // edge cache: at most one Alpaca call per 3 hours

function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

// Alpaca snapshots → {SYMBOL: {price, prev_close, change_pct, as_of}}. Unknown or malformed
// entries are dropped rather than guessed.
function normalizeSnapshots(body, symbols) {
  const quotes = {};
  for (const symbol of symbols) {
    const snap = body && body[symbol];
    const price = snap && snap.latestTrade && Number(snap.latestTrade.p);
    if (!Number.isFinite(price) || price <= 0) continue;
    const prev = snap.prevDailyBar && Number(snap.prevDailyBar.c);
    quotes[symbol] = {
      price,
      prev_close: Number.isFinite(prev) && prev > 0 ? prev : null,
      change_pct: Number.isFinite(prev) && prev > 0 ? round(price / prev - 1, 6) : null,
      as_of: String(snap.latestTrade.t || ""),
    };
  }
  return quotes;
}

function send(res, status, payload, cacheControl) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", cacheControl);
  res.end(JSON.stringify(payload));
}

async function handler(req, res, fetchImpl = globalThis.fetch) {
  const keyId = process.env.ALPACA_API_KEY_ID;
  const secret = process.env.ALPACA_API_SECRET_KEY;
  if (!keyId || !secret) {
    return send(res, 503, { error: "quotes not configured" }, "no-store");
  }
  const url = `${ENDPOINT}?symbols=${ALLOWED.join(",")}&feed=iex`;
  try {
    const response = await fetchImpl(url, {
      headers: { "APCA-API-KEY-ID": keyId, "APCA-API-SECRET-KEY": secret },
    });
    if (!response.ok) {
      // Never echo the upstream body: it can contain request details.
      return send(res, 502, { error: `upstream ${response.status}` }, "no-store");
    }
    const quotes = normalizeSnapshots(await response.json(), ALLOWED);
    return send(res, 200, {
      source: "Alpaca market data (IEX feed)",
      fetched_at: new Date().toISOString(),
      cache_seconds: CACHE_SECONDS,
      quotes,
      missing: ALLOWED.filter((symbol) => !(symbol in quotes)),
    }, `public, s-maxage=${CACHE_SECONDS}, stale-while-revalidate=3600`);
  } catch (error) {
    return send(res, 502, { error: "upstream unreachable" }, "no-store");
  }
}

module.exports = handler;
module.exports.normalizeSnapshots = normalizeSnapshots;
module.exports.ALLOWED = ALLOWED;
