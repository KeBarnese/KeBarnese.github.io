#!/usr/bin/env python3
"""
canvas_make_practice_quizzes.py — create the missing PRACTICE versions of the
daily homework in Honors Chemistry (course 6624), correctly, for New Quizzes.

REPLACES canvas_make_practice_hw.py, which was wrong: it POSTed to the
Assignments API, which for a New Quiz creates an empty assignment shell with
none of the questions.  Your daily homework are New Quizzes (quiz_lti
assignments backed by item banks — the same things list_new_quizzes.py and
test_new_quiz_items.py inspect), so the only way to copy one with its items is
Canvas's duplicate endpoint.

WHAT IT DOES
  1. classifies every daily homework as new_quiz / classic_quiz / assignment
  2. for each one with no practice version yet:
        POST /assignments/:id/duplicate      (carries the questions across)
        wait for Canvas to finish duplicating (it is asynchronous)
        PUT the copy:  name "<homework> Practice", 0 points, no due date,
                       post_to_sis false, group "Practice Daily Homework"
        DELETE any per-section overrides the duplicate inherited, so the copy
               has no due dates for periods 5/6/7 either
  3. logs every id it created to practice_quizzes_created.json

UNDO — remove what the earlier, broken run created:
        python3 canvas_make_practice_quizzes.py --undo practice_created.json
        python3 canvas_make_practice_quizzes.py --undo practice_created.json --apply
  It refuses to delete anything that has submissions, and re-checks each id's
  name against the log before deleting.

USAGE
    export CANVAS_TOKEN='paste-token-here'
    python3 canvas_make_practice_quizzes.py                    # preview
    python3 canvas_make_practice_quizzes.py --limit 1 --apply  # do ONE first
    python3 canvas_make_practice_quizzes.py --apply --verify   # then the rest

*** DRY RUN BY DEFAULT.  Nothing is created or deleted without --apply. ***

TWO THINGS I COULD NOT VERIFY WITHOUT YOUR TOKEN, so --verify checks them and
tells you rather than assuming:
  * New Quiz duplication is asynchronous and the exact workflow_state values
    Canvas reports mid-duplication are not something I can confirm from here.
    The script polls until the copy leaves "duplicating" and reports whatever
    state it lands in.
  * A New Quiz's points normally come from its items, so points_possible = 0
    set at the assignment level may not stick.  --verify re-reads it and says
    so plainly if Canvas overrode it; you would then zero the item points
    inside the quiz instead.
Run with --limit 1 first and look at the result in Canvas before doing 30.
"""

import os
import re
import sys
import json
import time
import difflib
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"
COURSE_ID = "6624"
PER_PAGE = 100

PRACTICE_GROUP = "Practice Daily Homework"
PRACTICE_SUFFIX = " Practice"
LOG_FILE = "practice_quizzes_created.json"

EXTRA_DAILY_IDS = {266481, 266482, 266483}   # the 2.6 Nomenclature set

DUP_POLL_SECONDS = 3
DUP_POLL_TRIES = 20        # ~1 minute per quiz before we give up and report


# ---- API --------------------------------------------------------------------
def api(path, method="GET", body=None, params=None, raw_base=None):
    token = os.environ.get("CANVAS_TOKEN")
    if not token:
        sys.exit("ERROR: set CANVAS_TOKEN first  ->  export CANVAS_TOKEN='...'")
    root = raw_base or f"{BASE}/api/v1/"
    url = root + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = urllib.parse.urlencode(body, doseq=True).encode() if body else None
    out = []
    while url:
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            payload = json.loads(text) if text.strip() else {}
            link = resp.headers.get("Link", "")
        out.extend(payload if isinstance(payload, list) else [payload])
        nxt = None
        if method == "GET":
            for part_ in link.split(","):
                m = re.search(r'<([^>]+)>;\s*rel="next"', part_)
                if m:
                    nxt = m.group(1)
                    break
        url = nxt
        data = None
    return out


# ---- name matching (same rules as the other scripts) ------------------------
def denum(s):
    return re.sub(r'\b0+(\d)', r'\1', s or "")


