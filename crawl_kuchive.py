import re
import requests
from bs4 import BeautifulSoup
import json

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
    # 예: "모집중  D-9"
    m = re.search(r"D-(\d+)", text)
    return int(m.group(1)) if m else None


def normalize_status(status_text: str) -> str:
    """
    노션 Select에 넣을 값으로 정규화 (필요하면 너 DB 옵션에 맞춰 조정)
    """
    t = (status_text or "").strip()
    if "모집중" in t:
        return "모집중"
    if "마감" in t:
        return "마감"
    if "종료" in t:
        return "종료"
    return "기타"


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

        # 상태
        status_btn = li.select_one("div.label_box a.btn01")
        status_text = safe_text(status_btn)
        d_day = parse_d_day(status_text)
        status = normalize_status(status_text)

        # 기간
        period_dds = li.select("div.etc_cont li.date dd, div.etc_cont li.ac_date dd")
        apply_period = safe_text(period_dds[0]) if len(period_dds) > 0 else ""
        run_period = safe_text(period_dds[1]) if len(period_dds) > 1 else ""

        # encSddpbSeq 추출
        enc = None
        if title_a.has_attr("data-params"):
            m = re.search(r'"encSddpbSeq"\s*:\s*"([^"]+)"', title_a["data-params"])
            if m:
                enc = m.group(1)

        # 상세 URL(없으면 빈 문자열)
        # enc 값이 있으면 노션에 링크로 넣기 좋아서 만들어둠
        # (사이트가 실제로 이 패턴을 쓰는지 100% 확신은 없어서 enc 없으면 비움)
        detail_url = ""
        if enc:
            # 너가 이전에 말한 "상세 페이지 URL 규칙"을 이미 알고 있다면 여기만 맞춰주면 됨
            # 안전하게는 enc만 기록해두고 notion_sync에서 클릭 가능한 링크를 구성해도 됨.
            detail_url = f"{BASE}/ptfol/imng/icmpNsbjtPgm/5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmView.do?encSddpbSeq={enc}"

        results.append({
            # 원본(네가 이미 뽑는 것)
            "title": title,
            "org": org,
            "category": category,
            "status_text": status_text,
            "d_day": d_day,
            "apply_period": apply_period,
            "run_period": run_period,
            "encSddpbSeq": enc,

            # 노션 싱크 편의용(추가 필드)
            "status": status,           # Select에 넣기 좋게
            "ptype": category or "기타", # Program Type에 바로 넣을 용도
            "url": detail_url,          # URL 컬럼
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
            print(f"  상태: {p['status_text']}")
            print(f"  신청기간: {p['apply_period']}")
            print(f"  운영기간: {p['run_period']}")
            if p["encSddpbSeq"]:
                print(f"  encSddpbSeq: {p['encSddpbSeq']}")
                print(f"  url: {p['url']}")

        all_results.extend(programs)

    # 중복 제거(혹시 페이지 겹침 대비): enc 기준으로 마지막 값으로 덮어쓰기
    dedup = {}
    for it in all_results:
        key = it.get("encSddpbSeq") or f"title::{it.get('title','')}"
        dedup[key] = it
    all_results = list(dedup.values())

    # JSON 저장 (노션 싱크에서 바로 사용)
    out_path = "kuchive_items.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nTOTAL (deduped): {len(all_results)}")
    print(f"SAVED: {out_path}")


if __name__ == "__main__":
    main()
