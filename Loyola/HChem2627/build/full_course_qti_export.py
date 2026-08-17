#!/usr/bin/env python3
"""
full_course_qti_export.py — create a WHOLE-COURSE QTI content export (no
per-quiz selection, since New Quizzes don't have classic quiz ids to select
by -- confirmed via list_new_quizzes.py returning 0 quizzes for this
course). Polls until done, then downloads the resulting zip.

This does not change anything in Canvas -- it only packages existing
content into a file you can download. Course exports can take a few
minutes for a full year's worth of content; this script polls every 5s.

USAGE
  export CANVAS_TOKEN=...
  python3 full_course_qti_export.py
"""
import os, sys, re, json, time, urllib.request, urllib.parse

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"
tok = os.environ.get("CANVAS_TOKEN")
if not tok:
    sys.exit("export CANVAS_TOKEN=... first.")

def api(path, method="GET", body=None, full_url=None):
    url = full_url or f"{BASE}/api/v1/{path}"
    data = urllib.parse.urlencode(body, doseq=True).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

EXPORT_TYPE = sys.argv[1] if len(sys.argv) > 1 else "common_cartridge"
# common_cartridge is what Canvas's "Copy this Course" uses internally, and
# course copies reliably bring New Quizzes along -- more likely to resolve
# New Quizzes content than the narrower "qti" export type. Pass "qti" as an
# argv if you want to try that instead: python3 full_course_qti_export.py qti
print(f"Creating full-course {EXPORT_TYPE} export (whole course, no quiz filter)...")
export = api(f"courses/{COURSE_ID}/content_exports", "POST", {"export_type": EXPORT_TYPE})
export_id = export["id"]
progress_url = export.get("progress_url")
print(f"export id {export_id}, polling progress...")

while True:
    time.sleep(5)
    status = api(None, full_url=progress_url) if progress_url else api(f"courses/{COURSE_ID}/content_exports/{export_id}")
    workflow = status.get("workflow_state")
    pct = status.get("completion")
    print(f"  ... {workflow} {f'{pct}%' if pct is not None else ''}")
    if workflow in ("completed", "failed"):
        break

if workflow == "failed":
    sys.exit("export failed -- check the course for content types Canvas can't export.")

# fetch the export object again for the attachment url
export = api(f"courses/{COURSE_ID}/content_exports/{export_id}")
att = export.get("attachment")
if not att:
    sys.exit(f"export completed but no attachment found. Full response:\n{json.dumps(export, indent=1)}")

url = att["url"]
fname = att.get("filename", f"course_{COURSE_ID}_qti_export.zip")
print(f"downloading {fname} ...")
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
with urllib.request.urlopen(req) as r, open(fname, "wb") as f:
    f.write(r.read())
print(f"saved {fname} ({os.path.getsize(fname)} bytes)")
