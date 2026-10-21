# 배포 방법 (Vercel 무료 / Netlify)

이 폴더의 `index.html` 하나만 배포하면 됩니다. (빌드 불필요, 자립형 HTML)

## A. Vercel + GitHub (추천 — 같은 URL로 자동 갱신)
1. github.com 에서 새 repo 생성(예: `semi-research`) → `index.html` 업로드(드래그&드롭 가능)
2. vercel.com → Add New → Project → 그 repo Import → Deploy
3. 나오는 `https://semi-research.vercel.app` 를 폰에 저장
4. 업데이트: 새 index.html 을 GitHub repo에 올리면(덮어쓰기) Vercel이 같은 URL로 자동 재배포

## B. Vercel CLI (GitHub 없이)
1. 이 폴더에서:  npm i -g vercel  →  vercel --prod
2. 이후 업데이트: 새 index.html 로 교체 후 다시  vercel --prod  (같은 프로젝트=같은 URL)

## C. Netlify Drop (제일 간단, 1단계)
1. app.netlify.com/drop 에 index.html 드래그 → 링크 생성
2. "Claim this site"(무료 가입)로 URL 고정
3. 업데이트: 같은 사이트 Deploys에 새 index.html 재드롭

* 무료 티어 모두 개인용으로 충분. 인터넷 연결 시 차트(CDN) 정상 표시.

## 시세 자동 갱신 (2026-10-21 추가)

폰(웹)에서 페이지를 열면 시세를 자동으로 불러옵니다.

| 종목 | 어디서 | 얼마나 자주 |
|---|---|---|
| 미국 (MU, SNDK 등) | `api/quotes.js` → Alpaca 무료(IEX) 시세 | Vercel이 3시간 동안 저장해 두고 재사용. 최대 3시간마다 새로 받음 |
| 한국 (삼성전자, SK하이닉스) | `api/quotes.js` → 한국투자증권 Open API. 실패하거나 키가 없으면 `data/manual_quotes.json` 수동 입력 | 미국과 같음 (3시간) |

### 처음 한 번만 할 일 (Vercel 대시보드에서)
1. **Root Directory 확인**: Project → Settings → General → Root Directory 가 `web_deploy` 인지 확인. 다르면 `api/quotes.js` 가 서버 함수로 인식되지 않습니다.
2. **환경 변수 추가**: Project → Settings → Environment Variables. 키는 Vercel 에만 두고 코드·채팅·문서에 적지 않습니다.
   - 미국: `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (GitHub Actions secret 과 같은 Alpaca 키)
   - 한국: `KIS_APP_KEY`, `KIS_APP_SECRET` (KIS Developers 에서 발급), `KIS_ENV` = `real`(실전) 또는 `mock`(모의투자). 비우면 `real`.
   - 한쪽만 넣어도 됩니다. 넣은 쪽 시세만 나옵니다.
   - **주의**: 실전 계좌 키는 시세뿐 아니라 매매 권한도 있는 열쇠입니다. 이 함수는 시세 조회 주소만 부르지만, 키가 새면 주문이 가능할 수 있습니다. 실전 키를 쓰면 그 계좌는 시세 조회 전용으로 비워 두세요.
3. 다시 배포(Redeploy) 후 `https://<사이트>/api/quotes` 를 열어 `"quotes"` 가 보이면 성공. `"quotes not configured"` 면 2번이 안 된 것입니다. `"errors"` 에 `"KR upstream failed"` 가 있으면 KIS 키나 `KIS_ENV` 를 확인하세요(실전 키에 `mock` 을 넣거나 그 반대면 실패).

### 한국 시세 수동 입력
한국투자증권 시세가 안 들어올 때를 위한 예비입니다. `data/manual_quotes.json` 에서 종목의 `price`, `as_of`(YYYY-MM-DD), `source` 를 채워 커밋하면 됩니다. GitHub 웹/앱에서 파일을 바로 고쳐도 됩니다. 비워 두면 기존 스냅샷을 쓰고 화면에 "수동 입력 필요"가 뜹니다.

### 지원 종목 늘리기
`api/quotes.js` 의 `US_SYMBOLS`(미국) 또는 `KR_CODES`(한국, 6자리 종목코드: 이름) 에 추가합니다. 목록에 없는 티커는 요청해도 무시합니다(남이 우리 키로 다른 종목을 조회하지 못하게).