def norm(s):
    s = denum((s or "").lower())
    s = re.sub(r'classwork|daily homework|practice', '', s)
    s = re.sub(r'[^\w\s.#-]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip(' ,.-')


def sections(s):
    return set(re.findall(r'\d+\.\d+', denum(s)))


def part_no(s):
    m = re.search(r'part\s*(\d+)', s or "", re.I)
    return m.group(1) if m else None


def practice_score(hw, pr):
    s = difflib.SequenceMatcher(None, norm(hw), norm(pr)).ratio()
    sa, sp = sections(hw), sections(pr)
    if sa and sa == sp:
        s += 0.30
    elif sa and sp and not (sa & sp):
        s -= 0.50
    pa, pp = part_no(hw), part_no(pr)
    if pa and pp and pa != pp:
        s -= 0.80
    return s


def kind_of(a):
    """new_quiz | classic_quiz | assignment"""
    if a.get("is_quiz_lti_assignment"):
        return "new_quiz"
    st = a.get("submission_types") or []
    tag = (a.get("external_tool_tag_attributes") or {}).get("url", "")
    if "external_tool" in st and ("quiz-lti" in tag or "quiz_lti" in tag):
        return "new_quiz"
    if a.get("quiz_id") or "online_quiz" in st:
        return "classic_quiz"
    return "assignment"


# ---- undo -------------------------------------------------------------------
def undo(args):
    path = args.undo
    if not os.path.exists(path):
        sys.exit(f"ERROR: {path} not found. Point --undo at the log the bad run wrote "
                 f"(practice_created.json), or list ids with --undo-ids.")
    log = json.load(open(path, encoding="utf-8"))
    print(f"{len(log)} assignment(s) recorded in {path}\n")

    to_delete, protected, gone = [], [], []
    for rec in log:
        aid = rec.get("new_id")
        try:
            a = api(f"courses/{args.course}/assignments/{aid}")[0]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                gone.append((aid, rec.get("new_name")))
                continue
            raise
        if a.get("name", "").strip() != (rec.get("new_name") or "").strip():
            protected.append((aid, a.get("name"), "name no longer matches the log — not touching it"))
            continue
        if a.get("has_submitted_submissions"):
            protected.append((aid, a.get("name"), "has student submissions — not deleting"))
            continue
        to_delete.append((aid, a.get("name")))

    print(f"WOULD DELETE ({len(to_delete)}):" if not args.apply else f"DELETING ({len(to_delete)}):")
    for aid, name in to_delete:
        print(f"    {aid:>8}  {name}")
    if gone:
        print(f"\nAlready gone ({len(gone)}):")
        for aid, name in gone:
            print(f"    {aid:>8}  {name}")
    if protected:
        print(f"\nSKIPPED ({len(protected)}):")
        for aid, name, why in protected:
            print(f"    {aid:>8}  {str(name)[:50]:52} {why}")

    if not args.apply:
        print("\n(dry run — add --apply to actually delete)")
        return

    ok, fail = 0, []
    for aid, name in to_delete:
        try:
            api(f"courses/{args.course}/assignments/{aid}", "DELETE")
            ok += 1
            print(f"  deleted {aid}  {name[:60]}")
            time.sleep(0.1)
        except urllib.error.HTTPError as e:
            fail.append((aid, e.code, e.read().decode("utf-8", "replace")[:150]))
    print(f"\nDeleted {ok}, failed {len(fail)}")
    for aid, code, detail in fail:
        print(f"    {aid}  HTTP {code}  {detail}")
    if ok:
        print(f"\nNote: {path} still lists them. Delete or rename that file so a later "
              f"--undo doesn't try again.")


# ---- duplicate + fix up -----------------------------------------------------
def wait_for_duplicate(course, new_id):
    """New Quiz duplication is async. Poll until it settles; return the assignment."""
    for _ in range(DUP_POLL_TRIES):
        a = api(f"courses/{course}/assignments/{new_id}")[0]
        state = a.get("workflow_state", "")
        if state != "duplicating":
            return a, state
        time.sleep(DUP_POLL_SECONDS)
    return None, "still duplicating after "\
                 f"{DUP_POLL_TRIES * DUP_POLL_SECONDS}s"


def strip_overrides(course, aid):
    """Remove per-section overrides the duplicate inherited (they carry due dates)."""
    removed = 0
    try:
        for ov in api(f"courses/{course}/assignments/{aid}/overrides",
                      params={"per_page": PER_PAGE}):
            api(f"courses/{course}/assignments/{aid}/overrides/{ov['id']}", "DELETE")
            removed += 1
    except urllib.error.HTTPError:
        pass
    return removed


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--course", default=COURSE_ID)
    ap.add_argument("--undo", metavar="LOGFILE",
                    help="delete the assignments listed in this log file (e.g. practice_created.json)")
    ap.add_argument("--group-name", default=PRACTICE_GROUP)
    ap.add_argument("--create-group", action="store_true")
    ap.add_argument("--suffix", default=PRACTICE_SUFFIX)
    ap.add_argument("--exclude-ids", default="")
    ap.add_argument("--limit", type=int, default=None,
                    help="only do this many this run — use --limit 1 the first time")
    ap.add_argument("--publish", action="store_true",
                    help="publish the copies (default: leave unpublished for review)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if args.undo:
        undo(args)
        return

    course = args.course
    exclude = {int(x) for x in args.exclude_ids.replace(" ", "").split(",") if x}
    mode = "APPLY" if args.apply else "DRY RUN (nothing will be created)"
    print(f"# course {course} @ {BASE}   mode: {mode}\n", file=sys.stderr)

    # ---- group ----
    groups = api(f"courses/{course}/assignment_groups", params={"per_page": PER_PAGE})
    target = next((g for g in groups
                   if g["name"].strip().lower() == args.group_name.strip().lower()), None)
    if not target:
        print(f'Assignment group "{args.group_name}" does not exist. Groups here:')
        for g in groups:
            print(f"    {g['id']:>8}  {g['name']}")
        if not args.create_group:
            sys.exit('\nRe-run with --create-group, or use --group-name.')
        if args.apply:
            target = api(f"courses/{course}/assignment_groups", "POST",
                         {"name": args.group_name})[0]
            print(f'\nCreated group "{args.group_name}" (id {target["id"]})')
            group_id = target["id"]
        else:
            group_id = "<would create>"
    else:
        group_id = target["id"]
        print(f'Group "{target["name"]}" -> {group_id}\n')

    # ---- inventory ----
    assignments = api(f"courses/{course}/assignments", params={"per_page": PER_PAGE})
    daily, practice = [], []
    for a in assignments:
        low = a.get("name", "").lower()
        if "practice" in low:
            practice.append(a)
        elif re.search(r"daily\s+homework", low) or a["id"] in EXTRA_DAILY_IDS:
            daily.append(a)

    kinds = {}
    for a in daily:
        kinds.setdefault(kind_of(a), []).append(a)
    print("Daily homework by type: " +
          ", ".join(f"{k}={len(v)}" for k, v in sorted(kinds.items())) or "none")
    print()

    existing = {a.get("name", "").strip().lower() for a in assignments}
    todo, already, unsupported = [], [], []
    for hw in daily:
        if hw["id"] in exclude:
            continue
        name = hw.get("name", "")
        best = (0.0, None)
        for p in practice:
            s = practice_score(name, p.get("name", ""))
            if s > best[0]:
                best = (s, p)
        tgt = (name + args.suffix).strip()
        if (best[1] and best[0] >= 0.80) or tgt.lower() in existing:
            already.append((hw, best[1]))
            continue
        k = kind_of(hw)
        if k == "classic_quiz":
            unsupported.append((hw, "Classic Quiz — the duplicate endpoint does not copy these "
                                    "reliably; copy it in the Canvas UI instead"))
            continue
        todo.append((hw, tgt, k))

    print("=" * 110)
    print(f"TO CREATE — {len(todo)}     [{mode}]")
    print("=" * 110)
    for hw, tgt, k in todo:
        print(f"  {k:<13} from {hw['id']:>7}  {hw.get('name','')[:48]:50}")
        print(f"  {'':<13}   -> {tgt[:78]}")
    print(f"\nAlready have a practice version ({len(already)}) — skipped.")
    if unsupported:
        print(f"\nNOT HANDLED ({len(unsupported)}):")
        for hw, why in unsupported:
            print(f"    {hw['id']:>7}  {hw.get('name','')[:44]:46} {why}")

    print("\n" + "-" * 110)
    print(f"Each copy: duplicated WITH its questions, then set to 0 points, no due date, "
          f"no section overrides,\nSIS off, group {args.group_name!r}, "
          f"published={str(args.publish).lower()}")
    print("-" * 110)

    if not args.apply:
        print("\n(dry run — add --apply to create. Use --limit 1 the first time.)")
        return

    batch = todo if args.limit is None else todo[:args.limit]
    print(f"\nCREATING {len(batch)} ...")
    created, failures = [], []
    for hw, tgt, k in batch:
        try:
            dup = api(f"courses/{course}/assignments/{hw['id']}/duplicate", "POST")[0]
            new_id = dup["id"]
        except urllib.error.HTTPError as e:
            failures.append((hw["id"], tgt, e.code, e.read().decode("utf-8", "replace")[:200]))
            print(f"  FAIL duplicate {hw['id']}: HTTP {e.code}")
            continue

        settled, state = wait_for_duplicate(course, new_id)
        if settled is None:
            failures.append((hw["id"], tgt, "timeout", state))
            print(f"  FAIL {hw['id']} -> {new_id}: {state} (check it in Canvas by hand)")
            continue
        if state == "failed_to_duplicate":
            failures.append((hw["id"], tgt, "failed_to_duplicate",
                             "Canvas reported the duplicate failed"))
            print(f"  FAIL {hw['id']} -> {new_id}: Canvas reported failed_to_duplicate")
            continue

        n_ov = strip_overrides(course, new_id)
        try:
            api(f"courses/{course}/assignments/{new_id}", "PUT", {
                "assignment[name]": tgt,
                "assignment[points_possible]": 0,
                "assignment[assignment_group_id]": group_id,
                "assignment[due_at]": "",
                "assignment[unlock_at]": "",
                "assignment[lock_at]": "",
                "assignment[post_to_sis]": "false",
                "assignment[published]": "true" if args.publish else "false",
            })
        except urllib.error.HTTPError as e:
            failures.append((hw["id"], tgt, e.code,
                             "duplicated OK but the follow-up PUT failed: "
                             + e.read().decode("utf-8", "replace")[:150]))
            print(f"  PARTIAL {new_id}: duplicated but not configured — fix it by hand")
            continue

        created.append({"source_id": hw["id"], "source_name": hw.get("name"),
                        "new_id": new_id, "new_name": tgt, "kind": k,
                        "overrides_removed": n_ov})
        print(f"  ok  {new_id:>8}  {tgt[:62]}"
              + (f"   ({n_ov} inherited override(s) removed)" if n_ov else ""))
        time.sleep(0.3)

    if created:
        log = []
        if os.path.exists(LOG_FILE):
            try:
                log = json.load(open(LOG_FILE, encoding="utf-8"))
            except Exception:
                log = []
        log.extend(created)
        json.dump(log, open(LOG_FILE, "w"), indent=1)
        print(f"\nLogged {len(created)} to {LOG_FILE} (use --undo {LOG_FILE} to remove them)")

    print(f"\nCreated {len(created)}, failed {len(failures)}, "
          f"remaining {max(0, len(todo) - len(batch))}")
    for sid, tgt, code, detail in failures:
        print(f"    from {sid}  {tgt[:38]:40} {code}  {detail}")

    # ---- verify ----
    if args.verify and created:
        print("\nVERIFYING ...")
        bad, points_overridden = [], []
        for rec in created:
            a = api(f"courses/{course}/assignments/{rec['new_id']}")[0]
            if a.get("points_possible") not in (0, 0.0):
                points_overridden.append((rec["new_id"], a.get("points_possible"), rec["new_name"]))
            if a.get("due_at"):
                bad.append(f"    {rec['new_id']}: still has a due date {a.get('due_at')}")
            if a.get("post_to_sis"):
                bad.append(f"    {rec['new_id']}: post_to_sis is true")
            if str(a.get("assignment_group_id")) != str(group_id):
                bad.append(f"    {rec['new_id']}: group is {a.get('assignment_group_id')}, "
                           f"expected {group_id}")
            ovs = api(f"courses/{course}/assignments/{rec['new_id']}/overrides",
                      params={"per_page": PER_PAGE})
            if ovs:
                bad.append(f"    {rec['new_id']}: {len(ovs)} section override(s) still present")
            # did the questions actually come across?
            if rec["kind"] == "new_quiz":
                try:
                    items = api(f"courses/{course}/quizzes/{rec['new_id']}/items",
                                raw_base=f"{BASE}/api/quiz/v1/")
                    if not items:
                        bad.append(f"    {rec['new_id']}: NEW QUIZ HAS NO ITEMS — "
                                   f"the questions did not copy")
                    else:
                        print(f"    {rec['new_id']}: {len(items)} question item(s) copied")
                except urllib.error.HTTPError as e:
                    bad.append(f"    {rec['new_id']}: could not read items to confirm the "
                               f"questions copied (HTTP {e.code})")

        if points_overridden:
            print(f"\n!! Canvas did not keep points_possible=0 on "
                  f"{len(points_overridden)} quiz(zes) — a New Quiz takes its points from its "
                  f"items, so you need to zero the item points inside the quiz:")
            for nid, pts, name in points_overridden:
                print(f"    {nid}  is {pts} pts  {name[:50]}")
        if bad:
            print(f"\n!! {len(bad)} other problem(s):")
            for b in bad:
                print(b)
        if not bad and not points_overridden:
            print("\nAll copies verified: questions present, 0 points, no due date, "
                  "no overrides, SIS off, correct group.")

    print(f"\nNext: refresh the lecture page links —\n"
          f"    python3 canvas_lecture_hw_links.py --propose --merge\n"
          f"    python3 canvas_lecture_hw_links.py --apply --verify")


if __name__ == "__main__":
    main()