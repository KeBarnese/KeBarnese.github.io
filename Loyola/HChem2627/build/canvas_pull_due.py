#!/usr/bin/env python3
"""
canvas_pull_due.py — pull the CURRENT due dates (incl. per-section overrides)
from Canvas course 6624 and write due_dates.json.  Canvas is the source of truth.

    export CANVAS_TOKEN=...
    python3 canvas_pull_due.py        # writes due_dates.json
    python3 build_page.py             # rebuild index.html from it

Run these two whenever you change a due date in Canvas and want the page to match.
Output format:  { "<assignment_id>": { "5": "YYYY-MM-DD", "6": ..., "7": ... } }
A due date with no section override is recorded for all three periods.
"""
import os, re, sys, json, datetime, urllib.request
from assignment_kind import classify
try:
    from zoneinfo import ZoneInfo; TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    TZ = None

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"
SECTION_OVERRIDE = {}          # {5: id, 6: id, 7: id} if section names lack the digit
TOK = os.environ.get("CANVAS_TOKEN") or sys.exit("set CANVAS_TOKEN first")

def api(path):
    url = f"{BASE}/api/v1/{path}"; out = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOK}"})
        with urllib.request.urlopen(req) as r:
            out += json.loads(r.read()); link = r.headers.get("Link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', link); url = m.group(1) if m else None
    return out

def local_date(due_at):
    if not due_at: return None
    dt = datetime.datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    if TZ: dt = dt.astimezone(TZ)
    return dt.date().isoformat()

# section id -> class period
secs = api(f"courses/{COURSE_ID}/sections?per_page=100")
pmap = {}
for P, sid in SECTION_OVERRIDE.items(): pmap[sid] = P
for s in secs:
    for P in (5, 6, 7):
        if s["id"] not in pmap and re.search(rf"\b{P}\b|period\s*{P}", s["name"].lower()):
            pmap[s["id"]] = P
print("sections ->", {s["id"]: s["name"] for s in secs})
print("period map ->", pmap)

# assignments with all their dates (base + per-section overrides)
out = {}
for a in api(f"courses/{COURSE_ID}/assignments?per_page=100&include[]=all_dates"):
    per = {}
    for d in a.get("all_dates", []):
        iso = local_date(d.get("due_at"))
        if not iso: continue
        if d.get("base"):                      # applies to everyone
            for P in (5, 6, 7): per.setdefault(str(P), iso)
        elif d.get("set_type") == "CourseSection" and d.get("set_id") in pmap:
            per[str(pmap[d["set_id"]])] = iso   # section override wins
    if per:
        title = a.get("name", "")
        # kind drives how build_page.py labels/places the pill (see
        # assignment_kind.py). Re-classified fresh from the title every pull
        # -- if classify() ever guesses wrong for a real title, fix the rule
        # there rather than hand-editing "kind" here, or it'll be overwritten
        # on the next pull.
        out[str(a["id"])] = {"_title": title, "kind": classify(title), **per}

out = dict(sorted(out.items(), key=lambda kv: kv[1].get("_title", "")))
json.dump(out, open("due_dates.json", "w"), indent=1)
print(f"wrote due_dates.json — {len(out)} assignments with due dates")
