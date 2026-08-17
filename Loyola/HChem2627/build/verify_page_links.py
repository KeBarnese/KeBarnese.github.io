#!/usr/bin/env python3
"""
verify_page_links.py — check every Canvas link the schedule page (index.html)
hands to students, and check the homework/practice pairings are actually right.

Read-only: every request is a GET. Nothing in Canvas or on the page is changed.

WHAT IT CHECKS
  1. every id in ASSIGNMENT_IDS / QUIZ_IDS / FILE_IDS still exists in Canvas,
     and reports which are UNPUBLISHED (a student clicking one gets a 404-ish
     "page does not exist" even though the link is technically valid)
  2. every PAGE_URLS lecture page exists, and its publish state
  3. dangling keys — anything EVENTS references that no ID block defines
  4. homework -> practice pairings: the practice link on each daily-homework
     pill must agree with its homework on the leading section number AND the
     part number. This catches build_page.py's m_practice() fallback silently
     attaching e.g. the "part 1" practice to the "part 3" homework.
  5. one practice assignment reused across two different homeworks
  6. daily-homework pills that still have no practice link at all
  7. duplicate/near-duplicate practice assignments IN CANVAS (two practice
     copies of the same homework), which is what you get if a create run
     didn't recognise an existing unpublished copy

USAGE
    export CANVAS_TOKEN='paste-token-here'
    python3 verify_page_links.py                    # run from the course root
    python3 verify_page_links.py --page ../index.html
    python3 verify_page_links.py --no-canvas        # structure-only, no token needed
    python3 verify_page_links.py --csv report.csv
"""

import os
import re
import sys
import csv
import json
import difflib
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://loyolahs.instructure.com"
COURSE_ID = "6624"
PER_PAGE = 100


def api(path, params=None):
    token = os.environ.get("CANVAS_TOKEN")
    if not token:
        sys.exit("ERROR: set CANVAS_TOKEN first (or use --no-canvas)")
    url = f"{BASE}/api/v1/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    out = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            link = resp.headers.get("Link", "")
        out.extend(payload if isinstance(payload, list) else [payload])
        nxt = None
        for part_ in link.split(","):
            m = re.search(r'<([^>]+)>;\s*rel="next"', part_)
            if m:
                nxt = m.group(1)
                break
        url = nxt
    return out


# ---- parse index.html -------------------------------------------------------
def parse_block(html, name, numeric=True):
    """Read one of the const ID blocks out of index.html.

    index_template.html documents the format with COMMENTED-OUT examples, e.g.
        // 'Quiz_1': 000000, 'PLQuiz_1': 000000, ...
    Those must be stripped first or they parse as real entries pointing at id 0
    and get reported as broken links that were never real."""
    m = re.search(rf"const {name} = \{{(.*?)\}};", html, re.S)
    if not m:
        return {}
    body = m.group(1)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)     # /* block comments */
    body = re.sub(r"//[^\n]*", "", body)                   # // line comments
    if numeric:
        return {k: int(v) for k, v in re.findall(r"'([^']+)'\s*:\s*(\d+)\s*,", body)}
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']*)'\s*,", body))


def lead_section(s):
    m = re.match(r"\s*0*(\d+\.\d+)", s or "")
    return m.group(1) if m else None


def part_of(s):
    m = re.search(r"part\s*(\d+)", s or "", re.I)
    return m.group(1) if m else None


