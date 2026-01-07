import os
import re
import json
import requests
from datetime import datetime, timezone

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

NOTION_VERSION = "2022-06-28"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# ---------- helpers ----------
def _req(method, url, **kwargs):
    r = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # 에러 원인 바로 보이게
        print("Notion API Error:", r.status_code, r.text)
        raise
    return r.json()

def parse_korean_datetime(s: str) -> str | None:
    """
    '2026.01.16 15:00' -> '2026-01-16T15:00:00+09:00'
    """
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})", s)
    if not m:
        return None
    y, mo, d, hh, mm = map(int, m.groups())
    # KST +09:00
    return f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mm:02d}:00+09:00"

def query_by_enc(enc: str) -> str | None:
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "encSddpbSeq",
            "rich_text": {"equals": enc}
        }
    }
    data = _req("POST", url, json=payload)
    results = data.get("results", [])
    return results[0]["id"] if results else None

def make_page_properties(item: dict) -> dict:
    # DB 컬럼명 네가 만든 것과 1:1로 맞춰둠
    props = {
        "Name": {"title": [{"text": {"content": item["title"]}}]},
        "Status": {"select": {"name": item.get("status", "모집중")}},
        "Org": {"rich_text": [{"text": {"content": item.get("org", "")}}]},
        "Program Type": {"select": {"name": item.get("ptype", "기타")}},
        "encSddpbSeq": {"rich_text": [{"text": {"content": item["enc"]}}]},
        "URL": {"url": item.get("url", "")},
    }

    # Date properties
    if item.get("apply_start"):
        props["Apply Start"] = {"date": {"start": item["apply_start"]}}
    if item.get("apply_end"):
        props["Apply End"] = {"date": {"start": item["apply_end"]}}

    return props

def create_page(item: dict):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": make_page_properties(item),
    }
    _req("POST", url, json=payload)
    print(f"created: {item['enc']} | {item['title']}")

def update_page(page_id: str, item: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": make_page_properties(item)}
    _req("PATCH", url, json=payload)
    print(f"updated: {item['enc']} | {item['title']}")

def upsert(item: dict):
    page_id = query_by_enc(item["enc"])
    if page_id:
        update_page(page_id, item)
    else:
        create_page(item)

# ---------- main ----------
if __name__ == "__main__":
    """
    입력 데이터 형식(크롤러 출력 JSON 가정):
    [
      {
        "enc": "...",
        "title": "...",
        "org": "...",
        "ptype": "...",
        "apply_period": "2025.12.08 13:25 ~ 2026.01.16 15:00",
        "url": "..."
      },
      ...
    ]
    """
    input_path = os.environ.get("KUCHIVE_JSON", "kuchive_items.json")

    with open(input_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    # status 계산 예시 (원하면 더 정교화 가능)
    now = datetime.now(timezone.utc)  # 비교만 할거라 UTC로 둠
    for it in items:
        # 신청기간 파싱
        ap = it.get("apply_period", "")
        # "start ~ end" 형태에서 각각 뽑기
        start_s, end_s = None, None
        if "~" in ap:
            parts = [p.strip() for p in ap.split("~")]
            if len(parts) == 2:
                start_s, end_s = parts

        it["apply_start"] = parse_korean_datetime(start_s) if start_s else None
        it["apply_end"] = parse_korean_datetime(end_s) if end_s else None

        # 기본 status (크롤링이 모집중 탭이면 모집중으로 고정해도 됨)
        it["status"] = it.get("status", "모집중")

        upsert(it)
