#!/usr/bin/env python3
"""
canvas_update_quiz_dates.py - move the Honors Chemistry quizzes (course 6624)
to their new fall-2026 dates, including the per-period section overrides.

Same conventions as the other build/ scripts: stdlib only, CANVAS_TOKEN from the
environment, course 6624 hardcoded.

*** DRY RUN BY DEFAULT.  Nothing is written unless you pass --apply. ***

    export CANVAS_TOKEN='paste-token-here'
    python3 canvas_update_quiz_dates.py                  # preview the changes
    python3 canvas_update_quiz_dates.py --list           # just dump current dates
    python3 canvas_update_quiz_dates.py --apply
    python3 canvas_update_quiz_dates.py --apply --titles # also rename the 2 rescoped quizzes
    python3 canvas_update_quiz_dates.py --apply --verify

AFTERWARDS
    python3 canvas_pull_due.py      # re-pull -> rewrites due_dates.json
    python3 build_page.py           # rebuild ../index.html
    commit/push ../index.html

SAFETY
    Every change is keyed on the assignment ID *and* checked against the title
    Canvas currently holds. If a title has drifted from what this list expects,
    that assignment is skipped and reported - never overwritten blind.
    Only CourseSection overrides that map to periods 5/6/7 are ever touched;
    ADHOC (individual-student) and Group overrides are left alone and reported.

HOW A SPLIT DATE IS EXPRESSED
    Canvas has one base due date ("Everyone else") plus per-section overrides.
    For each quiz this script sets the base to the date the MAJORITY of periods
    share, then adds/updates a section override only for the odd period(s), and
    DELETES any leftover section override whose period now matches the base.
    That keeps the shape Canvas (and canvas_pull_due.py) already expects.
"""
import os, re, sys, json, argparse, datetime, urllib.request, urllib.parse, urllib.error
from collections import Counter

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    TZ = None

BASE, COURSE_ID = "https://loyolahs.instructure.com", "6624"
DEFAULT_TIME = "23:59"          # used only when Canvas has no existing time to copy
SECTION_OVERRIDE = {}           # {5: section_id, ...} if section names lack the digit

# ---------------------------------------------------------------------------
# What to change.  (assignment_id, expected_current_title, {period: date}, new_title)
# new_title is applied only with --titles; None means leave the title alone.
# ---------------------------------------------------------------------------
TARGETS = [
    (266628, "Quiz #3 inorganic nomenclature",
     {5: "2026-09-14", 6: "2026-09-14", 7: "2026-09-14"},
     "Quiz #3 monatomic and polyatomic ions (names and charges)"),

    (266645, "quiz #4",
     {5: "2026-10-13", 6: "2026-10-14", 7: "2026-10-14"},
     None),

    (266629, "Quiz #5, ion review",
     {5: "2026-10-20", 6: "2026-10-20", 7: "2026-10-20"},
     None),

    (266631, "Quiz #7 (ch. 6)",
     {5: "2026-12-03", 6: "2026-12-03", 7: "2026-12-03"},
     "Quiz #7 (ch. 6-7)"),
]

# Quizzes deliberately NOT touched, listed so the preview is a complete picture.
UNCHANGED = [
    (266622, "Quiz #1 1.1 - 1.5",           "8/31 all periods - unchanged"),
    (266627, "Quiz #2 Dimensional Analysis", "9/10 all periods - unchanged"),
    (266630, "Quiz #6 Chapter 4",           "11/2 all periods - unchanged"),
    (266612, "Post-Lab Quiz #4",            "already 10/13 P5 / 10/14 P6,7 - unchanged"),
]

STILL_TODO = """
NOT handled by this script (needs a decision or a different call):

  * Quiz #8 (ch. 7-8 only, 12/10 all periods) does not exist in Canvas yet.
    Creating a graded quiz needs points / assignment group / quiz type / questions,
    so make it in Canvas (or a separate create script) and then add it here.
  * Chapter 9 / Lab 6 cleanup - these are not quizzes, so they are out of scope:
      266530  "9.1 - 9.2 Daily Homework"   -> delete or move to semester 2
      266533  "9.3 Daily Homework"         -> delete or move to semester 2
      266603  "Lab 6"                      -> delete or move to semester 2
      266592  "Chapter 6-9 Homework"       -> rename to "Chapter 6-8 Homework"
"""


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


# ---- date helpers ----------------------------------------------------------
def to_canvas(date_iso, clock):
    """'2026-10-13' + '23:59' -> UTC ISO8601 string Canvas will accept."""
    h, m = (int(x) for x in clock.split(":")[:2])
    naive = datetime.datetime.fromisoformat(date_iso).replace(hour=h, minute=m)
    if TZ is None:
        return naive.isoformat()          # Canvas falls back to the course TZ
    return naive.replace(tzinfo=TZ).astimezone(datetime.timezone.utc)\
                .strftime("%Y-%m-%dT%H:%M:%SZ")


