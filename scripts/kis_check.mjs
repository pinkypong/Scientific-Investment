// Local KIS check. Run it yourself in your own terminal; keys are typed in hidden and never
// printed. Output contains no key, secret or token, so it is safe to paste back.
//
//   node scripts/kis_check.mjs
//
// 1) checks the shape of the key and secret (length, stray whitespace, swapped values);
// 2) runs the real Vercel function code (web_deploy/api/quotes.js) end to end against KIS,
//    so a fix is proven on this machine before it is pushed. If the live server rejects the
//    key, it also tries the mock server to catch a live/mock mismatch.
import readline from "node:readline";
import { createRequire } from "node:module";

const handler = createRequire(import.meta.url)("../web_deploy/api/quotes.js");

function askHidden(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    rl._writeToOutput = (text) => { if (text.includes(question)) rl.output.write(text); };
    rl.question(question, (answer) => { rl.close(); process.stdout.write("\n"); resolve(answer); });
  });
}

function shape(label, value) {
  const trimmed = value.trim();
  const notes = [];
  if (value !== trimmed) notes.push("앞뒤에 공백/줄바꿈 있음");
  if (/\s/.test(trimmed)) notes.push("중간에 공백 있음");
  if (!trimmed) notes.push("비어 있음");
  console.log(`${label}: 길이 ${trimmed.length}자${notes.length ? " · ⚠ " + notes.join(", ") : " · 공백 문제 없음"}`);
  return trimmed;
}

async function runFunction(mode, key, secret) {
  for (const name of ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]) delete process.env[name];
  Object.assign(process.env, { KIS_APP_KEY: key, KIS_APP_SECRET: secret, KIS_ENV: mode });
  handler._resetTokenCache();
  const res = { statusCode: 0, body: "", setHeader() {}, end(text) { this.body = text; } };
  await handler({}, res);
  const body = JSON.parse(res.body || "{}");
  const prices = Object.entries(body.quotes || {})
    .map(([code, q]) => `${q.name || code} ${q.price.toLocaleString("ko-KR")}원`);
  console.log(`${mode}: HTTP ${res.statusCode} · 받은 시세: ${prices.join(", ") || "없음"}`);
  console.log(`   missing: ${JSON.stringify(body.missing || [])} · errors: ${JSON.stringify(body.errors || body.error || [])}`);
  return body;
}

const rawKey = process.env.KIS_APP_KEY ?? await askHidden("KIS APP KEY (입력은 화면에 안 보임): ");
const rawSecret = process.env.KIS_APP_SECRET ?? await askHidden("KIS APP SECRET (입력은 화면에 안 보임): ");

console.log("\n── 키 모양 ──");
const key = shape("APP KEY", rawKey);
const secret = shape("APP SECRET", rawSecret);
if (key && secret && key.length > secret.length) console.log("⚠ APP KEY가 SECRET보다 깁니다. 두 값이 바뀌었을 수 있습니다.");

console.log("\n── 서버 함수(quotes.js) 그대로 실행: 실전 서버 ──");
const real = await runFunction("real", key, secret);
const tokenRejected = (real.errors || []).some((e) => e.includes("kis token"));
if (tokenRejected) {
  console.log("\n── 실전에서 키 거부 → 모의 서버로도 시험 ──");
  const mock = await runFunction("mock", key, secret);
  if (Object.keys(mock.quotes || {}).length) console.log('\n→ 모의 앱 키입니다. Vercel의 KIS_ENV 를 "mock" 으로 바꾸세요.');
  else console.log("\n→ 두 서버 모두 거부했습니다. 키 값 자체(복사 오류·바뀐 값·앱 미승인)를 확인하세요.");
} else if (!(real.missing || []).length) {
  console.log('\n→ 정상. 한국 종목이 모두 들어왔습니다. Vercel KIS_ENV 는 "real".');
} else {
  console.log("\n→ 키는 정상이지만 일부 종목이 빠졌습니다. 위 errors 를 확인하세요.");
}
