#!/usr/bin/env python3
"""
canvas_audit_points.py — audit assignment point totals for Honors Chemistry
(Loyola course 6624) and check them against the syllabus's "1000 pts per
semester" target.

Matches the conventions of your other build/ scripts (canvas_get_ids.py,
canvas_pull_due.py): stdlib-only (urllib), read-only GETs, token from the
CANVAS_TOKEN environment variable.

SETUP
    export CANVAS_TOKEN='paste-token-here'
                     # semester 1, course 6624
    python3 canvas_audit_points.py --semester 2      # semester 2 instead
    python3 canvas_audit_points.py --csv out.csv     # also write a CSV
    python3 canvas_audit_points.py --end-date 2026-12-19   # override the
        semester-1/2 cutoff date used when Canvas has no Grading Periods set

WHAT IT DOES
    1. Pulls every assignment in the course (all pages, incl. unpublished).
    2. Splits them into semester 1 / semester 2 using Canvas Grading Periods
       if the course has them configured; otherwise falls back to a due-date
       cutoff (see --end-date) and clearly labels the fallback in the output.
    3. Sums points_possible by assignment group and grand total, separating
       published from unpublished so you can see how much of the total is
       actually live for students right now.
    4. Flags anything that needs a human look: null/zero-point assignments,
       assignments with no due date at all (can't be dated to a semester),
       and assignments not attached to any assignment group.
    5. Compares the semester total against 1000 pts and against your
       980-990 pt headroom target, and reports the gap either way.

Nothing is modified in Canvas — every request is a GET.
"""

import os
import re
import sys
import json
import csv
import argparse
import datetime
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"
COURSE_ID = "6624"  # Honors Chemistry 26-27
PER_PAGE = 100

TARGET_TOTAL = 1000
HEADROOM_LOW, HEADROOM_HIGH = 980, 990

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    TZ = None


def canvas_get(path, params=None):
    """GET an API path, following Link: rel="next" pagination. Returns a list."""
    token = os.environ.get("CANVAS_TOKEN")
    if not token:
        sys.exit("ERROR: set CANVAS_TOKEN first  ->  export CANVAS_TOKEN='...'")
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    out = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            sys.exit(f"ERROR {e.code} fetching {url}\n{e.read().decode('utf-8', 'replace')}")
        out.extend(data if isinstance(data, list) else [data])
        nxt = None
        for part in link.split(","):
            m = re.search(r'<([^>]+)>;\s*rel="next"', part)
            if m:
                nxt = m.group(1)
                break
        url = nxt
    return out


def local_date(iso_str):
    if not iso_str:
        return None
    dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if TZ:
        dt = dt.astimezone(TZ)
    return dt.date()


def get_grading_periods():
    """Returns a sorted list of grading periods, or [] if the feature isn't set up."""
    try:
        gp = canvas_get(f"courses/{COURSE_ID}/grading_periods")
    except SystemExit:
        raise
    periods = []
    for entry in gp:
        # the API wraps periods under "grading_periods" in some Canvas versions
        rows = entry.get("grading_periods") if isinstance(entry, dict) and "grading_periods" in entry else [entry]
        for p in rows:
            if p.get("start_date") and p.get("end_date"):
                periods.append(p)
    periods.sort(key=lambda p: p["start_date"])
    return periods


