#!/usr/bin/env python3
"""
probe_quiz_timing.py — find out which Canvas endpoint exposes per-attempt
TIMING data for New Quizzes, using last year's course (5799) as the test case.

I could not verify from documentation which endpoint carries attempt duration
for New Quizzes, and I would rather probe than assert. This script tries every
plausible endpoint read-only, reports the HTTP status of each, and for the ones
that return data it names any field that looks like a timestamp or a duration.

Read-only: GET requests only. Nothing is created, changed, or deleted.

STUDENT PRIVACY: attempt data contains student names and ids. This script
anonymises by default — names are dropped and user ids replaced by a stable
per-run pseudonym (S001, S002, ...). Timing analysis does not need identities.
Pass --with-names only if you actually need them, and keep that output off the
GitHub repo.

USAGE
    export CANVAS_TOKEN='paste-token-here'

    # probe all endpoints for one assignment
    python3 probe_quiz_timing.py --course 5799 --assignment 227866

    # once you know which endpoint works, pull several and write a CSV
    python3 probe_quiz_timing.py --course 5799 \\
        --assignment 227866,227877,227890 --csv timing.csv

The three assignments above are the daily homework whose moderation pages you
linked:
    227866  ->  .../assignments/227866/moderation/10897
    227877  ->  .../assignments/227877/moderation/10908
    227890  ->  .../assignments/227890/moderation/10921
"""

import os
import re
import sys
import csv
import json
import argparse
import hashlib
import datetime
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"

TIME_FIELD = re.compile(
    r"(duration|elapsed|time_spent|seconds|started_at|finished_at|"
    r"submitted_at|created_at|updated_at|attempt_started|workflow_state)", re.I)


def get(path, params=None, api_root="api/v1"):
    """GET a path. Returns (status, parsed_json_or_text, note)."""
    token = os.environ.get("CANVAS_TOKEN")
    if not token:
        sys.exit("ERROR: set CANVAS_TOKEN first  ->  export CANVAS_TOKEN='...'")
    url = f"{BASE}/{api_root}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read().decode("utf-8")
            try:
                return r.status, json.loads(body), ""
            except json.JSONDecodeError:
                return r.status, None, f"non-JSON response ({len(body)} bytes)"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:160].replace("\n", " ")
        return e.code, None, detail
    except Exception as e:                                  # noqa: BLE001
        return None, None, str(e)[:160]


def walk_fields(obj, prefix="", out=None, depth=0):
    """Collect dotted field paths that look time-related."""
    if out is None:
        out = {}
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if TIME_FIELD.search(k) and not isinstance(v, (dict, list)):
                out.setdefault(p, v)
            walk_fields(v, p, out, depth + 1)
    elif isinstance(obj, list) and obj:
        walk_fields(obj[0], prefix + "[]", out, depth + 1)
    return out


def anon(uid, salt):
    h = hashlib.sha256(f"{salt}:{uid}".encode()).hexdigest()[:8]
    return "S" + h


def probe(course, aid):
    print("=" * 96)
    print(f"PROBING course {course}, assignment {aid}")
    print("=" * 96)

    candidates = [
        # (label, api_root, path, params)
        ("New Quizzes: items (known good — proves token scope)",
         "api/quiz/v1", f"courses/{course}/quizzes/{aid}/items", None),
        ("New Quizzes: sessions",
         "api/quiz/v1", f"courses/{course}/quizzes/{aid}/sessions", None),
        ("New Quizzes: submissions",
         "api/quiz/v1", f"courses/{course}/quizzes/{aid}/submissions", None),
        ("New Quizzes: reports",
         "api/quiz/v1", f"courses/{course}/quizzes/{aid}/reports", None),
        ("Assignment submissions (+submission_history)",
         "api/v1", f"courses/{course}/assignments/{aid}/submissions",
         {"include[]": ["submission_history"], "per_page": 5}),
        ("Assignment submissions (+sub_assignment_submissions)",
         "api/v1", f"courses/{course}/assignments/{aid}/submissions",
         {"per_page": 5}),
        ("Classic quiz statistics (only if this is a Classic Quiz)",
         "api/v1", f"courses/{course}/quizzes/{aid}/statistics", None),
        ("Assignment object itself (tells us the quiz engine)",
         "api/v1", f"courses/{course}/assignments/{aid}", None),
    ]

    working = []
    for label, root, path, params in candidates:
        status, data, note = get(path, params, api_root=root)
        ok = status == 200 and data is not None
        n = len(data) if isinstance(data, list) else (1 if data else 0)
        flag = "OK " if ok else "-- "
        print(f"\n{flag}[{status}] {label}")
        print(f"    /{root}/{path}")
        if note:
            print(f"    note: {note}")
        if not ok:
            continue
        print(f"    returned: {n} record(s)")
        fields = walk_fields(data)
        if fields:
            print("    time-ish fields found:")
            for k, v in list(fields.items())[:12]:
                print(f"        {k} = {v!r}")
            working.append((label, root, path, params, fields))
        else:
            print("    no timestamp/duration-looking fields")

    print("\n" + "=" * 96)
    if working:
        print("ENDPOINTS THAT RETURNED TIME-RELATED FIELDS:")
        for label, root, path, _, fields in working:
            print(f"  * {label}")
            print(f"      /{root}/{path}")
            print(f"      fields: {', '.join(list(fields)[:8])}")
        print("\nTell me which of these has what you need and I'll write the extractor.")
    else:
        print("None of the probed endpoints returned timing data.")
        print("Fallback: in Canvas open the New Quiz -> Reports -> 'Student Analysis',")
        print("download the CSV, and send it to me — that export does carry per-attempt")
        print("timing, and I can analyse the CSV directly.")
    print("=" * 96)
    return working


