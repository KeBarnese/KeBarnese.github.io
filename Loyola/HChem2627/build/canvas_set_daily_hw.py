#!/usr/bin/env python3
"""
canvas_set_daily_hw.py — retitle-safe bulk edit of DAILY HOMEWORK assignments in
Honors Chemistry (Loyola course 6624):

    * points_possible  ->  3   (configurable with --points)
    * available from   ->  due date  -  7 days   (00:00 local)
    * available until  ->  due date  + 14 days   (23:59 local)

Matches the conventions of your other build/ scripts (canvas_get_ids.py,
canvas_pull_due.py, canvas_due_publish.py): stdlib-only (urllib), token from the
CANVAS_TOKEN environment variable, course 6624 hardcoded.

*** DRY RUN BY DEFAULT.  Nothing is written to Canvas unless you pass --apply. ***

USAGE
    export CANVAS_TOKEN='paste-token-here'

    python3 canvas_set_daily_hw.py                  # preview every change
    python3 canvas_set_daily_hw.py --apply          # actually write them
    python3 canvas_set_daily_hw.py --apply --verify # write, then re-read to confirm

    python3 canvas_set_daily_hw.py --points 4       # try 4 pts instead of 3
    python3 canvas_set_daily_hw.py --include-ids 266481,266482,266483
                                                    # also treat these ids as daily HW
    python3 canvas_set_daily_hw.py --skip-dates     # only change points
    python3 canvas_set_daily_hw.py --skip-points    # only change unlock/lock dates
    python3 canvas_set_daily_hw.py --csv preview.csv  # write the preview table to CSV

WHY THIS TOUCHES OVERRIDES, NOT JUST THE ASSIGNMENT
    canvas_due_publish.py sets your due dates as PER-SECTION OVERRIDES (one per
    period: 5, 6, 7), not as a single base due date.  In Canvas an override
    REPLACES the base dates for the students it applies to — so setting
    unlock_at/lock_at only on the assignment would leave students in an
    overridden section with no availability window at all.

    This script therefore computes the window separately for each section
    override, from THAT override's own due date, so periods 5/6/7 each get a
    window anchored to the day they actually turn the work in.  Overrides are
    updated with due_at re-sent alongside unlock_at/lock_at, because Canvas
    treats omitted date fields on an override update as "set to null".
"""

import os
import re
import sys
import csv
import json
import time
import argparse
import datetime
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"
COURSE_ID = "6624"                       # Honors Chemistry 26-27
PER_PAGE = 100
FALL_CUTOFF = datetime.date(2026, 12, 20)   # same cutoff canvas_due_publish.py uses

DEFAULT_POINTS = 3
DAYS_BEFORE = 7
DAYS_AFTER = 14

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    TZ = None


# ---- API helper -------------------------------------------------------------
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
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            link = resp.headers.get("Link", "")
        out.extend(payload if isinstance(payload, list) else [payload])
        nxt = None
        if method == "GET":
            for part in link.split(","):
                m = re.search(r'<([^>]+)>;\s*rel="next"', part)
                if m:
                    nxt = m.group(1)
                    break
        url = nxt
        data = None      # never resend a body when following pagination
    return out


def local_date(iso_str):
    """Canvas ISO timestamp -> local calendar date (or None)."""
    if not iso_str:
        return None
    dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if TZ:
        dt = dt.astimezone(TZ)
    return dt.date()


def stamp(d, hour, minute):
    """Local calendar date + time -> ISO string Canvas accepts."""
    dt = datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ) if TZ \
        else datetime.datetime(d.year, d.month, d.day, hour, minute)
    return dt.isoformat()


def window_for(due_date, days_before, days_after):
    """(unlock_at, lock_at) ISO strings around a due date."""
    unlock = stamp(due_date - datetime.timedelta(days=days_before), 0, 0)
    lock = stamp(due_date + datetime.timedelta(days=days_after), 23, 59)
    return unlock, lock


