#!/usr/bin/env python3
"""
canvas_rename_sections.py - bring Honors Chemistry (course 6624) assignment
titles into line with the textbook section numbering, chapters 1-9.

Same conventions as your other build/ scripts: stdlib only, CANVAS_TOKEN from
the environment, course 6624 hardcoded.

*** DRY RUN BY DEFAULT.  Nothing is written unless you pass --apply. ***

    export CANVAS_TOKEN='paste-token-here'
    python3 canvas_rename_sections.py                 # preview all 27
    python3 canvas_rename_sections.py --apply         # rename them
    python3 canvas_rename_sections.py --apply --verify

SAFETY
    Every rename is keyed on the assignment ID *and* checked against the title
    Canvas currently holds.  If a title has changed since this list was built,
    that one assignment is skipped and reported - it is never overwritten blind.

*** RUN THIS TOGETHER WITH patch_schedule_sections.py ***
    build_page.py matches a schedule line to a Canvas assignment by its leading
    section number.  Renaming one side and not the other breaks the match and
    the daily-homework pill silently disappears from the calendar.
"""
import os, re, sys, json, argparse, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renames import RENAMES

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"

def api(path, method="GET", body=None):
    tok = os.environ.get("CANVAS_TOKEN") or sys.exit("set CANVAS_TOKEN first")
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    data = urllib.parse.urlencode(body, doseq=True).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {method} {url}\n{e.read().decode('utf-8')[:600]}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--verify", action="store_true")
    a = p.parse_args()

    ok, skip = [], []
    for aid, cur, new in RENAMES:
        live = api(f"courses/{COURSE_ID}/assignments/{aid}").get("name", "")
        if live == new:
            skip.append((aid, live, "already renamed")); continue
        if live != cur:
            skip.append((aid, live, f"title on Canvas is not what this list expected "
                                    f"(expected {cur!r})")); continue
        ok.append((aid, cur, new))

    print(f"\n{len(ok)} to rename, {len(skip)} skipped\n" + "-"*78)
    for aid, cur, new in ok:
        print(f"  {aid}\n      from  {cur}\n      to    {new}")
    if skip:
        print("\nSKIPPED (not touched):")
        for aid, live, why in skip:
            print(f"  {aid}  {why}\n      Canvas currently has: {live!r}")

    if not a.apply:
        print("\n(dry run - re-run with --apply to write)")
        return
    for aid, cur, new in ok:
        api(f"courses/{COURSE_ID}/assignments/{aid}", "PUT", {"assignment[name]": new})
        print(f"  renamed {aid}")
    if a.verify:
        print("\nVERIFY:")
        for aid, cur, new in ok:
            live = api(f"courses/{COURSE_ID}/assignments/{aid}").get("name", "")
            print(f"  {aid}  {'OK ' if live == new else 'MISMATCH'}  {live}")

if __name__ == "__main__":
    main()
