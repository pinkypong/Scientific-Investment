"""OpenDART API 참고.

인증: crtfc_key 필요 (https://opendart.fss.or.kr 무료 발급). → 환경변수 OPENDART_API_KEY.

엔드포인트:
  /api/fnlttSinglAcntAll.json  단일회사 전체 재무제표
     params: crtfc_key, corp_code(8), bsns_year(4), reprt_code, fs_div(CFS|OFS)
  /api/corpCode.xml            corp_code 마스터 (zip)

reprt_code:  11011 사업보고서(연간) · 11012 반기 · 11013 1분기 · 11014 3분기
status:  "000" 정상 · "013" 데이터없음 · "010" 키오류 · "020" 사용한도초과 · "011" 미등록키

응답 list[] 주요 필드:
  rcept_no · bsns_year · sj_div(BS/IS/CIS/CF) · sj_nm · account_id · account_nm
  thstrm_nm · thstrm_amount(당기) · frmtrm_amount(전기) · thstrm_add_amount(당기누적)
  currency (보통 "KRW")
"""

BASE = "https://opendart.fss.or.kr/api"

STATUS_MSG = {
    "000": "정상", "010": "등록되지 않은 키", "011": "사용할 수 없는 키(오류)",
    "013": "조회 데이터 없음", "020": "요청 제한 초과", "100": "필드 부적절", "800": "점검중",
}

# sj_div → 재무제표 종류
SJ = {"BS": "balance_sheet", "IS": "income_statement", "CIS": "income_statement",
      "CF": "cash_flow", "SCE": "equity_changes"}

FILING_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
