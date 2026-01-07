import os
import json
from notion_client import Client

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DB_ID"]
JSON_PATH = os.environ.get("KUCHIVE_JSON", "kuchive_items.json")

notion = Client(auth=NOTION_TOKEN)


def query_page_by_enc(enc: str):
    """
    encSddpbSeq(text) 프로퍼티가 enc와 같은 페이지를 찾는다.
    """
    if not enc:
        return None

    resp = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "property": "encSddpbSeq",
            "rich_text": {"equals": enc},
        },
    )
    results = resp.get("results", [])
    return results[0] if results else None


def build_properties(item: dict):
    """
    네 DB 스키마에 정확히 매핑
    - Name: title
    - Select: select
    - Apply Start/End: date
    - Program type/org/encSddpbSeq: text
    - URL: url
    - D-day: number
    """
    props = {
        "Name": {
            "title": [{"text": {"content": item.get("title", "")[:2000]}}],
        },
        "Select": {
            "select": {"name": item.get("status", "기타")},
        },
        "Program type": {
            "multi_select": [
                {"name": item.get("program_type", "기타")}
            ]
        },
        "org": {
            "rich_text": [{"text": {"content": item.get("org", "")[:2000]}}],
        },
        "encSddpbSeq": {
            "rich_text": [{"text": {"content": (item.get("encSddpbSeq") or "")[:2000]}}],
        },
        "URL": {
            "url": item.get("url") or None,
        },
        "D-day": {
            "number": item.get("d_day") if isinstance(item.get("d_day"), int) else None,
        },
    }

    # Date는 None이면 프로퍼티를 아예 빼는 게 가장 안전(노션 오류 방지)
    if item.get("apply_start"):
        props["Apply Start"] = {"date": {"start": item["apply_start"]}}
    if item.get("apply_end"):
        props["Apply End"] = {"date": {"start": item["apply_end"]}}

    return props


def upsert_item(item: dict):
    enc = item.get("encSddpbSeq")
    props = build_properties(item)

    existing = query_page_by_enc(enc) if enc else None
    if existing:
        notion.pages.update(page_id=existing["id"], properties=props)
        return "updated"
    else:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties=props,
        )
        return "created"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    created = 0
    updated = 0

    for it in items:
        result = upsert_item(it)
        if result == "created":
            created += 1
        else:
            updated += 1

    print(f"SYNC DONE. created={created}, updated={updated}, total={len(items)}")


if __name__ == "__main__":
    main()
