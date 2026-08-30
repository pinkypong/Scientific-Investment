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
