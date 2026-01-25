import os
import json
import requests

from datetime import datetime, timezone, timedelta


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

def _extract_title(page: dict) -> str:
    props = page.get("properties", {})
    # title 타입 속성 찾아서 반환
    for v in props.values():
        if v.get("type") == "title":
            arr = v.get("title", [])
            return "".join([t.get("plain_text", "") for t in arr]) or "(no title)"
    return "(no title)"


def _get_date_start(page: dict, prop: str):
    p = page.get("properties", {}).get(prop)
    if not p or p.get("type") != "date":
        return None
    d = p.get("date")
    if not d:
        return None
    return d.get("start")


def _has_closed_tag(page: dict) -> bool:
    p = page.get("properties", {}).get(STATUS_PROP)
    if not p:
        return False

    # 네 스키마: multi_select
    if p.get("type") == "multi_select":
        tags = p.get("multi_select", [])
        return any(t.get("name") == CLOSED_TAG for t in tags)

    # 혹시 Status 타입으로 바꾼 경우도 대비
    if p.get("type") == "status":
        st = p.get("status")
        return (st or {}).get("name") == CLOSED_TAG

    return False


def notion_query_all_pages(filter_payload: dict = None):
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    results = []
    start_cursor = None

    while True:
        payload = {"page_size": 100}
        if filter_payload:
            payload.update(filter_payload)
        if start_cursor:
            payload["start_cursor"] = start_cursor

        r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if not r.ok:
            print("DB QUERY FAILED:", r.status_code, r.text)
            print("SENT PAYLOAD:", json.dumps(payload, ensure_ascii=False, indent=2))
            r.raise_for_status()

        data = r.json()
        results.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")

    return results


def mark_expired_as_closed():
    # 정책: "마감직전 = 마감 당일"
    # => Apply End가 "오늘(00:00 KST)" 보다 이전이면 마감으로 전환
    now_kst = datetime.now(tz=KST)
    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    cutoff_iso = today_start_kst.isoformat()

    filter_payload = {
        "filter": {
            "property": APPLY_END_PROP,
            "date": {"before": cutoff_iso}
        }
    }

    pages = notion_query_all_pages(filter_payload=filter_payload)
    print(f"[CLOSE] candidates(before {cutoff_iso}): {len(pages)}")

    to_close = []
    for page in pages:
        if _has_closed_tag(page):
            continue
        page_id = page["id"]
        title = _extract_title(page)
        apply_end = _get_date_start(page, APPLY_END_PROP)
        to_close.append((page_id, title, apply_end))

    print(f"[CLOSE] to update: {len(to_close)}")
    for page_id, title, apply_end in to_close:
        print(f" - {title} | Apply End={apply_end} -> {CLOSED_TAG}")

    if DRY_RUN_CLOSE:
        print("[CLOSE] DRY_RUN_CLOSE=True, no updates applied.")
        return

    for page_id, _, _ in to_close:
        props = {
            STATUS_PROP: {"multi_select": [{"name": CLOSED_TAG}]}
        }
        notion_update_page(page_id, props)

    print("[CLOSE] DONE")


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
    mark_expired_as_closed()

if __name__ == "__main__":
    main()
