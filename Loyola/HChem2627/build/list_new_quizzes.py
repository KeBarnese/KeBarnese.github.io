#!/usr/bin/env python3
"""
list_new_quizzes.py — read-only. Lists what /api/v1/courses/:id/quizzes
returns for this course, so we can see whether New Quizzes show up there
with their own quiz id (distinct from the assignment id), which is what
the standard Content Exports API's select[quizzes][] param needs.

Nothing is created/changed -- this is a GET only.

USAGE
  export CANVAS_TOKEN=...
  python3 list_new_quizzes.py            # lists everything
  python3 list_new_quizzes.py atomic     # filters titles containing "atomic"
"""
import os, sys, json, re, urllib.request

BASE, COURSE_ID = "https://loyolahs.instructure.com", "5799"
tok = os.environ.get("CANVAS_TOKEN")
if not tok:
    sys.exit("export CANVAS_TOKEN=... first.")
filt = sys.argv[1].lower() if len(sys.argv) > 1 else None

def api_get(path):
    out, url = [], f"{BASE}/api/v1/{path}"
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req) as r:
            j = json.loads(r.read())
            link = r.headers.get("Link", "")
        out += j if isinstance(j, list) else [j]
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out

quizzes = api_get(f"courses/{COURSE_ID}/quizzes?per_page=100")
print(f"{len(quizzes)} quiz(zes) returned by /courses/{COURSE_ID}/quizzes\n")
for q in quizzes:
    title = q.get("title", "")
    if filt and filt not in title.lower():
        continue
    print(f"  quiz id {q.get('id'):<10} assignment_id {str(q.get('assignment_id')):<10} "
          f"quiz_type {q.get('quiz_type'):<16} {title}")
