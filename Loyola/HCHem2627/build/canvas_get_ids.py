#!/usr/bin/env python3
"""
canvas_get_ids.py  —  Honors Chemistry (Loyola course 5799)

Pulls EVERYTHING linkable out of the Canvas course so the schedule web page
can point at it:

  * Assignments            -> graded work, incl. graded quizzes ("New Quizzes"
                              and graded Classic Quizzes show up here)
  * Classic Quizzes        -> the /quizzes/:id list, incl. UNGRADED practice
                              quizzes that never appear as assignments
  * Files                  -> study guides / review PDFs / packets

It prints a full inventory (type | id | title | url) and then emits three
paste-ready JavaScript blocks for index.html:

    ASSIGNMENT_IDS   ->  {CANVAS}/assignments/:id
    QUIZ_IDS         ->  {CANVAS}/quizzes/:id      (classic/practice quizzes)
    FILE_IDS         ->  {CANVAS}/files/:id

The auto-generated keys are slugs of the Canvas titles. Rename them in the
emitted block to match the keys your schedule uses (e.g. HW_1, HW_1_practice,
Quiz_4, Exam_1_Review) — the page looks work up by those keys.

------------------------------------------------------------------------------
SETUP (one time)
  1. In Canvas: Account -> Settings -> "+ New Access Token". Copy the token.
  2. Export it so the script can read it (do NOT hard-code it in the file):
         export CANVAS_TOKEN='paste-token-here'
  3. Run:
         python3 canvas_get_ids.py
     Optional: write the emitted JS to a file as well:
         python3 canvas_get_ids.py > canvas_ids_output.txt

Only the standard library is used (urllib) — no pip install needed.
Nothing is modified in Canvas; every request is read-only (GET).
------------------------------------------------------------------------------
"""

import os
import re
import sys
import json
import urllib.request
import urllib.parse
import urllib.error

# ---- configuration ----------------------------------------------------------
BASE      = "https://loyolahs.instructure.com"
COURSE_ID = "6624"                       # Honors Chemistry 26-27 (new course; copied from 5799)
TOKEN     = os.environ.get("CANVAS_TOKEN")
PER_PAGE  = 100                          # Canvas max page size

if not TOKEN:
    sys.exit("ERROR: set CANVAS_TOKEN first  ->  export CANVAS_TOKEN='...'")


# ---- tiny paginated GET helper ---------------------------------------------
def canvas_get(path, params=None):
    """GET an API path, following Link: rel="next" pagination. Returns a list."""
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    out = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            sys.exit(f"ERROR {e.code} fetching {url}\n{e.read().decode('utf-8', 'replace')}")
        out.extend(data if isinstance(data, list) else [data])
        # find the rel="next" URL in the Link header, if any
        nxt = None
        for part in link.split(","):
            m = re.search(r'<([^>]+)>;\s*rel="next"', part)
            if m:
                nxt = m.group(1)
                break
        url = nxt
    return out


def slug(title):
    """Turn a Canvas title into a safe-ish JS key. Rename after."""
    s = re.sub(r"[^0-9A-Za-z]+", "_", (title or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "UNTITLED"


# ---- pull the three inventories --------------------------------------------
print(f"# Fetching course {COURSE_ID} from {BASE} ...\n", file=sys.stderr)

assignments = canvas_get(f"courses/{COURSE_ID}/assignments",
                         {"per_page": PER_PAGE})
quizzes     = canvas_get(f"courses/{COURSE_ID}/quizzes",
                         {"per_page": PER_PAGE})
files       = canvas_get(f"courses/{COURSE_ID}/files",
                         {"per_page": PER_PAGE})

# Graded classic quizzes surface in BOTH lists; note their assignment ids so we
# can avoid emitting a duplicate link. (Assignment link is usually the nicer one.)
graded_quiz_ids = {a.get("quiz_id") for a in assignments if a.get("quiz_id")}


# ---- human-readable inventory ----------------------------------------------
def show(title, rows):
    print(f"\n{'='*78}\n{title}  ({len(rows)})\n{'='*78}")
    for r in rows:
        print(r)

show("ASSIGNMENTS  (graded work + graded quizzes)",
     [f"  {a['id']:>9}  {a.get('name','')[:60]:60}  {a.get('html_url','')}"
      for a in assignments])

show("CLASSIC QUIZZES  (includes ungraded PRACTICE quizzes)",
     [f"  {q['id']:>9}  {q.get('title','')[:56]:56}  "
      f"{'[also assignment]' if q['id'] in graded_quiz_ids else '[quiz-only]  '}  "
      f"{q.get('html_url','')}"
      for q in quizzes])

show("FILES  (study guides / review PDFs / packets)",
     [f"  {f['id']:>9}  {f.get('display_name','')[:60]:60}  "
      f"{BASE}/courses/{COURSE_ID}/files/{f['id']}"
      for f in files])


# ---- paste-ready JS blocks --------------------------------------------------
def emit(varname, pairs, comment):
    print(f"\n/* {comment} */")
    print(f"const {varname} = {{")
    seen = {}
    for key, cid in pairs:
        k = key
        n = 2
        while k in seen:                 # de-dupe collided slugs
            k = f"{key}_{n}"; n += 1
        seen[k] = cid
        print(f"  '{k}': {cid},")
    print("};")

print("\n\n" + "#"*78)
print("# PASTE-READY BLOCKS  — rename keys to match your schedule, then paste")
print("# into index.html.  Practice quizzes usually live in QUIZ_IDS.")
print("#"*78)

emit("ASSIGNMENT_IDS",
     [(slug(a.get("name")), a["id"]) for a in assignments],
     "from canvas_get_ids.py — graded assignments & graded quizzes -> /assignments/:id")

emit("QUIZ_IDS",
     [(slug(q.get("title")), q["id"]) for q in quizzes if q["id"] not in graded_quiz_ids],
     "from canvas_get_ids.py — classic/practice quizzes -> /quizzes/:id")

emit("FILE_IDS",
     [(slug(os.path.splitext(f.get("display_name",""))[0]), f["id"]) for f in files],
     "from canvas_get_ids.py — files (study guides / packets) -> /files/:id")

print("\n# done.", file=sys.stderr)
