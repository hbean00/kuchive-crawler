import re
import requests
from bs4 import BeautifulSoup

BASE = "https://kuchive.korea.ac.kr"
LIST_URL = BASE + "/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmList.do"

# 네가 말한 페이지 URL 규칙 그대로 사용
PARAMS_TEMPLATE = {
    "paginationInfo.currentPageNo": None,  # 1~3
    "sort": "0001",
    "aplIngTy": "0001",
    "chkAblyCount": "0",
    "viewType": "",
    "vshOrgid": "",
    "vshOrgzNm": "",
    "nsbjtYy": "0000",
    "pgmBigCd": "0000",
    "searchPlanBigCd": "0000",
    "aplyCheck": "0000",
    "yuCoreAblyCdList": "0000",
    "acceptTy": "0000",
    "rcritStaCd": "0000",
    "searchValue": "",
    "mileageTypeSh": "",
}


def safe_text(el):
    return el.get_text(strip=True) if el else ""


def parse_d_day(text: str) -> int | None:
    # 예: "모집중  D-9"
    m = re.search(r"D-(\d+)", text)
    return int(m.group(1)) if m else None


def fetch_page(page_no: int) -> str:
    params = dict(PARAMS_TEMPLATE)
    params["paginationInfo.currentPageNo"] = str(page_no)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; KUchiveCrawler/1.0; +https://github.com/)",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    r = requests.get(LIST_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def parse_programs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div.lica_wrap > ul > li")
    results = []

    for li in items:
        title_a = li.select_one("a.tit.ellipsis")
        if not title_a:
            continue

        title = safe_text(title_a)

        org = safe_text(li.select_one("ul.major_type > li:nth-of-type(1)"))
        category = safe_text(li.select_one("ul.major_type > li:nth-of-type(2)"))

        # "모집중  D-9" 같은 버튼 텍스트
        status_btn = li.select_one("div.label_box a.btn01")
        status_text = safe_text(status_btn)
        d_day = parse_d_day(status_text)

        # 신청기간/운영기간
        # dt=신청기간, 운영기간이므로 dd를 순서대로 가져온다
        period_dds = li.select("div.etc_cont li.date dd, div.etc_cont li.ac_date dd")
        apply_period = safe_text(period_dds[0]) if len(period_dds) > 0 else ""
        run_period = safe_text(period_dds[1]) if len(period_dds) > 1 else ""

        # 상세 페이지로 갈 때 필요한 encSddpbSeq 추출 (data-params 안에 들어있음)
        # data-params='{"encSddpbSeq":"..."}'
        enc = None
        if title_a.has_attr("data-params"):
            m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', title_a["data-params"])
            if m:
                enc = m.group(1)

        results.append({
            "title": title,
            "org": org,
            "category": category,
            "status_text": status_text,
            "d_day": d_day,
            "apply_period": apply_period,
            "run_period": run_period,
            "encSddpbSeq": enc,
        })

    return results


def main():
    all_results = []
    for page in (1, 2, 3):
        html = fetch_page(page)
        programs = parse_programs(html)
        print(f"\n===== PAGE {page} : {len(programs)} items =====")
        for p in programs:
            print(f"- [{p['d_day'] if p['d_day'] is not None else 'D-?'}] {p['title']} / {p['org']} / {p['category']}")
            print(f"  신청기간: {p['apply_period']}")
            print(f"  운영기간: {p['run_period']}")
            if p["encSddpbSeq"]:
                print(f"  encSddpbSeq: {p['encSddpbSeq']}")
        all_results.extend(programs)

    print(f"\nTOTAL: {len(all_results)}")


if __name__ == "__main__":
    main()