def local_parts(due_at):
    """Canvas due_at -> ('YYYY-MM-DD', 'HH:MM') in Los Angeles, or (None, None)."""
    if not due_at:
        return None, None
    dt = datetime.datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    if TZ:
        dt = dt.astimezone(TZ)
    return dt.date().isoformat(), dt.strftime("%H:%M")


# ---- section id <-> period -------------------------------------------------
def period_map():
    secs = api(f"courses/{COURSE_ID}/sections?per_page=100", paginate=True)
    pmap, names = dict(SECTION_OVERRIDE and {v: k for k, v in SECTION_OVERRIDE.items()}), {}
    for s in secs:
        names[s["id"]] = s["name"]
        for P in (5, 6, 7):
            if s["id"] not in pmap and re.search(rf"\b{P}\b|period\s*{P}", s["name"].lower()):
                pmap[s["id"]] = P
    return pmap, names


# ---- work out what needs to change for one assignment ---------------------
def build_plan(aid, expect_title, desired, new_title, pmap, names, force_time):
    a = api(f"courses/{COURSE_ID}/assignments/{aid}?include[]=all_dates")
    live_title = a.get("name", "")
    if live_title != expect_title and live_title != (new_title or expect_title):
        return None, f"title on Canvas is not what this list expected " \
                     f"(expected {expect_title!r}, found {live_title!r})"

    overrides = api(f"courses/{COURSE_ID}/assignments/{aid}/overrides?per_page=100",
                    paginate=True)

    base_due = a.get("due_at")
    base_date_now, base_time_now = local_parts(base_due)
    default_clock = force_time or base_time_now or DEFAULT_TIME

    # existing section overrides we own, keyed by period
    mine, foreign = {}, []
    for o in overrides:
        sid = o.get("course_section_id")
        if sid is not None and sid in pmap:
            mine[pmap[sid]] = o
        else:
            foreign.append(o)

    # current effective date per period (override wins over base)
    current = {}
    for P in (5, 6, 7):
        if P in mine:
            current[P] = local_parts(mine[P].get("due_at"))[0]
        else:
            current[P] = base_date_now

    # base = the date most periods share; the rest get overrides
    base_target = Counter(desired.values()).most_common(1)[0][0]
    need_override = {P: d for P, d in desired.items() if d != base_target}

    steps = []
    if base_date_now != base_target or (force_time and base_time_now != force_time):
        steps.append({
            "kind": "base",
            "desc": f"base due date {base_date_now or 'none'} -> {base_target} {default_clock}",
            "method": "PUT",
            "path": f"courses/{COURSE_ID}/assignments/{aid}",
            "body": {"assignment[due_at]": to_canvas(base_target, default_clock)},
        })

    for P, want in sorted(need_override.items()):
        sid = next((s for s, p in pmap.items() if p == P), None)
        if sid is None:
            steps.append({"kind": "error",
                          "desc": f"P{P}: no Canvas section matched - cannot set {want}"})
            continue
        if P in mine:
            o = mine[P]
            have, have_time = local_parts(o.get("due_at"))
            clock = force_time or have_time or default_clock
            if have != want or (force_time and have_time != force_time):
                steps.append({
                    "kind": "override-update",
                    "desc": f"P{P} override {have or 'none'} -> {want} {clock}",
                    "method": "PUT",
                    "path": f"courses/{COURSE_ID}/assignments/{aid}/overrides/{o['id']}",
                    "body": {"assignment_override[due_at]": to_canvas(want, clock)},
                })
        else:
            steps.append({
                "kind": "override-create",
                "desc": f"P{P} new override -> {want} {default_clock} "
                        f"(section {names.get(sid, sid)!r})",
                "method": "POST",
                "path": f"courses/{COURSE_ID}/assignments/{aid}/overrides",
                "body": {
                    "assignment_override[course_section_id]": sid,
                    "assignment_override[due_at]": to_canvas(want, default_clock),
                    "assignment_override[title]": names.get(sid, f"Period {P}"),
                },
            })

    # any override whose period now matches the base is redundant -> remove it
    for P, o in sorted(mine.items()):
        if P not in need_override:
            steps.append({
                "kind": "override-delete",
                "desc": f"P{P} override removed (base {base_target} now covers it)",
                "method": "DELETE",
                "path": f"courses/{COURSE_ID}/assignments/{aid}/overrides/{o['id']}",
                "body": None,
            })

    return {
        "aid": aid, "title": live_title, "new_title": new_title,
        "current": current, "desired": desired,
        "base_now": base_date_now, "base_target": base_target,
        "steps": steps, "foreign": foreign,
    }, None


def fmt_dates(d):
    return " / ".join(f"P{P} {d.get(P) or '--'}" for P in (5, 6, 7))


