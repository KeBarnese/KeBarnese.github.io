#!/usr/bin/env python3
"""
canvas_hw_due.py — audit and repair DUE DATES on the written (notebook)
Homework assignments in Honors Chemistry (Loyola course 6624).

Same conventions as your other build/ scripts (canvas_get_ids.py,
canvas_pull_due.py, canvas_set_daily_hw.py): stdlib-only (urllib), token from
the CANVAS_TOKEN environment variable, course 6624 hardcoded.

*** REPORT ONLY BY DEFAULT.  Nothing is written unless you pass --apply. ***

USAGE
    export CANVAS_TOKEN='paste-token-here'

    # 1. See the current state of every written Homework (this is the one to
    #    run first — it tells us what Homework 3 is missing and what the other
    #    homeworks look like, so we can pick a consistent date).
    python3 canvas_hw_due.py

    # 2. Preview a fix.  Give the date the work is due; the script builds one
    #    override per section that already has one, or sets the base due date
    #    if the assignment has no overrides.
    python3 canvas_hw_due.py --set 3 --due 2026-10-19
    python3 canvas_hw_due.py --id 266589 --due 2026-10-19     # same thing, by id

    # 3. Different date per period (order: 5,6,7 — whichever sections exist):
    python3 canvas_hw_due.py --set 3 --due 2026-10-08,2026-10-09,2026-10-09

    # 4. Write it.
    python3 canvas_hw_due.py --set 3 --due 2026-10-19 --apply --verify

OPTIONS
    --pattern REGEX   which assignments count as written homework
                      (default: title contains "homework" and does NOT contain
                       "daily", "practice" or "classwork" — this matches your
                       renamed "Chapter N Homework" titles)
    --set N           target "Chapter N Homework" (or "Homework ch. N")
    --id 123456       target by assignment id instead of by number
    --due DATE[,...]  YYYY-MM-DD, local time.  Due time defaults to 23:59.
    --time HH:MM      override the 23:59 due time
    --window A,B      also set available-from = due - A days (00:00) and
                      available-until = due + B days (23:59).  Omit to leave
                      unlock_at / lock_at exactly as they are.
    --apply           actually write to Canvas
    --verify          after applying, re-read and print what Canvas now holds
    --csv FILE        write the report table to CSV

WHY THIS TOUCHES OVERRIDES, NOT JUST THE ASSIGNMENT
    Your due dates are stored as PER-SECTION OVERRIDES (periods 5, 6, 7), not
    as a single base due date.  In Canvas an override REPLACES the base dates
    for the students it applies to.  So if an assignment already has section
    overrides, setting only the base due_at leaves those students with no due
    date at all — which is very likely how Homework 3 ended up blank in the
    first place.  This script reports the base date AND every override, and
    writes to whichever one actually governs each section.

    Overrides are updated with due_at re-sent alongside unlock_at/lock_at,
    because Canvas treats an omitted date field on an override update as
    "set this to null".
"""

import os
import re
import sys
import csv
import json
import argparse
import datetime
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"
COURSE_ID = "6624"
PER_PAGE = 100

DEFAULT_PATTERN = r"homework"      # matches "Chapter 3 Homework" and "Homework ch. 3"
EXCLUDE = re.compile(r"daily|practice|classwork", re.I)


# --------------------------------------------------------------------------- api
def api(path, method="GET", body=None, params=None):
    """Call the Canvas API. GETs follow Link: rel="next" pagination."""
    token = os.environ.get("CANVAS_TOKEN")
    if not token:
        sys.exit("ERROR: set CANVAS_TOKEN first  ->  export CANVAS_TOKEN='...'")
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = urllib.parse.urlencode(body, doseq=True).encode() if body else None
    out = []
    while url:
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code} on {method} {url}\n{e.read().decode('utf-8')[:800]}")
        out.extend(payload if isinstance(payload, list) else [payload])
        nxt = None
        if method == "GET":
            for part in link.split(","):
                m = re.search(r'<([^>]+)>;\s*rel="next"', part)
                if m:
                    nxt = m.group(1)
                    break
        url = nxt
        data = None
    return out


