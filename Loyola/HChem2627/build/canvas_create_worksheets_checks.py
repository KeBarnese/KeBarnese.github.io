#!/usr/bin/env python3
"""
canvas_create_worksheets_checks.py - create the 7 in-class worksheets and the
9 daily planner/notes checks in Honors Chemistry (course 6624), set their due
dates (incl. per-period section overrides), and leave them UNPUBLISHED.

Same conventions as the other build/ scripts: stdlib only, CANVAS_TOKEN from the
environment, course 6624 hardcoded.

*** DRY RUN BY DEFAULT.  Nothing is created unless you pass --apply. ***

    export CANVAS_TOKEN='paste-token-here'
    python3 canvas_create_worksheets_checks.py                  # preview + list groups
    python3 canvas_create_worksheets_checks.py --groups         # just list assignment groups
    python3 canvas_create_worksheets_checks.py --apply          # -> the "Classwork" group
    python3 canvas_create_worksheets_checks.py --apply --verify

AFTERWARDS
    python3 canvas_pull_due.py      # re-pull -> rewrites due_dates.json
    python3 build_page.py           # rebuild ../index.html

WHICH ASSIGNMENT GROUP
    Both the worksheets and the checks go in the group named in
    DEFAULT_GROUP_NAME below ("Classwork"). The name is resolved to an id at
    run time and the resolved group is printed before anything is written.
    Override with --group-name NAME, or with explicit ids:
        --group-all ID
        --group-worksheets ID --group-checks ID
    If the name matches zero groups, or more than one, the script refuses
    rather than guessing. It also refuses if the course uses weighted groups
    and the target group's weight is 0% -- that would make all 62 points
    count for nothing (pass --allow-zero-weight if that is really intended).

RE-RUN SAFETY
    Creating is the one thing you cannot undo by running the script again, so
    before creating anything it pulls every existing assignment name in the
    course and SKIPS any that already exist (exact name match). Running this
    twice creates nothing the second time.

    Everything is created with published=false. Nothing becomes visible to
    students until you publish it in Canvas yourself.
"""
import os, re, sys, json, argparse, datetime, urllib.request, urllib.parse, urllib.error
from collections import Counter

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    TZ = None

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"
DEFAULT_TIME = "23:59"
SECTION_OVERRIDE = {}           # {5: section_id, ...} if section names lack the digit

WORKSHEET_PTS = 5
CHECK_PTS     = 3
SUBMISSION    = "on_paper"      # done on paper, graded in class

# Both worksheets and planner checks live here. Resolved by name at run time so
# the id never has to be looked up; override with --group-name / --group-all.
DEFAULT_GROUP_NAME = "Classwork"

WORKSHEET_DESC = ("<p>In-class worksheet. Completed on paper during class and "
                  "collected at the end of the period.</p>")
CHECK_DESC     = ("<p>Daily planner and notes check. Bring your planner and your "
                  "class notes to be checked in class.</p>")

# ---------------------------------------------------------------------------
# The 7 worksheets - dates are the class meetings agreed for each section.
# (name, {period: 'YYYY-MM-DD'})
# ---------------------------------------------------------------------------
WORKSHEETS = [
    ("Worksheet 1: Dimensional Analysis",
     {5: "2026-09-01", 6: "2026-09-02", 7: "2026-09-02"}),
    ("Worksheet 2: Nomenclature",
     {5: "2026-09-15", 6: "2026-09-15", 7: "2026-09-15"}),
    ("Worksheet 3: Stoichiometry / Limiting Reactant",
     {5: "2026-10-13", 6: "2026-10-14", 7: "2026-10-14"}),
    ("Worksheet 4: Net Ionic Equations",
     {5: "2026-10-23", 6: "2026-10-23", 7: "2026-10-26"}),
    ("Worksheet 5: Enthalpies of Formation",
     {5: "2026-11-05", 6: "2026-11-05", 7: "2026-11-04"}),
    ("Worksheet 6: Electron Configuration",
     {5: "2026-12-01", 6: "2026-12-02", 7: "2026-12-02"}),
    ("Worksheet 7: Lewis Structures",
     {5: "2026-12-10", 6: "2026-12-10", 7: "2026-12-10"}),
]

