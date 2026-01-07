import os
import re
import json
import requests
from datetime import datetime

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]  # database id (32 chars with hyphens or without both ok)

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# ====== 너의 크롤러 결과 JSON 파일 경로 (원하는대로) ======
CRAWL_JSON_PATH = "kuchive_items.json"


def parse_apply_period(period_text: str):
    """
    예: '2025.12.08 13:25 ~ 2026.01.16 15:00'
    Notion date는 ISO 형식 'YYYY-MM-DDTHH:MM:SS' 권장(초 없어도 통과되는 경우가 많음)
    """
    if not period_text:
        return None, None

    # 공백/nbsp 등 정리
    t = period_text.replace("\xa0", " ").strip()
    parts = [p.strip() for p in t.split("~")]
    if len(parts) != 2:
        return None, None

    def to_iso(s):
        # 'YYYY.MM.DD HH:MM' -> 'YYYY-MM-DDTHH:MM:00'
        s = s.strip()
        m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})", s)
        if not m:
            return None
        yyyy, mm, dd, HH, MM = m.groups()
        return f"{yyyy}-{mm}-{dd}T{HH}:{MM}:00"

    return to_iso(parts[0]), to_iso(parts[1])


def notion_db_query(filter_payload: dict):
    url = f"{NOTION_API}/databases/{NOTION_DB_ID}/query"
    r = requests.post(url, headers=HEADERS, data=json.dumps(filter_payload), timeout=30)
    r.raise_for_status()
    return r.json()


def notion_create_page(properties: dict):
    url = f"{NOTION_API}/pages"
    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": properties}
    r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()


def notion_update_page(page_id: str, properties: dict):
    url = f"{NOTION_API}/pages/{page_id}"
    payload = {"properties": properties}
    r = requests.patch(url, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()


def query_page_by_enc(enc: str):
    # encSddpbSeq 컬럼이 "텍스트(rich_text)" 여야 함
    payload = {
        "filter": {
            "property": "encSddpbSeq",
            "rich_text": {"equals": enc}
        }
    }
    data = notion_db_query(payload)
    results = data.get("results", [])
    return results[0] if results else None


def build_properties(item: dict):
    """
    item 예시 키:
      title, org, category, status_text, d_day, apply_period, run_period, encSddpbSeq
    + URL은 encSddpbSeq 기반으로 만들어 넣을 수도 있음
    """
    name = item.get("title", "")
    org = item.get("org", "")
    program_type = item.get("category", "")  # 네 크롤러에서 category가 프로그램 유형(워크샵/특강...)로 들어옴
    enc = item.get("encSddpbSeq", "")
    dday = item.get("d_day", None)

    apply_start, apply_end = parse_apply_period(item.get("apply_period", ""))

    # 상세 URL (Info.do 규칙이 /List.do -> /Info.do 였지)
    # enc만 있으면 Info.do로 직접 접근 가능 (파라미터 방식은 사이트에서 쓰는 방식 그대로)
    url = ""
    if enc:
        url = (
            "https://kuchive.korea.ac.kr/ptfol/imng/icmpNsbjtPgm/"
            "5a2da4784090946376d0733cab816f04/findIcmpNsbjtPgmInfo.do"
            f"?encSddpbSeq={enc}"
        )

    props = {
        "Name": {"title": [{"text": {"content": name}}]},
        "org": {"rich_text": [{"text": {"content": org}}]},
        "encSddpbSeq": {"rich_text": [{"text": {"content": enc}}]},
        "URL": {"url": url or None},
    }

    # D-day (숫자) : Notion number
    if dday is None:
        props["D-day"] = {"number": None}
    else:
        props["D-day"] = {"number": int(dday)}

    # Apply Start / Apply End : Notion date
    props["Apply Start"] = {"date": {"start": apply_start}} if apply_start else {"date": None}
    props["Apply End"] = {"date": {"start": apply_end}} if apply_end else {"date": None}

    # Select (선택) : 단일 select
    # 네가 “Select는 선택”이라고 했으니 기본은 모집상태(모집중/마감 등)로 넣는 걸 추천
    # status_text 예: "모집중  D-9" -> "모집중"만 추출
    st = item.get("status_text", "")
    st_clean = st.split()[0] if st else ""
    props["Select"] = {"select": {"name": st_clean}} if st_clean else {"select": None}

    # Program type : 다중선택(multi_select)
    # program_type 예: "워크샵/특강/세미나" -> 그대로 하나의 태그로 넣음(원하면 분해도 가능)
    if program_type:
        props["Program type"] = {"multi_select": [{"name": program_type}]}
    else:
        props["Program type"] = {"multi_select": []}

    return props


def upsert_item(item: dict):
    enc = item.get("encSddpbSeq") or ""
    existing = query_page_by_enc(enc) if enc else None
    props = build_properties(item)

    if existing:
        page_id = existing["id"]
        notion_update_page(page_id, props)
        return "updated"
    else:
        notion_create_page(props)
        return "created"


def main():
    with open(CRAWL_JSON_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    created = 0
    updated = 0
    for it in items:
        res = upsert_item(it)
        if res == "created":
            created += 1
        else:
            updated += 1

    print(f"Done. created={created}, updated={updated}, total={len(items)}")


if __name__ == "__main__":
    main()
