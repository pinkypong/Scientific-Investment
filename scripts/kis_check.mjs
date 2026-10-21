// Local KIS check. Run it yourself in your own terminal. Keys are never printed, so the
// output is safe to paste back.
//
//   node scripts/kis_check.mjs
//
// Where the keys come from, in order:
//   1) data_sources/.env  (KIS_APP_KEY=..., KIS_APP_SECRET=...). Ignored by git and blocked by
//      the pre-commit hook. Easiest: paste the keys into it with Notepad.
//   2) environment variables KIS_APP_KEY / KIS_APP_SECRET, if non-empty
//   3) a hidden prompt (paste with a right-click; Ctrl+V may not work in this prompt)
//
// Then: checks the key shape, and runs the real Vercel function code (web_deploy/api/quotes.js)
// unchanged against KIS, so a fix is proven on this machine before it is pushed.
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const handler = createRequire(import.meta.url)("../web_deploy/api/quotes.js");
const envFile = process.env.KIS_ENV_FILE || path.join(here, "..", "data_sources", ".env");

function readEnvFile(file) {
  if (!fs.existsSync(file)) return {};
  const values = {};
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/);
    if (match) values[match[1]] = match[2].replace(/^(["'])(.*)\1$/, "$2");
  }
  return values;
}

function askHidden(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    rl._writeToOutput = (text) => { if (text.includes(question)) rl.output.write(text); };
    let done = false;
    const finish = (answer) => { if (!done) { done = true; process.stdout.write("\n"); resolve(answer); } };
    rl.on("close", () => finish(""));  // input closed without an answer counts as empty
    rl.question(question, (answer) => { finish(answer); rl.close(); });
  });
}

function shape(label, value) {
  const trimmed = value.trim();
  const notes = [];
  if (value !== trimmed) notes.push("앞뒤에 공백/줄바꿈 있음");
  if (/\s/.test(trimmed)) notes.push("중간에 공백 있음");
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
  const quotes = body.quotes || {};
  const prices = Object.entries(quotes).map(([code, q]) => `${q.name || code} ${q.price.toLocaleString("ko-KR")}원`);
  console.log(`${mode}: HTTP ${res.statusCode} · 받은 시세: ${prices.join(", ") || "없음"}`);
  console.log(`   missing: ${JSON.stringify(body.missing || [])} · errors: ${JSON.stringify(body.errors || body.error || [])}`);
  const krCodes = Object.keys(handler.KR_CODES);
  return { body, complete: res.statusCode === 200 && krCodes.every((code) => code in quotes),
           tokenRejected: (body.errors || []).some((e) => e.includes("kis token")) };
}

const fileValues = readEnvFile(envFile);
let source = "";
let rawKey = fileValues.KIS_APP_KEY || "";
let rawSecret = fileValues.KIS_APP_SECRET || "";
if (rawKey || rawSecret) source = process.env.KIS_ENV_FILE ? "지정한 파일" : "data_sources/.env 파일";
else if ((process.env.KIS_APP_KEY || "").trim() && (process.env.KIS_APP_SECRET || "").trim()) {
  rawKey = process.env.KIS_APP_KEY; rawSecret = process.env.KIS_APP_SECRET; source = "환경 변수";
} else {
  console.log("키를 붙여 넣으세요. 화면에 표시되지 않습니다. 붙여넣기는 마우스 오른쪽 클릭으로 하세요.");
  rawKey = await askHidden("KIS APP KEY: ");
  rawSecret = rawKey.trim() ? await askHidden("KIS APP SECRET: ") : "";
  source = "직접 입력";
}

console.log(`\n── 키 모양 (출처: ${source}) ──`);
const key = shape("APP KEY", rawKey);
const secret = shape("APP SECRET", rawSecret);
if (!key || !secret) {
  console.log("\n✋ 키가 비어 있어 시험하지 않았습니다.");
  console.log("   메모장으로 data_sources\\.env 파일을 만들어 아래 두 줄을 넣고 다시 실행하세요:");
  console.log("   KIS_APP_KEY=여기에_APP_KEY\n   KIS_APP_SECRET=여기에_APP_SECRET");
  process.exit(1);
}
if (key.length > secret.length) console.log("⚠ APP KEY가 SECRET보다 깁니다. 두 값이 바뀌었을 수 있습니다.");

console.log("\n── 서버 함수(quotes.js) 그대로 실행: 실전 서버 ──");
const real = await runFunction("real", key, secret);
if (real.complete) {
  console.log('\n✅ 정상. 한국 종목 시세가 모두 들어왔습니다. Vercel의 KIS_ENV 는 "real".');
} else if (real.tokenRejected) {
  console.log("\n── 실전 서버가 키를 거부 → 모의 서버로도 시험 ──");
  const mock = await runFunction("mock", key, secret);
  if (mock.complete) console.log('\n→ 모의 앱 키입니다. Vercel의 KIS_ENV 를 "mock" 으로 바꾸세요.');
  else console.log("\n❌ 두 서버 모두 실패. 위 errors 의 코드를 확인하세요.");
} else {
  console.log("\n❌ 일부 또는 전부 실패. 위 errors 의 코드를 확인하세요.");
}
