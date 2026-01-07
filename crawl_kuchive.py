import re
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

BASE = "https://kuchive.korea.ac.kr"
LIST_URL = BASE + "/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmList.do"

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KUchiveCrawler/1.0; +https://github.com/)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def safe_text(el):
    return el.get_text(strip=True) if el else ""


def parse_d_day(text: str):
    m = re.search(r"D-(\d+)", text or "")
    return int(m.group(1)) if m else None


def normalize_status(status_text: str) -> str:
    t = (status_text or "").strip()
    if "모집중" in t:
        return "모집중"
    if "마감" in t:
        return "마감"
    if "종료" in t:
        return "종료"
    return "기타"


def parse_period_to_dates(period: str):
    """
    입력 예:
      "2025.12.30 00:00 ~ 2026.01.13 23:59"
    출력:
      ("2025-12-30", "2026-01-13")
    날짜를 못 뽑으면 (None, None)
    """
    if not period:
        return None, None

    # 날짜(yyyy.mm.dd) 2개를 찾는다
    dates = re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", period)
    if len(dates) >= 2:
        s = "-".join(dates[0])
        e = "-".join(dates[1])
        return s, e
    return None, None


def fetch_page(page_no: int) -> str:
    params = dict(PARAMS_TEMPLATE)
    params["paginationInfo.currentPageNo"] = str(page_no)
    r = requests.get(LIST_URL, params=params, headers=HEADERS, timeout=20)
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

        status_btn = li.select_one("div.label_box a.btn01")
        status_text = safe_text(status_btn)
        d_day = parse_d_day(status_text)
        status = normalize_status(status_text)

        period_dds = li.select("div.etc_cont li.date dd, div.etc_cont li.ac_date dd")
        apply_period = safe_text(period_dds[0]) if len(period_dds) > 0 else ""

        # encSddpbSeq
        enc = None
        if title_a.has_attr("data-params"):
            m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', title_a["data-params"])
            if m:
                enc = m.group(1)

        # URL (enc 기반)
        url = ""
        if enc:
            url = f"{BASE}/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmView.do?encSddpbSeq={enc}"

        apply_start, apply_end = parse_period_to_dates(apply_period)

        results.append({
            # Notion 매핑용 키(최종)
            "title": title,
            "status": status,
            "apply_start": apply_start,  # YYYY-MM-DD or None
            "apply_end": apply_end,
            "program_type": category,
            "org": org,
            "encSddpbSeq": enc,
            "url": url,
            "d_day": d_day,
        })

    return results


def main():
    all_results = []

    for page in (1, 2, 3):
        html = fetch_page(page)
        programs = parse_programs(html)
        print(f"\n===== PAGE {page} : {len(programs)} items =====")
        for p in programs:
            print(f"- [{p['d_day'] if p['d_day'] is not None else 'D-?'}] {p['title']} / {p['org']} / {p['program_type']}")
            print(f"  상태: {p['status']}")
            print(f"  Apply Start: {p['apply_start']}, Apply End: {p['apply_end']}")
            if p["encSddpbSeq"]:
                print(f"  encSddpbSeq: {p['encSddpbSeq']}")

        all_results.extend(programs)

    # dedup: encSddpbSeq 기준
    dedup = {}
    for it in all_results:
        key = it.get("encSddpbSeq") or f"title::{it.get('title','')}"
        dedup[key] = it
    all_results = list(dedup.values())

    out_path = "kuchive_items.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nTOTAL (deduped): {len(all_results)}")
    print(f"SAVED: {out_path}")


if __name__ == "__main__":
    main()
