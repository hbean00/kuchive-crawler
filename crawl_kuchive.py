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


def parse_int(text: str):
    """콤마/공백/'명' 등 섞여 있어도 숫자만 추출해 int로 변환. 없으면 None."""
    if text is None:
        return None
    s = re.sub(r"[^\d]", "", str(text))
    return int(s) if s else None


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
        apply_start, apply_end = parse_period_to_dates(apply_period)

        # encSddpbSeq
        enc = None
        if title_a.has_attr("data-params"):
            m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', title_a["data-params"])
            if m:
                enc = m.group(1)

        # URL (enc 기반) - "맨 뒤"로 append할 거라 변수만 준비
        # url = ""
        # if enc:
        #     url = f"{BASE}/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmView.do?encSddpbSeq={enc}"
                # encSddpbSeq + paginationInfo.currentPageNo
        enc = None
        current_page_no = None

        # 1) title_a에서 먼저 시도
        if title_a.has_attr("data-params"):
            dp = title_a["data-params"]
            m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', dp)
            if m:
                enc = m.group(1)

            m2 = re.search(r'"paginationInfo\.currentPageNo"\s*:\s*"([^"]+)"', dp)
            if m2:
                current_page_no = m2.group(1)

        # 2) title_a에 pageNo가 없으면 detailBtn 중 paginationInfo 있는 걸 탐색
        if current_page_no is None:
            for a in li.select("a.detailBtn[data-params]"):
                dp = a.get("data-params", "")
                if enc is None:
                    m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', dp)
                    if m:
                        enc = m.group(1)

                m2 = re.search(r'"paginationInfo\.currentPageNo"\s*:\s*"([^"]+)"', dp)
                if m2:
                    current_page_no = m2.group(1)

                if enc and current_page_no:
                    break

        # URL 생성 (실제 접근 가능한 Info 페이지)
        url = build_info_url(enc, current_page_no)


        # ===== 인원 파싱 (현재 신청 / 대기 / 정원) =====
        applicants = waitlist = capacity = None
        cnt_li = li.select_one("div.etc_cont li.cnt")
        if cnt_li:
            for dl in cnt_li.select("dl"):
                dt = safe_text(dl.select_one("dt"))
                dd = safe_text(dl.select_one("dd"))
                if "신청자" in dt:
                    applicants = parse_int(dd)
                elif "대기자" in dt:
                    waitlist = parse_int(dd)
                elif "모집정원" in dt:
                    capacity = parse_int(dd)

        # ===== results.append: 요청한 키 순서로 정렬 =====
        results.append({
            "title": title,

            # 제목 바로 다음: 인원 3종
            "capacity": capacity,           # 모집정원
            "applicants": applicants,       # 현재 신청 인원
            "waitlist": waitlist,           # 대기 인원

            "status": status,
            "apply_start": apply_start,
            "apply_end": apply_end,
            "program_type": category,
            "org": org,
            "d_day": d_day,

            # 링크는 맨 뒤
            "url": url,
            "encSddpbSeq": enc,
        })

    return results
    
def build_info_url(enc: str, page_no: str | int | None) -> str:
    if not enc:
        return ""
    p = str(page_no) if page_no else "1"
    return (
        f"{BASE}/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/"
        f"findIcmpNsbjtPgmInfo.do?paramStart=paramStart&encSddpbSeq={enc}"
        f"&paginationInfo.currentPageNo={p}"
    )


def main():
    all_results = []

    for page in (1, 2, 3):
        html = fetch_page(page)
        programs = parse_programs(html)
        print(f"\n===== PAGE {page} : {len(programs)} items =====")
        for p in programs:
            print(f"- [{p['d_day'] if p['d_day'] is not None else 'D-?'}] {p['title']} / {p['org']} / {p['program_type']}")
            print(f"  인원(정원/신청/대기): {p.get('capacity')} / {p.get('applicants')} / {p.get('waitlist')}")
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
