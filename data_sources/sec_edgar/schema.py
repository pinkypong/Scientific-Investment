"""SEC EDGAR API 참고.

인증 불필요 (공개). 단 SEC 정책상 User-Agent 헤더에 이름+이메일 필수. rate ~10 req/s.

엔드포인트:
  https://www.sec.gov/files/company_tickers.json                         ticker → CIK
  https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/{tag}.json   개념 1개, 전체 기간
  https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json             전체 facts (대용량)
  https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=...      filing 목록

companyconcept 응답:
  { cik, taxonomy:'us-gaap', tag, label, description,
    units: { 'USD': [ {start,end,val,accn,fy,fp,form,filed,frame}, ... ] } }
"""

BASE = "https://data.sec.gov/api/xbrl"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# flow metric 의 허용 duration(일) 범위
QUARTER_DAYS = (80, 100)
ANNUAL_DAYS = (350, 380)


def filing_index_url(cik: int, accession: str) -> str:
    if not accession:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}-index.htm"