# ------------------------------------------------------------------- formatting
def local(iso):
    """Canvas returns UTC ISO8601. Show the date/time a teacher would recognize."""
    if not iso:
        return None
    try:
        dt = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return iso
    # Los Angeles: UTC-7 in DST, UTC-8 otherwise. Good enough for a report.
    off = 7 if datetime.date(dt.year, 3, 15) <= dt.date() <= datetime.date(dt.year, 11, 1) else 8
    return (dt - datetime.timedelta(hours=off)).strftime("%Y-%m-%d %H:%M")


def stamp(d, hh, mm):
    """Local date + time -> UTC ISO8601 string Canvas will accept."""
    off = 7 if datetime.date(d.year, 3, 15) <= d <= datetime.date(d.year, 11, 1) else 8
    dt = datetime.datetime(d.year, d.month, d.day, hh, mm) + datetime.timedelta(hours=off)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def show(v):
    return v if v else "\033[31m-- none --\033[0m"


# ----------------------------------------------------------------------- gather
def section_names():
    out = {}
    for s in api(f"courses/{COURSE_ID}/sections", params={"per_page": PER_PAGE}):
        out[s["id"]] = s.get("name", str(s["id"]))
    return out


def collect(pattern):
    rx = re.compile(pattern, re.I)
    rows = []
    for a in api(f"courses/{COURSE_ID}/assignments",
                 params={"per_page": PER_PAGE, "include[]": "overrides"}):
        t = a.get("name") or ""
        if not rx.search(t) or EXCLUDE.search(t):
            continue
        rows.append(a)
    rows.sort(key=lambda a: (
        int(m.group(1)) if (m := re.search(r"homework\s*#?\s*(\d+)", a["name"], re.I)) else 999,
        a["name"]))
    return rows


def report(rows, secs, csv_path=None):
    out = []
    print(f"\n{'id':>8}  {'title':<34} {'pts':>5}  {'pub':<4} "
          f"{'base due':<17} overrides")
    print("-" * 116)
    for a in rows:
        ovs = a.get("overrides") or []
        base = local(a.get("due_at"))
        first = True
        blank = (not a.get("due_at")) and not any(o.get("due_at") for o in ovs)
        title = a["name"][:34]
        flag = "  <== NO DUE DATE ANYWHERE" if blank else ""
        if not ovs:
            print(f"{a['id']:>8}  {title:<34} {str(a.get('points_possible')):>5}  "
                  f"{'yes' if a.get('published') else 'NO':<4} {show(base):<17} "
                  f"(no section overrides){flag}")
        for o in ovs:
            names = ", ".join(secs.get(s, str(s)) for s in ([o["course_section_id"]]
                              if o.get("course_section_id") else o.get("student_ids", [])))
            head = (f"{a['id']:>8}  {title:<34} {str(a.get('points_possible')):>5}  "
                    f"{'yes' if a.get('published') else 'NO':<4} {show(base):<17} "
                    if first else " " * 74)
            print(f"{head}{names:<26} due {show(local(o.get('due_at')))}"
                  f"   open {local(o.get('unlock_at')) or '-'}"
                  f"   close {local(o.get('lock_at')) or '-'}"
                  f"{flag if first else ''}")
            first = False
        out.append(dict(id=a["id"], title=a["name"],
                        points=a.get("points_possible"),
                        published=a.get("published"),
                        base_due=base,
                        n_overrides=len(ovs),
                        override_dues="; ".join(
                            f"{secs.get(o.get('course_section_id'), '?')}="
                            f"{local(o.get('due_at')) or 'NONE'}" for o in ovs),
                        missing_due=blank))
    print()
    miss = [r for r in out if r["missing_due"]]
    if miss:
        print("MISSING A DUE DATE:")
        for r in miss:
            print(f"   {r['id']}  {r['title']}")
    else:
        print("Every written homework has a due date somewhere.")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print(f"\nwrote {csv_path}")
    return out