def extract(course, aids, csv_path, with_names):
    """Best-effort extractor for the endpoint that most often carries this:
    assignment submissions with submission_history."""
    salt = hashlib.sha256(os.urandom(16)).hexdigest()
    rows = []
    for aid in aids:
        a_status, a_obj, _ = get(f"courses/{course}/assignments/{aid}")
        title = (a_obj or {}).get("name", f"assignment {aid}") if a_status == 200 else f"assignment {aid}"
        status, subs, note = get(f"courses/{course}/assignments/{aid}/submissions",
                                 {"include[]": ["submission_history"], "per_page": 100})
        if status != 200 or not isinstance(subs, list):
            print(f"  {aid}: could not read submissions ({status}) {note}")
            continue
        for s in subs:
            started = s.get("started_at") or (s.get("submission_history") or [{}])[0].get("started_at")
            finished = s.get("submitted_at")
            dur = None
            if started and finished:
                try:
                    t0 = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                    t1 = datetime.datetime.fromisoformat(finished.replace("Z", "+00:00"))
                    dur = round((t1 - t0).total_seconds() / 60.0, 1)
                except Exception:                            # noqa: BLE001
                    pass
            rows.append({
                "assignment_id": aid,
                "assignment": title,
                "student": (s.get("user_id") if with_names else anon(s.get("user_id"), salt)),
                "attempt": s.get("attempt"),
                "score": s.get("score"),
                "started_at": started or "",
                "submitted_at": finished or "",
                "minutes": dur if dur is not None else "",
            })
        print(f"  {aid}: {len(subs)} submission(s)  {title[:50]}")

    if not rows:
        print("\nNo rows extracted — run without --csv first to see which endpoint works.")
        return
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    got = [r["minutes"] for r in rows if r["minutes"] != ""]
    print(f"\nWrote {len(rows)} row(s) to {csv_path}")
    print(f"rows with a computable duration: {len(got)} of {len(rows)}")
    if got:
        got = sorted(got)
        mid = got[len(got) // 2]
        print(f"median {mid} min | min {got[0]} | max {got[-1]}")
    else:
        print("No durations computable — 'started_at' is probably absent for New Quizzes,")
        print("which would mean the Student Analysis CSV export is the way to go.")
    if not with_names:
        print("Student identifiers are pseudonymised (new salt each run).")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--course", default="5799", help="Canvas course id (default 5799, last year)")
    ap.add_argument("--assignment", required=True,
                    help="assignment id, or comma-separated list")
    ap.add_argument("--csv", default=None, help="write extracted timing rows here")
    ap.add_argument("--with-names", action="store_true",
                    help="keep raw user ids instead of pseudonyms")
    args = ap.parse_args()

    aids = [x.strip() for x in args.assignment.split(",") if x.strip()]
    if args.csv:
        extract(args.course, aids, args.csv, args.with_names)
    else:
        probe(args.course, aids[0])
        if len(aids) > 1:
            print(f"\n({len(aids)-1} more assignment id(s) given — probing only the first. "
                  f"Add --csv once we know which endpoint works.)")


if __name__ == "__main__":
    main()