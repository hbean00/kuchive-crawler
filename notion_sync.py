import os
import json
import requests

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
DATABASE_ID = os.getenv("NOTION_DB_ID", "")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

def notion_query_by_enc(enc: str):
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "encSddpbSeq",
            "rich_text": {"equals": enc}
        }
    }
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    if not r.ok:
        print("QUERY FAILED:", r.status_code, r.text)
        r.raise_for_status()
    data = r.json()
    return data["results"][0] if data.get("results") else None

def notion_create_page(props: dict):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": props
    }
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    if not r.ok:
        print("CREATE FAILED:", r.status_code)
        print("RESPONSE:", r.text)          # <-- 400 원인 여기서 바로 뜸
        print("SENT PAYLOAD:", json.dumps(payload, ensure_ascii=False, indent=2))
        r.raise_for_status()
    return r.json()

def notion_update_page(page_id: str, props: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": props}
    r = requests.patch(url, headers=HEADERS, json=payload, timeout=30)
    if not r.ok:
        print("UPDATE FAILED:", r.status_code)
        print("RESPONSE:", r.text)
        print("SENT PAYLOAD:", json.dumps(payload, ensure_ascii=False, indent=2))
        r.raise_for_status()
    return r.json()

def build_props(it: dict) -> dict:
    title = (it.get("title") or "")[:200]
    d_day = it.get("d_day")
    program_type = it.get("program_type") or "기타"

    capacity = it.get("capacity")
    applicants = it.get("applicants")
    waitlist = it.get("waitlist")

    # ---- 상태 멀티셀렉트 결정 ----
    raw_status = (it.get("status") or "").strip()

    status_tags = []
    if raw_status == "마감":
        status_tags = ["마감"]
    else:
        # 모집중/기타는 수치 기반으로 재판정
        # 최악 케이스: capacity None/0이면 비교 불가 -> '신청가능'로 두되, 필요하면 '확인필요' 같은 태그로 바꿔도 됨
        if capacity is not None and capacity > 0 and applicants is not None:
            if applicants >= capacity:
                status_tags = ["정원 초과"]
            else:
                status_tags = ["신청가능"]
        else:
            status_tags = ["신청가능"]

    props = {
        # Title
        "Name": {"title": [{"text": {"content": title}}]},

        # 날짜
        "Apply Start": {"date": {"start": it.get("apply_start")}} if it.get("apply_start") else {"date": None},
        "Apply End": {"date": {"start": it.get("apply_end")}} if it.get("apply_end") else {"date": None},

        # Program type (multi_select)
        "Program type": {"multi_select": [{"name": program_type}]},

        # org / enc / url / d-day
        "org": {"rich_text": [{"text": {"content": it.get("org", "")}}]},
        "encSddpbSeq": {"rich_text": [{"text": {"content": it.get("encSddpbSeq", "")}}]},
        "D-day": {"number": d_day} if d_day is not None else {"number": None},
        "URL": {"url": it.get("url", "")},

        # ---- 인원 컬럼(숫자 타입이어야 함) ----
        "정원": {"number": capacity} if capacity is not None else {"number": None},
        "신청": {"number": applicants} if applicants is not None else {"number": None},
        "대기": {"number": waitlist} if waitlist is not None else {"number": None},

        # ---- 상태(멀티셀렉트) ----
        "상태": {"multi_select": [{"name": s} for s in status_tags]},
    }

    return props


def upsert_item(it: dict):
    enc = it.get("encSddpbSeq", "")
    if not enc:
        return "skip(no encSddpbSeq)"

    existing = notion_query_by_enc(enc)
    props = build_props(it)

    if existing:
        notion_update_page(existing["id"], props)
        return "updated"
    else:
        notion_create_page(props)
        return "created"

def main():
    if not NOTION_TOKEN or not DATABASE_ID:
        raise RuntimeError("Set NOTION_TOKEN and NOTION_DATABASE_ID as environment variables.")

    with open("kuchive_items.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    created = updated = skipped = 0
    for it in items:
        try:
            res = upsert_item(it)
            if res == "created": created += 1
            elif res == "updated": updated += 1
            else: skipped += 1
        except Exception as e:
            print("FAILED ITEM:", it.get("title"), it.get("encSddpbSeq"))
            raise

    print("DONE:", {"created": created, "updated": updated, "skipped": skipped})

if __name__ == "__main__":
    main()