# ------------------------------------------------------------------------ write
def apply_due(a, secs, dues, hh, mm, window, do_apply, verify):
    ovs = a.get("overrides") or []
    plan = []
    if ovs:
        if len(dues) == 1:
            dues = dues * len(ovs)
        if len(dues) != len(ovs):
            sys.exit(f"ERROR: assignment has {len(ovs)} overrides but you gave "
                     f"{len(dues)} date(s).")
        for o, d in zip(ovs, dues):
            body = {"assignment_override[due_at]": stamp(d, hh, mm)}
            if window:
                body["assignment_override[unlock_at]"] = stamp(
                    d - datetime.timedelta(days=window[0]), 0, 0)
                body["assignment_override[lock_at]"] = stamp(
                    d + datetime.timedelta(days=window[1]), 23, 59)
            name = secs.get(o.get("course_section_id"), str(o.get("id")))
            plan.append((f"override {o['id']} ({name})",
                         f"assignments/{a['id']}/overrides/{o['id']}", body))
    else:
        d = dues[0]
        body = {"assignment[due_at]": stamp(d, hh, mm)}
        if window:
            body["assignment[unlock_at]"] = stamp(
                d - datetime.timedelta(days=window[0]), 0, 0)
            body["assignment[lock_at]"] = stamp(
                d + datetime.timedelta(days=window[1]), 23, 59)
        plan.append(("base assignment", f"assignments/{a['id']}", body))

    print(f"\nPLAN for {a['id']}  {a['name']}")
    for label, path, body in plan:
        print(f"   {label}")
        for k, v in body.items():
            print(f"        {k.split('[')[-1].rstrip(']'):<10} {v}   ({local(v)} local)")
    if not do_apply:
        print("\n(dry run — re-run with --apply to write)")
        return
    for label, path, body in plan:
        api(f"courses/{COURSE_ID}/{path}", "PUT", body)
        print(f"   wrote {label}")
    if verify:
        fresh = api(f"courses/{COURSE_ID}/assignments/{a['id']}",
                    params={"include[]": "overrides"})[0]
        print("\nVERIFY — what Canvas holds now:")
        report([fresh], secs)


# ------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pattern", default=DEFAULT_PATTERN)
    p.add_argument("--set", dest="num", type=int, help="target Homework N")
    p.add_argument("--id", type=int, help="target this assignment id")
    p.add_argument("--due", help="YYYY-MM-DD, or comma-separated one per section")
    p.add_argument("--time", default="23:59", help="due time, local (default 23:59)")
    p.add_argument("--window", help="A,B  -> open due-A days, close due+B days")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--csv")
    args = p.parse_args()

    secs = section_names()
    rows = collect(args.pattern)
    if not rows:
        sys.exit("No assignments matched. Try a different --pattern.")

    if not (args.num or args.id):
        report(rows, secs, args.csv)
        print("\nNext: pick the date, then\n"
              "   python3 canvas_hw_due.py --set N --due YYYY-MM-DD\n"
              "and add --apply once the plan looks right.")
        return

    if args.id:
        target = [a for a in rows if a["id"] == args.id]
    else:
        pats = [rf"(?:chapter|ch\.?)\s*{args.num}\b[^0-9]*homework",
                rf"homework\s*(?:ch\.?|chapter)?\s*#?\s*{args.num}\b"]
        target = [a for a in rows
                  if any(re.search(px, a["name"], re.I) for px in pats)
                  and "part" not in a["name"].lower()]
    if len(target) != 1:
        sys.exit(f"Expected exactly one match, got {len(target)}: "
                 + ", ".join(f"{a['id']} {a['name']}" for a in target))
    if not args.due:
        sys.exit("Give --due YYYY-MM-DD (or a comma-separated list, one per section).")

    dues = [datetime.date.fromisoformat(s.strip()) for s in args.due.split(",")]
    hh, mm = (int(x) for x in args.time.split(":"))
    window = tuple(int(x) for x in args.window.split(",")) if args.window else None
    apply_due(target[0], secs, dues, hh, mm, window, args.apply, args.verify)


if __name__ == "__main__":
    main()