# ---------------------------------------------------------------------------
# The 9 planner/notes checks. Biweekly, first the week of 8/24, exact 14-day
# cadence (Thanksgiving week 11/23 falls between checks and drops out).
#
# The exact class day inside each week was still TBD, so these default to the
# LAST class meeting of that week for each period - computed from
# Honors_Chem_2627_Schedule_2.xlsx, so every one is a real meeting. Move any of
# them freely; they are placeholders, not decisions.
#
# EXCEPTION: check 9's week would put it on 12/15, which is finals time, so it
# is pinned to 12/14 (the Final Review day) instead.
# ---------------------------------------------------------------------------
CHECKS = [
    ("Planner & Notes Check 1", {5: "2026-08-27", 6: "2026-08-27", 7: "2026-08-28"}),
    ("Planner & Notes Check 2", {5: "2026-09-10", 6: "2026-09-10", 7: "2026-09-10"}),
    ("Planner & Notes Check 3", {5: "2026-09-25", 6: "2026-09-25", 7: "2026-09-25"}),
    ("Planner & Notes Check 4", {5: "2026-10-09", 6: "2026-10-09", 7: "2026-10-09"}),
    ("Planner & Notes Check 5", {5: "2026-10-23", 6: "2026-10-23", 7: "2026-10-22"}),
    ("Planner & Notes Check 6", {5: "2026-11-06", 6: "2026-11-05", 7: "2026-11-04"}),
    ("Planner & Notes Check 7", {5: "2026-11-19", 6: "2026-11-19", 7: "2026-11-20"}),
    ("Planner & Notes Check 8", {5: "2026-12-03", 6: "2026-12-03", 7: "2026-12-03"}),
    ("Planner & Notes Check 9", {5: "2026-12-14", 6: "2026-12-14", 7: "2026-12-14"}),
]


# ---- tiny API helper -------------------------------------------------------
def api(path, method="GET", body=None, paginate=False):
    tok = os.environ.get("CANVAS_TOKEN") or sys.exit("set CANVAS_TOKEN first")
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    data = urllib.parse.urlencode(body, doseq=True).encode() if body else None
    out = []
    while url:
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req) as r:
                payload = json.loads(r.read().decode("utf-8"))
                link = r.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code} on {method} {url}\n"
                     f"{e.read().decode('utf-8', 'replace')[:700]}")
        if not paginate:
            return payload
        out.extend(payload if isinstance(payload, list) else [payload])
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url, data = (m.group(1), None) if m else (None, None)
    return out


def to_canvas(date_iso, clock):
    h, m = (int(x) for x in clock.split(":")[:2])
    naive = datetime.datetime.fromisoformat(date_iso).replace(hour=h, minute=m)
    if TZ is None:
        return naive.isoformat()
    return naive.replace(tzinfo=TZ).astimezone(datetime.timezone.utc)\
                .strftime("%Y-%m-%dT%H:%M:%SZ")


def period_map():
    secs = api(f"courses/{COURSE_ID}/sections?per_page=100", paginate=True)
    pmap = {v: k for k, v in SECTION_OVERRIDE.items()}
    names = {}
    for s in secs:
        names[s["id"]] = s["name"]
        for P in (5, 6, 7):
            if s["id"] not in pmap and re.search(rf"\b{P}\b|period\s*{P}", s["name"].lower()):
                pmap[s["id"]] = P
    return pmap, names


def show_groups():
    course = api(f"courses/{COURSE_ID}")
    weighted = course.get("apply_assignment_group_weights", False)
    groups = api(f"courses/{COURSE_ID}/assignment_groups?per_page=100", paginate=True)
    print(f"\nASSIGNMENT GROUPS  (group weighting is "
          f"{'ON - picking the wrong group changes grades' if weighted else 'off'})")
    print("-" * 78)
    for g in sorted(groups, key=lambda x: x.get("position", 0)):
        w = f"{g.get('group_weight', 0)}%" if weighted else "-"
        print(f"  id {g['id']:>8}   weight {w:>6}   {g.get('name','')}")
    return weighted, groups


def fmt(d):
    return " / ".join(f"P{P} {d[P]}" for P in (5, 6, 7))


def split_plan(desired):
    """base date (majority) + {period: date} needing an override."""
    base = Counter(desired.values()).most_common(1)[0][0]
    return base, {P: d for P, d in desired.items() if d != base}