def semester_of_grading_period(due_date, periods):
    """Map a due_date to a 1-based semester index using grading period order.
    Assumes periods are laid out in chronological chunks — every 2 consecutive
    periods (e.g. Q1+Q2) = semester 1, next 2 = semester 2. If there are
    exactly 2 periods total, each one IS a semester."""
    if not due_date or not periods:
        return None
    idx = None
    for i, p in enumerate(periods):
        start = local_date(p["start_date"])
        end = local_date(p["end_date"])
        if start and end and start <= due_date <= end:
            idx = i
            break
    if idx is None:
        return None
    periods_per_semester = 1 if len(periods) <= 2 else 2
    return (idx // periods_per_semester) + 1


def main():
    global COURSE_ID
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--course", default=COURSE_ID, help=f"Canvas course id (default {COURSE_ID})")
    ap.add_argument("--semester", type=int, default=1, choices=[1, 2], help="which semester to audit (default 1)")
    ap.add_argument("--end-date", default="2026-12-19",
                     help="fallback semester-1/2 cutoff (YYYY-MM-DD, due date <= this is semester 1); "
                          "only used if the course has no Canvas Grading Periods configured")
    ap.add_argument("--csv", default=None, help="optional path to also write a CSV of every assignment")
    args = ap.parse_args()

    COURSE_ID = args.course
    cutoff = datetime.date.fromisoformat(args.end_date)

    print(f"# Auditing course {COURSE_ID} ({BASE}) — semester {args.semester}\n", file=sys.stderr)

    course = canvas_get(f"courses/{COURSE_ID}")[0]
    weighted = bool(course.get("apply_assignment_group_weights"))
    if weighted:
        print("WARNING: this course has weighted assignment groups turned on "
              "(apply_assignment_group_weights=true). The syllabus describes a flat "
              "1000-pt scheme, so a raw point sum may not be what actually determines "
              "the final grade — double check Settings > Assignment Groups in Canvas.\n",
              file=sys.stderr)

    groups = {g["id"]: g["name"] for g in canvas_get(f"courses/{COURSE_ID}/assignment_groups", {"per_page": PER_PAGE})}

    periods = get_grading_periods()
    using_grading_periods = bool(periods)
    if using_grading_periods:
        print(f"Using {len(periods)} Canvas Grading Period(s) to determine semester.", file=sys.stderr)
    else:
        print(f"No Grading Periods found on this course — falling back to due-date cutoff "
              f"{cutoff.isoformat()} (semester 1 = due on/before this date).", file=sys.stderr)

    assignments = canvas_get(f"courses/{COURSE_ID}/assignments",
                              {"per_page": PER_PAGE, "include[]": "all_dates"})

    rows = []
    for a in assignments:
        name = a.get("name", "")
        gid = a.get("assignment_group_id")
        group_name = groups.get(gid, "(no group)")
        points = a.get("points_possible")
        published = a.get("published", False)
        due_iso = a.get("due_at")
        due = local_date(due_iso)

        # If there's no base due_at, fall back to the earliest date in all_dates
        if due is None:
            all_dates = [local_date(d.get("due_at")) for d in a.get("all_dates", []) if d.get("due_at")]
            all_dates = [d for d in all_dates if d]
            due = min(all_dates) if all_dates else None

        if using_grading_periods:
            sem = semester_of_grading_period(due, periods)
        else:
            sem = None if due is None else (1 if due <= cutoff else 2)

        notes = []
        if points is None:
            notes.append("NO POINTS SET")
        elif points == 0:
            notes.append("0 points")
        if due is None:
            notes.append("NO DUE DATE — could not assign a semester, excluded from totals")
        if gid is None:
            notes.append("not in any assignment group")
        if not published:
            notes.append("unpublished")

        rows.append({
            "id": a["id"],
            "name": name,
            "group": group_name,
            "points": points,
            "published": published,
            "due_date": due.isoformat() if due else "",
            "semester": sem,
            "notes": "; ".join(notes),
        })

    # ---- filter to the requested semester ----
    in_scope = [r for r in rows if r["semester"] == args.semester and r["points"] is not None]
    excluded_no_date = [r for r in rows if r["semester"] is None]
    excluded_no_points = [r for r in rows if r["semester"] == args.semester and r["points"] is None]

    published_total = sum(r["points"] for r in in_scope if r["published"])
    unpublished_total = sum(r["points"] for r in in_scope if not r["published"])
    grand_total = published_total + unpublished_total

    # ---- report ----
    print("=" * 78)
    print(f"SEMESTER {args.semester} ASSIGNMENT AUDIT — course {COURSE_ID}")
    print("=" * 78)

    by_group = {}
    for r in in_scope:
        by_group.setdefault(r["group"], []).append(r)

    for gname, grows in sorted(by_group.items()):
        gtotal = sum(r["points"] for r in grows)
        print(f"\n{gname}  —  {gtotal:g} pts  ({len(grows)} assignments)")
        for r in sorted(grows, key=lambda x: x["due_date"] or ""):
            flag = f"   [{r['notes']}]" if r["notes"] else ""
            pub = "" if r["published"] else "  (UNPUBLISHED)"
            print(f"    {r['due_date'] or '(no date)':10}  {r['points']:>6g} pts   {r['name'][:55]:55}{pub}{flag}")

    print("\n" + "-" * 78)
    print(f"Published total:    {published_total:g} pts")
    print(f"Unpublished total:  {unpublished_total:g} pts")
    print(f"GRAND TOTAL:        {grand_total:g} pts")
    print("-" * 78)

    diff_1000 = grand_total - TARGET_TOTAL
    print(f"\nvs. syllabus target of {TARGET_TOTAL} pts: {'+' if diff_1000 >= 0 else ''}{diff_1000:g}")
    if HEADROOM_LOW <= grand_total <= HEADROOM_HIGH:
        print(f"-> within your {HEADROOM_LOW}-{HEADROOM_HIGH} headroom target. Nice.")
    elif grand_total < HEADROOM_LOW:
        print(f"-> {HEADROOM_LOW - grand_total:g} pts BELOW your {HEADROOM_LOW}-{HEADROOM_HIGH} headroom target "
              f"(you have room for {TARGET_TOTAL - grand_total:g} pts of new work before hitting {TARGET_TOTAL}).")
    else:
        print(f"-> {grand_total - HEADROOM_HIGH:g} pts ABOVE your {HEADROOM_LOW}-{HEADROOM_HIGH} headroom target.")

    if excluded_no_points:
        print(f"\n{len(excluded_no_points)} assignment(s) in this semester have NO points_possible set "
              f"and were excluded from the totals above — these need a grade value before they'll count:")
        for r in excluded_no_points:
            print(f"    id {r['id']:>7}  {r['due_date'] or '(no date)':10}  {r['name'][:60]}")

    if excluded_no_date:
        print(f"\n{len(excluded_no_date)} assignment(s) in the whole course have no due date at all "
              f"and couldn't be sorted into a semester — check these manually:")
        for r in excluded_no_date:
            print(f"    id {r['id']:>7}  ({r['points']} pts)  {r['name'][:60]}")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "name", "group", "points", "published", "due_date", "semester", "notes"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"\nWrote full assignment list ({len(rows)} rows, all semesters) to {args.csv}")


if __name__ == "__main__":
    main()