def norm(s):
    s = re.sub(r'\b0+(\d)', r'\1', (s or "").lower())
    s = re.sub(r'daily homework|classwork|practice', '', s)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s.#-]', ' ', s)).strip(' ,.-')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", default="index.html", help="path to the built index.html")
    ap.add_argument("--course", default=COURSE_ID)
    ap.add_argument("--no-canvas", action="store_true",
                    help="skip all live Canvas checks (structure and pairing only)")
    ap.add_argument("--csv", default=None, help="write a per-link CSV report here")
    args = ap.parse_args()

    if not os.path.exists(args.page):
        sys.exit(f"ERROR: {args.page} not found. Run this from the course root, "
                 f"or pass --page path/to/index.html")
    html = open(args.page, encoding="utf-8").read()

    aids = parse_block(html, "ASSIGNMENT_IDS")
    qids = parse_block(html, "QUIZ_IDS")
    fids = parse_block(html, "FILE_IDS")
    pages = parse_block(html, "PAGE_URLS", numeric=False)
    ev = re.search(r"const EVENTS = (\[.*?\]);", html, re.S)
    events = json.loads(ev.group(1)) if ev else []

    print("=" * 100)
    print(f"LINK CHECK — {args.page}")
    print("=" * 100)
    print(f"ASSIGNMENT_IDS {len(aids)}   QUIZ_IDS {len(qids)}   FILE_IDS {len(fids)}   "
          f"PAGE_URLS {len(pages)}   EVENTS {len(events)}\n")

    problems = []
    rows = []

    # ---- 3. dangling keys ----
    defined = set(aids) | set(qids) | set(fids)
    dangling = {}
    for e in events:
        for field in ("hw", "hw2"):
            k = e.get(field)
            if k and k not in defined:
                dangling.setdefault(k, []).append(e.get("t", ""))
    if dangling:
        problems.append(f"{len(dangling)} dangling key(s) — EVENTS reference them but no ID "
                        f"block defines them, so the link falls back to the assignments index")
        print(f"DANGLING KEYS ({len(dangling)}):")
        for k, labels in dangling.items():
            print(f"    {k}   used by: {labels[0][:50]}")
        print()

    # ---- 1 & 2. live existence / publish state ----
    id2name, unpublished, missing = {}, [], []
    if not args.no_canvas:
        live = {a["id"]: a for a in api(f"courses/{args.course}/assignments",
                                       params={"per_page": PER_PAGE})}
        id2name = {i: a.get("name", "") for i, a in live.items()}
        print("CHECKING ASSIGNMENT LINKS ...")
        for key, aid in sorted(aids.items(), key=lambda kv: kv[1]):
            a = live.get(aid)
            if a is None:
                missing.append((key, aid, "assignment"))
                rows.append({"kind": "assignment", "key": key, "id": aid,
                             "status": "MISSING", "name": ""})
                continue
            pub = bool(a.get("published"))
            if not pub:
                unpublished.append((key, aid, a.get("name", "")))
            rows.append({"kind": "assignment", "key": key, "id": aid,
                         "status": "ok" if pub else "UNPUBLISHED", "name": a.get("name", "")})

        for label, block, path in (("quiz", qids, "quizzes"), ("file", fids, "files")):
            for key, oid in block.items():
                try:
                    o = api(f"courses/{args.course}/{path}/{oid}")[0]
                    name = o.get("title") or o.get("display_name") or ""
                    hidden = o.get("hidden") or o.get("locked")
                    rows.append({"kind": label, "key": key, "id": oid,
                                 "status": "HIDDEN/LOCKED" if hidden else "ok", "name": name})
                    if hidden:
                        unpublished.append((key, oid, name))
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        missing.append((key, oid, label))
                        rows.append({"kind": label, "key": key, "id": oid,
                                     "status": "MISSING", "name": ""})
                    else:
                        raise

        print("CHECKING LECTURE PAGES ...")
        for lid, slug in sorted(pages.items()):
            try:
                p = api(f"courses/{args.course}/pages/{slug}")[0]
                pub = bool(p.get("published"))
                rows.append({"kind": "page", "key": lid, "id": slug,
                             "status": "ok" if pub else "UNPUBLISHED",
                             "name": p.get("title", "")})
                if not pub:
                    unpublished.append((lid, slug, p.get("title", "")))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    missing.append((lid, slug, "page"))
                    rows.append({"kind": "page", "key": lid, "id": slug,
                                 "status": "MISSING", "name": ""})
                else:
                    raise

        if missing:
            problems.append(f"{len(missing)} link target(s) DO NOT EXIST in Canvas")
            print(f"\nMISSING ({len(missing)}) — these links are broken:")
            for key, oid, kind in missing:
                print(f"    {kind:<10} {key:<28} {oid}")
        if unpublished:
            problems.append(f"{len(unpublished)} link target(s) are UNPUBLISHED — students "
                            f"clicking them see 'page does not exist'")
            print(f"\nUNPUBLISHED ({len(unpublished)}):")
            for key, oid, name in unpublished:
                print(f"    {key:<28} {str(oid):<10} {name[:44]}")
        print()

    # ---- 4 & 5. homework -> practice pairing ----
    def title_of(key):
        aid = aids.get(key)
        if aid is None:
            return None
        return id2name.get(aid) if id2name else None

    pairs, mispaired, reuse = {}, [], {}
    for e in events:
        if e.get("k") == "due" and e.get("hw") and e.get("hw2"):
            pairs[(e["hw"], e["hw2"])] = e.get("t", "")

    print(f"HOMEWORK -> PRACTICE PAIRINGS ({len(pairs)}):")
    for (hw, hw2), label in sorted(pairs.items(), key=lambda kv: kv[1]):
        th, tp = title_of(hw), title_of(hw2)
        reuse.setdefault(hw2, set()).add(hw)
        if not id2name:
            print(f"    ?    {label[:60]}   (run with a token to resolve titles)")
            continue
        # id2name is populated, so a None title means that id is GONE from Canvas
        if th is None or tp is None:
            dead = []
            if th is None:
                dead.append(f"homework id {aids.get(hw)}")
            if tp is None:
                dead.append(f"practice id {aids.get(hw2)}")
            mispaired.append((label, th or "<deleted>", tp or "<deleted>",
                              "links to a DELETED assignment: " + ", ".join(dead)))
            print(f"    DEAD  {label[:52]}   -> {', '.join(dead)} no longer exists")
            continue
        sh, sp = lead_section(th), lead_section(tp)
        ph, pp = part_of(th), part_of(tp)
        ok = True
        why = []
        if sh and sp and sh != sp:
            ok = False
            why.append(f"section {sh} vs {sp}")
        if ph and pp and ph != pp:
            ok = False
            why.append(f"part {ph} vs {pp}")
        if ph and not pp:
            why.append(f"homework is part {ph}, practice has no part — may be shared, check it")
        if not ok:
            mispaired.append((label, th, tp, "; ".join(why)))
        print(f"    {'ok  ' if ok else 'WRONG'} {th[:42]:44} -> {tp[:42]}")
        rows.append({"kind": "pairing", "key": f"{hw}->{hw2}", "id": "",
                     "status": "ok" if ok else "MISPAIRED", "name": f"{th} -> {tp}"})

    if mispaired:
        problems.append(f"{len(mispaired)} practice link(s) point at the WRONG practice quiz")
        print(f"\n!! MISPAIRED ({len(mispaired)}):")
        for label, th, tp, why in mispaired:
            print(f"    pill: {label[:56]}")
            print(f"        homework: {th}")
            print(f"        practice: {tp}")
            print(f"        problem:  {why}")

    shared = {p: hws for p, hws in reuse.items() if len(hws) > 1}
    if shared:
        print(f"\nONE PRACTICE USED BY SEVERAL HOMEWORKS ({len(shared)}) — "
              f"intentional for split part 1/part 2 lectures, a bug otherwise:")
        for p, hws in shared.items():
            print(f"    {(title_of(p) or p)[:60]}")
            for h in sorted(hws):
                print(f"        <- {(title_of(h) or h)[:56]}")

    # ---- 6. daily HW pills with no practice ----
    dailies = [e for e in events if e.get("k") == "due" and str(e.get("t", "")).startswith("HW: ")]
    seen, nopractice = set(), []
    for e in dailies:
        if not e.get("hw2") and e["t"] not in seen:
            seen.add(e["t"])
            nopractice.append(e["t"])
    if nopractice:
        print(f"\nDAILY HOMEWORK PILLS WITH NO PRACTICE LINK ({len(nopractice)}):")
        for t in nopractice:
            print(f"    {t[:72]}")
        print("    -> refresh the inventory and rebuild:")
        print("       python3 canvas_get_ids.py > canvas_ids_6624_renamed.txt")
        print("       python3 build_page.py")

    # ---- 7. duplicate practice assignments in Canvas ----
    if not args.no_canvas:
        practice = [(i, n) for i, n in id2name.items() if "practice" in n.lower()]
        dupes = []
        for idx, (i1, n1) in enumerate(practice):
            for i2, n2 in practice[idx + 1:]:
                s = difflib.SequenceMatcher(None, norm(n1), norm(n2)).ratio()
                same_sec = lead_section(n1) and lead_section(n1) == lead_section(n2)
                same_part = part_of(n1) == part_of(n2)
                if s >= 0.85 and same_sec and same_part:
                    dupes.append((i1, n1, i2, n2, round(s, 2)))
        if dupes:
            problems.append(f"{len(dupes)} pair(s) of near-duplicate PRACTICE assignments in Canvas")
            print(f"\n!! NEAR-DUPLICATE PRACTICE ASSIGNMENTS IN CANVAS ({len(dupes)}) — "
                  f"likely one pre-existing (possibly unpublished) copy plus a newly created one. "
                  f"Delete whichever you don't want:")
            for i1, n1, i2, n2, s in dupes:
                print(f"    {i1:>7}  {n1[:56]}")
                print(f"    {i2:>7}  {n2[:56]}   (similarity {s})")
                print()

    if args.csv and rows:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["kind", "key", "id", "status", "name"])
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {len(rows)} rows to {args.csv}")

    print("\n" + "=" * 100)
    if problems:
        print(f"{len(problems)} PROBLEM CATEGORY/CATEGORIES:")
        for p in problems:
            print(f"    - {p}")
    else:
        print("No broken links, no mispaired practice links.")
    print("=" * 100)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()