def main():
    p = argparse.ArgumentParser(description="Create the worksheets and planner checks.")
    p.add_argument("--apply",  action="store_true", help="actually create in Canvas")
    p.add_argument("--verify", action="store_true", help="re-read each new assignment after")
    p.add_argument("--groups", action="store_true", help="list assignment groups and exit")
    p.add_argument("--group-worksheets", type=int, metavar="ID")
    p.add_argument("--group-checks",     type=int, metavar="ID")
    p.add_argument("--group-all",        type=int, metavar="ID",
                   help="shortcut: put both kinds in this group")
    p.add_argument("--group-name", metavar="NAME", default=DEFAULT_GROUP_NAME,
                   help=f"resolve this group by name (default {DEFAULT_GROUP_NAME!r})")
    p.add_argument("--allow-zero-weight", action="store_true",
                   help="create even if the target group is weighted 0%%")
    p.add_argument("--only", choices=("worksheets", "checks"),
                   help="limit to one kind")
    p.add_argument("--time", metavar="HH:MM", default=DEFAULT_TIME,
                   help=f"due time for everything created (default {DEFAULT_TIME})")
    a = p.parse_args()

    if not re.fullmatch(r"\d{1,2}:\d{2}", a.time):
        sys.exit("--time wants HH:MM, e.g. --time 23:59")

    g_ws = a.group_worksheets or a.group_all
    g_ck = a.group_checks     or a.group_all

    pmap, names = period_map()
    print("sections   ->", names)
    print("period map ->", {sid: P for sid, P in pmap.items()})
    if set(pmap.values()) != {5, 6, 7}:
        print("\n!! could not resolve all three periods from the section names."
              "\n   Fill in SECTION_OVERRIDE at the top of this script and re-run.")
        if a.apply:
            sys.exit(1)

    weighted, groups = show_groups()
    valid_gids = {g["id"] for g in groups}
    if a.groups:
        return

    # ---- resolve the target group by name unless explicit ids were given ----
    by_id = {g["id"]: g for g in groups}
    name_err = None
    if g_ws is None or g_ck is None:
        hits = [g for g in groups
                if g.get("name", "").strip().lower() == a.group_name.strip().lower()]
        if len(hits) == 1:
            g_ws = g_ws if g_ws is not None else hits[0]["id"]
            g_ck = g_ck if g_ck is not None else hits[0]["id"]
            w = f"{hits[0].get('group_weight', 0)}%" if weighted else "n/a (total points)"
            print(f"\ntarget group -> id {hits[0]['id']}  {hits[0]['name']!r}  weight {w}")
        else:
            name_err = (f"group name {a.group_name!r} matched {len(hits)} groups "
                        f"- cannot resolve it")
            print(f"\n!! {name_err}")

    if weighted:
        print("\n!! this course uses WEIGHTED assignment groups, so group percentages\n"
              "   decide grades - the 1000-point total is presentational only.")
    else:
        print("\ngrading is total-points (no group weighting), so the 62 new points\n"
              "land directly on the 1000-point total.")

    # ---- what already exists (so a re-run creates nothing twice) ----
    existing = {x.get("name", "").strip(): x["id"]
                for x in api(f"courses/{COURSE_ID}/assignments?per_page=100", paginate=True)}

    todo = []
    if a.only != "checks":
        todo += [("worksheet", n, d, WORKSHEET_PTS, WORKSHEET_DESC, g_ws) for n, d in WORKSHEETS]
    if a.only != "worksheets":
        todo += [("check", n, d, CHECK_PTS, CHECK_DESC, g_ck) for n, d in CHECKS]

    fresh = [t for t in todo if t[1] not in existing]
    dupes = [t for t in todo if t[1] in existing]

    # ---- report ----
    print("\n" + "=" * 78)
    print("TO CREATE  (all unpublished, submission type "
          f"{SUBMISSION!r}, due {a.time})")
    print("=" * 78)
    kind_now = None
    n_over = 0
    for kind, name, dates, pts, _desc, gid in fresh:
        if kind != kind_now:
            kind_now = kind
            print(f"\n  --- {kind}s ---")
        base, over = split_plan(dates)
        n_over += len(over)
        tag = "" if not over else \
              "   + override " + ", ".join(f"P{P} {d}" for P, d in sorted(over.items()))
        print(f"  {pts:>2} pts  {name}")
        print(f"          base due {base}{tag}")
        print(f"          {fmt(dates)}")

    if dupes:
        print("\nALREADY IN CANVAS - will NOT be created again\n" + "-" * 78)
        for _k, name, _d, _p, _dd, _g in dupes:
            print(f"  id {existing[name]:>8}  {name}")

    ws_n = sum(1 for t in fresh if t[0] == "worksheet")
    ck_n = sum(1 for t in fresh if t[0] == "check")
    print("\nSUMMARY\n" + "-" * 78)
    print(f"  {ws_n} worksheet(s) x {WORKSHEET_PTS} pts = {ws_n * WORKSHEET_PTS}")
    print(f"  {ck_n} check(s)     x {CHECK_PTS} pts = {ck_n * CHECK_PTS}")
    print(f"  {len(fresh)} assignments, {n_over} section override(s), "
          f"{ws_n * WORKSHEET_PTS + ck_n * CHECK_PTS} points total")

    if not a.apply:
        print("\n(dry run - nothing created)")
        print("To create, re-run with --apply and the group id(s) from the list above:")
        print("    python3 canvas_create_worksheets_checks.py --apply --group-all <ID>")
        return

    # ---- guard rails before writing ----
    if not fresh:
        print("\nnothing to create - everything already exists.")
        return
    if (ws_n and g_ws is None) or (ck_n and g_ck is None):
        sys.exit(f"\nrefusing to create without an assignment group."
                 f"\n  {name_err or 'no group given'}\n"
                 "  fix the name with --group-name NAME, or pass ids:\n"
                 "    --group-all ID   |   --group-worksheets ID --group-checks ID\n"
                 "  (ids are in the ASSIGNMENT GROUPS list above)")
    for label, gid in (("--group-worksheets", g_ws), ("--group-checks", g_ck)):
        if gid is not None and gid not in valid_gids:
            sys.exit(f"\n{label} {gid} is not an assignment group in this course.")

    # a brand-new group defaults to 0% when weighting is on -> 62 dead points
    if weighted and not a.allow_zero_weight:
        for gid in {g for g in (g_ws, g_ck) if g is not None}:
            if not by_id[gid].get("group_weight"):
                sys.exit(
                    f"\nrefusing to create: group {by_id[gid]['name']!r} (id {gid}) is "
                    f"weighted 0%.\n"
                    "  Group weighting is ON for this course, so everything in a 0% group\n"
                    "  counts for nothing - all 62 points would be dead weight.\n"
                    "  Set the group's weight in Canvas first, or re-run with "
                    "--allow-zero-weight\n  if that really is what you want.")

    # ---- create ----
    print("=" * 78)
    print("CREATING")
    print("=" * 78)
    made = []
    for kind, name, dates, pts, desc, gid in fresh:
        base, over = split_plan(dates)
        body = {
            "assignment[name]": name,
            "assignment[points_possible]": pts,
            "assignment[due_at]": to_canvas(base, a.time),
            "assignment[published]": "false",
            "assignment[grading_type]": "points",
            "assignment[submission_types][]": SUBMISSION,
            "assignment[assignment_group_id]": gid,
            "assignment[description]": desc,
        }
        new = api(f"courses/{COURSE_ID}/assignments", "POST", body)
        aid = new["id"]
        made.append((aid, name, dates))
        print(f"  created {aid:>8}  {name}  ({pts} pts, base {base}, unpublished)")

        for P, want in sorted(over.items()):
            sid = next((s for s, pp in pmap.items() if pp == P), None)
            if sid is None:
                print(f"           !! no section for P{P} - override {want} SKIPPED")
                continue
            api(f"courses/{COURSE_ID}/assignments/{aid}/overrides", "POST", {
                "assignment_override[course_section_id]": sid,
                "assignment_override[due_at]": to_canvas(want, a.time),
                "assignment_override[title]": names.get(sid, f"Period {P}"),
            })
            print(f"           override P{P} -> {want}")

    if a.verify:
        print("\nVERIFY\n" + "-" * 78)
        for aid, name, dates in made:
            got = api(f"courses/{COURSE_ID}/assignments/{aid}?include[]=all_dates")
            eff, b = {}, None
            for d in got.get("all_dates", []):
                iso = None
                if d.get("due_at"):
                    dt = datetime.datetime.fromisoformat(d["due_at"].replace("Z", "+00:00"))
                    iso = (dt.astimezone(TZ) if TZ else dt).date().isoformat()
                if d.get("base"):
                    b = iso
                elif d.get("set_type") == "CourseSection" and d.get("set_id") in pmap:
                    eff[pmap[d["set_id"]]] = iso
            for P in (5, 6, 7):
                eff.setdefault(P, b)
            ok = eff == dates and got.get("published") is False
            print(f"  {aid:>8}  {'OK      ' if ok else 'CHECK ME'}  "
                  f"published={got.get('published')}  {fmt(eff)}")

    print(f"\ncreated {len(made)} assignment(s), all UNPUBLISHED.")
    print("Publish them in Canvas when you're ready for students to see them.")
    print("Next:  python3 canvas_pull_due.py  &&  python3 build_page.py")


if __name__ == "__main__":
    main()