# ---- which assignments count as "daily homework" ----------------------------
def is_daily_homework(name):
    """True for the graded per-lecture homework, False for everything else.

    Deliberately EXCLUDES:
      * '... Daily Homework Practice'  -> the ungraded 0-pt practice copies
      * 'Chapter N Homework'           -> the 10-pt chapter homework sets
    """
    n = (name or "").lower()
    if "practice" in n:
        return False
    if not re.search(r"daily\s+homework", n):
        return False
    return True


def fmt_date(d):
    return d.isoformat() if d else "(none)"


# ---- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--course", default=COURSE_ID, help=f"Canvas course id (default {COURSE_ID})")
    ap.add_argument("--points", type=float, default=DEFAULT_POINTS,
                    help=f"new points_possible for each daily homework (default {DEFAULT_POINTS})")
    ap.add_argument("--days-before", type=int, default=DAYS_BEFORE,
                    help=f"available-from = due date minus this many days (default {DAYS_BEFORE})")
    ap.add_argument("--days-after", type=int, default=DAYS_AFTER,
                    help=f"available-until = due date plus this many days (default {DAYS_AFTER})")
    ap.add_argument("--due-before", default=FALL_CUTOFF.isoformat(),
                    help=f"only touch assignments due on/before this date, so spring work is left "
                         f"alone (default {FALL_CUTOFF.isoformat()})")
    ap.add_argument("--include-ids", default="",
                    help="comma-separated assignment ids to ALSO treat as daily homework "
                         "(for ones whose titles don't say 'Daily Homework')")
    ap.add_argument("--exclude-ids", default="",
                    help="comma-separated assignment ids to skip entirely")
    ap.add_argument("--skip-points", action="store_true", help="leave points_possible alone")
    ap.add_argument("--skip-dates", action="store_true", help="leave unlock_at/lock_at alone")
    ap.add_argument("--csv", default=None, help="also write the preview table to this CSV path")
    ap.add_argument("--apply", action="store_true",
                    help="actually write to Canvas (default is a read-only dry run)")
    ap.add_argument("--verify", action="store_true",
                    help="after --apply, re-read every touched assignment and confirm the values stuck")
    args = ap.parse_args()

    course = args.course
    cutoff = datetime.date.fromisoformat(args.due_before)
    include_ids = {int(x) for x in args.include_ids.replace(" ", "").split(",") if x}
    exclude_ids = {int(x) for x in args.exclude_ids.replace(" ", "").split(",") if x}

    mode = "APPLY (writing to Canvas)" if args.apply else "DRY RUN (nothing will be written)"
    print(f"# course {course} @ {BASE}", file=sys.stderr)
    print(f"# mode: {mode}", file=sys.stderr)

    # section id -> period, same detection canvas_pull_due.py uses
    sections = api(f"courses/{course}/sections", params={"per_page": PER_PAGE})
    pmap = {}
    for s in sections:
        for P in (5, 6, 7):
            if s["id"] not in pmap and re.search(rf"\b{P}\b|period\s*{P}", s["name"].lower()):
                pmap[s["id"]] = P
    print(f"# sections: " + ", ".join(f"{s['id']}={s['name']}" for s in sections), file=sys.stderr)
    print(f"# period map: {pmap}\n", file=sys.stderr)

    assignments = api(f"courses/{course}/assignments",
                      params={"per_page": PER_PAGE, "include[]": "all_dates"})

    matched, skipped_late, no_due, plan = [], [], [], []

    for a in assignments:
        aid = a["id"]
        name = a.get("name", "")
        if aid in exclude_ids:
            continue
        if not (is_daily_homework(name) or aid in include_ids):
            continue

        # earliest due date across base + overrides decides the semester
        dates = [local_date(d.get("due_at")) for d in a.get("all_dates", []) if d.get("due_at")]
        base_due = local_date(a.get("due_at"))
        if base_due:
            dates.append(base_due)
        dates = sorted({d for d in dates if d})

        if not dates:
            no_due.append((aid, name, a.get("points_possible")))
            matched.append(aid)
            plan.append({
                "id": aid, "name": name, "scope": "assignment",
                "old_points": a.get("points_possible"), "new_points": args.points,
                "due": None, "new_unlock": None, "new_lock": None,
                "note": "no due date anywhere — points only, no window computed",
            })
            continue

        if min(dates) > cutoff:
            skipped_late.append((aid, name, min(dates)))
            continue

        matched.append(aid)

        # ---- base assignment row ----
        row = {
            "id": aid, "name": name, "scope": "assignment (base)",
            "old_points": a.get("points_possible"), "new_points": args.points,
            "due": base_due, "new_unlock": None, "new_lock": None,
            "old_unlock": local_date(a.get("unlock_at")), "old_lock": local_date(a.get("lock_at")),
            "note": "",
        }
        if base_due and not args.skip_dates:
            u, l = window_for(base_due, args.days_before, args.days_after)
            row["new_unlock"], row["new_lock"] = local_date(u), local_date(l)
        elif not base_due:
            row["note"] = "no BASE due date (dates live in section overrides) — points only here"
        plan.append(row)

        # ---- per-section overrides ----
        if not args.skip_dates:
            overrides = api(f"courses/{course}/assignments/{aid}/overrides",
                            params={"per_page": PER_PAGE})
            for ov in overrides:
                ov_due = local_date(ov.get("due_at"))
                sec_id = ov.get("course_section_id")
                period = pmap.get(sec_id)
                label = f"override P{period}" if period else f"override section {sec_id}"
                if not ov_due:
                    plan.append({
                        "id": aid, "name": name, "scope": label, "override_id": ov["id"],
                        "old_points": None, "new_points": None,
                        "due": None, "new_unlock": None, "new_lock": None,
                        "old_unlock": local_date(ov.get("unlock_at")),
                        "old_lock": local_date(ov.get("lock_at")),
                        "note": "override has no due date — SKIPPED, no window computed",
                    })
                    continue
                u, l = window_for(ov_due, args.days_before, args.days_after)
                plan.append({
                    "id": aid, "name": name, "scope": label, "override_id": ov["id"],
                    "old_points": None, "new_points": None,
                    "due": ov_due, "new_unlock": local_date(u), "new_lock": local_date(l),
                    "old_unlock": local_date(ov.get("unlock_at")),
                    "old_lock": local_date(ov.get("lock_at")),
                    "note": "",
                })

    # ---- preview table ----
    print("=" * 100)
    print(f"DAILY HOMEWORK PLAN — {len(matched)} assignment(s) matched   [{mode}]")
    print("=" * 100)
    cur_id = None
    for r in plan:
        if r["id"] != cur_id:
            cur_id = r["id"]
            print(f"\n  [{r['id']}] {r['name'][:70]}")
        if r["scope"].startswith("assignment"):
            pts = "" if args.skip_points else \
                f"points {r['old_points']!s:>5} -> {r['new_points']:g}"
            print(f"      {r['scope']:22} {pts}")
        if r["due"] is not None and not args.skip_dates:
            print(f"      {r['scope']:22} due {fmt_date(r['due'])}   "
                  f"open {fmt_date(r.get('old_unlock'))} -> {fmt_date(r['new_unlock'])}   "
                  f"until {fmt_date(r.get('old_lock'))} -> {fmt_date(r['new_lock'])}")
        if r["note"]:
            print(f"      {'':22} !! {r['note']}")

    old_total = sum(r["old_points"] or 0 for r in plan if r["scope"].startswith("assignment"))
    new_total = args.points * len(matched)
    print("\n" + "-" * 100)
    print(f"Matched assignments:        {len(matched)}")
    if not args.skip_points:
        print(f"Daily HW points currently:  {old_total:g}")
        print(f"Daily HW points after:      {new_total:g}")
        print(f"Net change to semester:     {new_total - old_total:+g}")
    print("-" * 100)

    if skipped_late:
        print(f"\nSkipped {len(skipped_late)} assignment(s) due after {cutoff} (spring work, left alone):")
        for aid, name, d in skipped_late:
            print(f"    {aid:>7}  {d}  {name[:60]}")

    if no_due:
        print(f"\n!! {len(no_due)} matched assignment(s) have NO due date anywhere. "
              f"Points will be set, but no availability window can be computed:")
        for aid, name, pts in no_due:
            print(f"    {aid:>7}  ({pts} pts)  {name[:60]}")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            cols = ["id", "name", "scope", "override_id", "old_points", "new_points",
                    "due", "old_unlock", "new_unlock", "old_lock", "new_lock", "note"]
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in plan:
                w.writerow(r)
        print(f"\nWrote preview to {args.csv}")

    if not args.apply:
        print("\n(dry run — add --apply to write these changes to Canvas)")
        return

    # ---- apply ----
    print("\nAPPLYING ...")
    failures = []
    done_points, done_windows = 0, 0

    for r in plan:
        try:
            if r["scope"].startswith("assignment"):
                body = {}
                if not args.skip_points:
                    body["assignment[points_possible]"] = r["new_points"]
                if not args.skip_dates and r["due"] is not None:
                    u, l = window_for(r["due"], args.days_before, args.days_after)
                    body["assignment[unlock_at]"] = u
                    body["assignment[lock_at]"] = l
                if body:
                    api(f"courses/{course}/assignments/{r['id']}", "PUT", body)
                    done_points += 1
                    print(f"  ok  [{r['id']}] {r['name'][:55]}")
            elif r.get("override_id") and r["due"] is not None and not args.skip_dates:
                u, l = window_for(r["due"], args.days_before, args.days_after)
                # due_at is re-sent on purpose: Canvas nulls omitted date fields
                # on an override update.
                api(f"courses/{course}/assignments/{r['id']}/overrides/{r['override_id']}", "PUT",
                    {"assignment_override[due_at]": stamp(r["due"], 23, 59),
                     "assignment_override[unlock_at]": u,
                     "assignment_override[lock_at]": l})
                done_windows += 1
                print(f"  ok  [{r['id']}] {r['scope']}")
            time.sleep(0.1)      # be polite to the API
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            failures.append((r["id"], r["name"], r["scope"], e.code, detail))
            print(f"  FAIL [{r['id']}] {r['scope']} -> HTTP {e.code}: {detail}")
        except Exception as e:                          # noqa: BLE001
            failures.append((r["id"], r["name"], r["scope"], "?", str(e)[:200]))
            print(f"  FAIL [{r['id']}] {r['scope']} -> {e}")

    print(f"\nAssignments updated: {done_points}   Overrides updated: {done_windows}")
    if failures:
        print(f"\n!! {len(failures)} operation(s) FAILED — Canvas may now be in a partial state. "
              f"Re-run the dry run to see what still needs changing:")
        for aid, name, scope, code, detail in failures:
            print(f"    {aid:>7}  {scope:22} {code}  {name[:40]}  {detail}")

    # ---- verify ----
    if args.verify:
        print("\nVERIFYING (re-reading from Canvas) ...")
        bad = []
        for aid in matched:
            a = api(f"courses/{course}/assignments/{aid}")[0]
            got = a.get("points_possible")
            if not args.skip_points and got != args.points:
                bad.append(f"    [{aid}] points_possible is {got}, expected {args.points}  "
                           f"{a.get('name','')[:45]}")
            if not args.skip_dates:
                ovs = api(f"courses/{course}/assignments/{aid}/overrides",
                          params={"per_page": PER_PAGE})
                for ov in ovs:
                    d, u, l = (local_date(ov.get("due_at")), local_date(ov.get("unlock_at")),
                               local_date(ov.get("lock_at")))
                    if d is None:
                        bad.append(f"    [{aid}] override {ov['id']} lost its due date!")
                        continue
                    want_u = d - datetime.timedelta(days=args.days_before)
                    want_l = d + datetime.timedelta(days=args.days_after)
                    if u != want_u or l != want_l:
                        bad.append(f"    [{aid}] override {ov['id']} window is "
                                   f"{fmt_date(u)}..{fmt_date(l)}, expected "
                                   f"{fmt_date(want_u)}..{fmt_date(want_l)}")
        if bad:
            print(f"!! {len(bad)} mismatch(es):")
            for line in bad:
                print(line)
        else:
            print("All matched assignments and overrides verified correct.")


if __name__ == "__main__":
    main()