# ---- main -----------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Move the Honors Chem quizzes to their new dates.")
    p.add_argument("--apply",  action="store_true", help="actually write to Canvas")
    p.add_argument("--verify", action="store_true", help="re-read and confirm after applying")
    p.add_argument("--titles", action="store_true",
                   help="also rename the two rescoped quizzes (#3 and #7)")
    p.add_argument("--only", type=int, action="append", metavar="ID",
                   help="limit to this assignment id (repeatable)")
    p.add_argument("--time", metavar="HH:MM",
                   help="force this due time on everything touched "
                        f"(default: keep what Canvas has, else {DEFAULT_TIME})")
    p.add_argument("--list", action="store_true",
                   help="just print current dates for every quiz and exit")
    a = p.parse_args()

    if a.time and not re.fullmatch(r"\d{1,2}:\d{2}", a.time):
        sys.exit("--time wants HH:MM, e.g. --time 23:59")

    pmap, names = period_map()
    print("sections   ->", {sid: names[sid] for sid in names})
    print("period map ->", {sid: P for sid, P in pmap.items()})
    if set(pmap.values()) != {5, 6, 7}:
        print("\n!! did not resolve all three periods from the section names."
              "\n   Fill in SECTION_OVERRIDE at the top of this script and re-run.")
        if a.apply:
            sys.exit(1)

    if a.list:
        print("\nCURRENT quiz dates on Canvas\n" + "-" * 78)
        for aid, title, _ in UNCHANGED:
            _show_current(aid, pmap)
        for aid, title, _, _ in TARGETS:
            _show_current(aid, pmap)
        return

    todo = [t for t in TARGETS if not a.only or t[0] in a.only]
    plans, skipped = [], []
    for aid, expect, desired, new_title in todo:
        # new_title is always passed so an already-renamed quiz is still
        # recognised on later runs; --titles only controls whether we WRITE it.
        plan, why = build_plan(aid, expect, desired, new_title, pmap, names, a.time)
        (skipped if plan is None else plans).append((aid, why) if plan is None else plan)

    # ---- report ----
    print("\n" + "=" * 78)
    print("PLANNED CHANGES")
    print("=" * 78)
    n_steps = 0
    for pl in plans:
        print(f"\n  {pl['aid']}  {pl['title']}")
        print(f"      now    {fmt_dates(pl['current'])}")
        print(f"      target {fmt_dates(pl['desired'])}")
        if not pl["steps"] and not (a.titles and pl["new_title"]):
            print("      already correct - nothing to do")
        for s in pl["steps"]:
            flag = "!!" if s["kind"] == "error" else "->"
            print(f"      {flag} {s['desc']}")
            if s["kind"] != "error":
                n_steps += 1
        if a.titles and pl["new_title"] and pl["new_title"] != pl["title"]:
            print(f"      -> rename to {pl['new_title']!r}")
            n_steps += 1
        for o in pl["foreign"]:
            kind = o.get("student_ids") and "student-specific" or "group/other"
            print(f"      (left alone: {kind} override id {o.get('id')})")

    if skipped:
        print("\nSKIPPED (not touched)\n" + "-" * 78)
        for aid, why in skipped:
            print(f"  {aid}  {why}")

    print("\nNOT CHANGED BY DESIGN\n" + "-" * 78)
    for aid, title, note in UNCHANGED:
        print(f"  {aid}  {title:32} {note}")
    print(STILL_TODO)

    if not a.apply:
        print(f"({n_steps} write(s) queued - dry run, re-run with --apply to write)")
        return

    # ---- apply ----
    print("=" * 78)
    print("APPLYING")
    print("=" * 78)
    for pl in plans:
        for s in pl["steps"]:
            if s["kind"] == "error":
                print(f"  {pl['aid']}  SKIP  {s['desc']}")
                continue
            api(s["path"], s["method"], s["body"])
            print(f"  {pl['aid']}  ok    {s['desc']}")
        if a.titles and pl["new_title"] and pl["new_title"] != pl["title"]:
            api(f"courses/{COURSE_ID}/assignments/{pl['aid']}", "PUT",
                {"assignment[name]": pl["new_title"]})
            print(f"  {pl['aid']}  ok    renamed to {pl['new_title']!r}")

    if a.verify:
        print("\nVERIFY\n" + "-" * 78)
        for pl in plans:
            got = _effective(pl["aid"], pmap)
            ok = all(got.get(P) == pl["desired"][P] for P in (5, 6, 7))
            print(f"  {pl['aid']}  {'OK      ' if ok else 'MISMATCH'}  {fmt_dates(got)}")

    print("\nNext:  python3 canvas_pull_due.py  &&  python3 build_page.py")


def _effective(aid, pmap):
    """Current effective due date per period, straight from Canvas."""
    a = api(f"courses/{COURSE_ID}/assignments/{aid}?include[]=all_dates")
    out, base = {}, None
    for d in a.get("all_dates", []):
        iso = local_parts(d.get("due_at"))[0]
        if d.get("base"):
            base = iso
        elif d.get("set_type") == "CourseSection" and d.get("set_id") in pmap:
            out[pmap[d["set_id"]]] = iso
    for P in (5, 6, 7):
        out.setdefault(P, base)
    return out


def _show_current(aid, pmap):
    a = api(f"courses/{COURSE_ID}/assignments/{aid}")
    print(f"  {aid}  {a.get('name','')[:40]:40}  {fmt_dates(_effective(aid, pmap))}")


if __name__ == "__main__":
    main()
