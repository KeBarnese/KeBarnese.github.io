#!/usr/bin/env python3
"""
test_new_quiz_items.py — one-off check: can this CANVAS_TOKEN read New Quiz
items (question text + answer key) via the New Quiz Items API?

USAGE
  export CANVAS_TOKEN=...
  python3 test_new_quiz_items.py 266475
  (pass any assignment id for a New Quiz you want to test against)
"""
import os, sys, json, urllib.request

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"

if len(sys.argv) != 2:
    sys.exit("usage: python3 test_new_quiz_items.py <assignment_id>")
aid = sys.argv[1]

tok = os.environ.get("CANVAS_TOKEN")
if not tok:
    sys.exit("export CANVAS_TOKEN=... first.")

url = f"{BASE}/api/quiz/v1/courses/{COURSE_ID}/quizzes/{aid}/items"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
try:
    with urllib.request.urlopen(req) as r:
        body = r.read()
        print(f"HTTP {r.status}")
        print(json.dumps(json.loads(body), indent=1)[:3000])
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}")
    print(e.read().decode()[:1000])
except Exception as e:
    print("Request failed:", e)
