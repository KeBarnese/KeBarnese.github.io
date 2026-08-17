#!/usr/bin/env python3
"""
test_item_bank.py — probe for an (undocumented) endpoint that returns an
item bank's actual questions, since /items on the assignment only returned
a bank reference (id, title, entry_count) not the questions themselves.

Tries a few plausible URL shapes against bank id 3471 -- none of these are
confirmed to exist; this is exploratory. A 200 with question-looking JSON
means it worked; 404/403/anything else means that shape is wrong or blocked.

USAGE
  export CANVAS_TOKEN=...
  python3 test_item_bank.py 3471
"""
import os, sys, json, urllib.request

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"

if len(sys.argv) != 2:
    sys.exit("usage: python3 test_item_bank.py <bank_id>")
bank_id = sys.argv[1]

tok = os.environ.get("CANVAS_TOKEN")
if not tok:
    sys.exit("export CANVAS_TOKEN=... first.")

CANDIDATES = [
    f"{BASE}/api/quiz/v1/item_banks/{bank_id}/items",
    f"{BASE}/api/quiz/v1/courses/{COURSE_ID}/item_banks/{bank_id}/items",
    f"{BASE}/api/quiz/v1/item_banks/{bank_id}",
    f"{BASE}/api/quiz/v1/courses/{COURSE_ID}/item_banks/{bank_id}",
]

for url in CANDIDATES:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    print(f"\n--- {url} ---")
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            print(f"HTTP {r.status}")
            print(json.dumps(json.loads(body), indent=1)[:1500])
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}")
    except Exception as e:
        print("Request failed:", e)
