import os
import json
import requests

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
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
    # Select 컬럼 타입이 checkbox라고 가정(원하면 select로도 바꿔줄게)
    props = {
        "Name": {"title": [{"text": {"content": it.get("title", "")[:200]}}]},
        "Select": {"checkbox": False},

        "Apply Start": {"date": {"start": it.get("apply_start")}} if it.get("apply_start") else {"date": None},
        "Apply End": {"date": {"start": it.get("apply_end")}} if it.get("apply_end") else {"date": None},

        # 핵심: multi_select
        "Program type": {"multi_select": [{"name": it.get("program_type", "기타")}]},

        "org": {"rich_text": [{"text": {"content": it.get("org", "")}}]},
        "encSddpbSeq": {"rich_text": [{"text": {"content": it.get("encSddpbSeq", "")}}]},

        "URL": {"url": it.get("url", "")},
        "D-day": {"number": it.get("d_day")} if it.get("d_day") is not None else {"number": None},
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
