#!/usr/bin/env python3
"""
build_page.py — one command: match the Honors-Chem schedule to Canvas IDs and
write index.html.

  python3 build_page.py

Inputs (edit CONFIG below if names change):
  * INV   : canvas_ids_output.txt   (from canvas_get_ids.py)
  * SRC   : the schedule .xlsx      (cols: Assignments | Period 5 | 6 | 7)
  * TPL   : index_template.html     (placeholders __COURSE__/__AIDS__/__EVENTS__)
Output:
  * index.html

The title matchers recognize BOTH the original names ("... Classwork",
"Homework ch. N") and the renamed ones ("... Daily Homework",
"Chapter N Homework"), so this keeps working after you rename in Canvas.
"""
import re, os, sys, json, datetime, pathlib
from openpyxl import load_workbook

# ---- CONFIG ----------------------------------------------------------------
COURSE_ID   = "6624"
INV         = "canvas_ids_6624_renamed.txt"
SRC         = "Honors_Chem_2627_Schedule_2.xlsx"
TPL         = "index_template.html"
OUT         = "../index.html"   # written to the course root (run this from build/)
FALL_CUTOFF = datetime.date(2026, 12, 20)
BLANK_ROW_DATE = {50: datetime.date(2026, 12, 15)}
LINK_DAILY  = True   # link the blue daily-homework pill to its Canvas assignment (+practice)
# extra fall exam-review assignments placed by hand (matched by title below)
REVIEW_TITLES = {"1": "Exam 1 Review - Build On",
                 "2": "Exam 2 Review - Build On",
                 "3": "Exam 3, Chapter 4 review, Build On",
                 "F": "Semester 1 Final Review"}

# ---- parse inventory -------------------------------------------------------
A, sec = [], None
for ln in open(INV, encoding="utf-8"):
    if "ASSIGNMENTS" in ln: sec = "A"; continue
    if "FILES" in ln: sec = None; continue
    if ln.startswith("===") or "CLASSIC QUIZZES" in ln: continue
    m = re.match(r"\s*(\d+)\s+(.*?)\s{2,}https?://", ln)
    if m and sec == "A": A.append((int(m.group(1)), m.group(2).strip()))
ID2T = {i: t for i, t in A}
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^\w\s.#/-]", " ", s.lower())).strip()
TITLES = [(i, t, norm(t)) for i, t in A]
def find(pred):
    for i, t, n in TITLES:
        if pred(n, t): return i
    return None
def lead_section(s):
    m = re.match(r"\s*(\d+\.\d+)", s);  return m.group(1) if m else None

# ---- matchers (accept original + renamed titles) ---------------------------
def m_daily(raw):                       # "3.3 Classwork"  OR  "3.3 Daily Homework"
    n = norm(raw)
    aid = find(lambda x, t: x.rstrip(". ") == n.rstrip(". "))
    if aid: return aid
    base = re.sub(r"classwork|daily homework", "", n).strip(" ,")
    aid = find(lambda x, t: re.sub(r"classwork|daily homework", "", x).strip(" ,") == base
               and ("classwork" in x or "daily homework" in x))
    if aid: return aid
    s = lead_section(raw)
    if s:
        return find(lambda x, t: x.startswith(s) and ("classwork" in x or "daily homework" in x)
                    and "practice" not in x)
    return None
def m_practice(raw):
    s = lead_section(raw)
    if not s: return None
    pm = re.search(r"part\s*(\d+)", raw.lower())
    if pm:
        aid = find(lambda x, t: x.startswith(s) and "practice" in x and f"part {pm.group(1)}" in x)
        if aid: return aid
    return find(lambda x, t: x.startswith(s) and "practice" in x)
def m_homework(text):                   # chapter homework, orig or renamed
    t = text.lower()
    mm = re.search(r"(\d+)\s*-\s*(\d+)", t)
    if mm:
        a, b = mm.group(1), mm.group(2)
        return find(lambda x, tt: "homework" in x and re.search(rf"\b{a}\s*-\s*{b}\b", x))
    m = re.search(r"(?:homework|hw)\s*#?\s*(\d+)(?:\s*part\s*(\d+))?", t)
    if not m: return None
    ch, part = m.group(1), m.group(2)
    if part:
        return find(lambda x, tt: "homework" in x and re.search(rf"(ch\.?|chapter)\s*{ch}\b", x)
                    and f"part {part}" in x)
    return find(lambda x, tt: "homework" in x and re.search(rf"(ch\.?|chapter)\s*{ch}\b", x)
                and "part" not in x)
def m_quiz(text, postlab):
    m = re.search(r"#\s*(\d+)", text)
    if not m:
        return find(lambda x, t: "snap" in x and "quiz" in x) if "snap" in text.lower() else None
    n = m.group(1)
    if postlab:
        return find(lambda x, t: "post" in x and "quiz" in x and re.search(rf"#\s*{n}\b", x))
    return find(lambda x, t: "quiz" in x and "post" not in x and re.search(rf"#\s*{n}\b", x))
def m_lab(text):
    m = re.search(r"(\d+)", text)
    return find(lambda x, t: re.fullmatch(rf"lab {m.group(1)}", x) is not None) if m else None
def m_review(n):
    want = norm(REVIEW_TITLES.get(n, "")); return find(lambda x, t: x == want)

# ---- walk the schedule -----------------------------------------------------
def pdate(v):
    if v is None: return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.date() if isinstance(v, datetime.datetime) else v
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v).strip())
    return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None
def iso(d): return d.strftime("%Y-%m-%d")
def clean(s): return re.sub(r"\s+", " ", re.sub(r",?\s*classwork\b", "", s, flags=re.I)).strip(" ,")

ws = load_workbook(SRC).active
AID, events, unmatched = {}, [], []
def key_for(aid):
    if aid is None: return None
    k = f"A{aid}"          # ID-based key: unique + stable, no truncation collisions
    AID[k] = aid; return k

# due dates come from Canvas (via canvas_pull_due.py) — Canvas is the source of truth
DUE = json.load(open("due_dates.json")) if os.path.exists("due_dates.json") else {}
def emit_due(aid, text, practice_aid=None):
    """Place a linked 'due' pill on each section's Canvas due date (grouped)."""
    if aid is None: return
    dd = DUE.get(str(aid))
    if not dd:
        unmatched.append(("DUE?", f"{ID2T.get(aid,aid)} has no due date in due_dates.json"))
        return
    key = key_for(aid)
    pkey = key_for(practice_aid) if practice_aid else None
    g = {}
    for P in (5, 6, 7):
        if str(P) in dd: g.setdefault(dd[str(P)], []).append(P)
    allsame = len(g) == 1 and set(next(iter(g.values()))) == {5, 6, 7}
    for dt, pers in g.items():
        ev = {"d": dt, "p": 0 if allsame else sorted(pers), "k": "due", "t": text, "hw": key}
        if pkey: ev["hw2"] = pkey
        events.append(ev)

for r in range(2, ws.max_row + 1):
    p = {5: pdate(ws.cell(r,2).value), 6: pdate(ws.cell(r,3).value), 7: pdate(ws.cell(r,4).value)}
    if all(v is None for v in p.values()):
        if r in BLANK_ROW_DATE: p = {k: BLANK_ROW_DATE[r] for k in p}
        else: continue
    if any(v is None for v in p.values()) or min(p.values()) > FALL_CUTOFF: continue
    groups = {}
    for per, d in p.items(): groups.setdefault(d, []).append(per)
    all_equal = len(groups) == 1
    pcode = lambda pers: 0 if all_equal else sorted(pers)
    lines = [x.strip() for x in (ws.cell(r,1).value or "").split("\n") if x.strip()]

    if r == 2:
        for d, pers in groups.items():
            events.append({"d": iso(d), "p": pcode(pers), "k": "info", "t": "First day of class", "hw": None})
        continue

    lect_done, buckets = False, []
    for ln in lines:
        low = ln.lower()
        if "review" in low:
            n = re.search(r"exam\s*(\d+)", low); rn = n.group(1) if n else "1"
            aid = m_review(rn)
            if not aid: unmatched.append((r, ln))
            buckets.append(("rev", {"t": f"Exam {rn} Review", "hw": key_for(aid)}))
        elif "exam" in low:
            buckets.append(("exam", {"t": ln, "hw": None}))
        elif "quiz" in low:
            aid = m_quiz(ln, "post" in low)
            if not aid: unmatched.append((r, ln))
            buckets.append(("quiz", {"t": ln, "hw": key_for(aid)}))
        elif low.startswith("lab") and "due" not in low:
            aid = m_lab(ln); n = re.search(r"(\d+)", ln)
            if not aid: unmatched.append((r, ln))
            buckets.append(("lab", {"t": f"Lab {n.group(1) if n else ''}".strip(), "hw": key_for(aid)}))
            emit_due(aid, f"Lab {n.group(1) if n else ''} due".strip())   # lab report due on its Canvas due date
        elif "due" in low:
            if low.startswith("lab"):
                pass                                                       # lab due already emitted on the lab day
            else:
                aid = m_homework(ln)
                lbl = re.sub(r"(?i)\s*due\.?$", "", ln)
                lbl = re.sub(r"(?i)homework\s*#?\s*", "Chapter HW ", lbl).strip()
                emit_due(aid, lbl + " due")                                # chapter homework -> Canvas due date
                if not aid: unmatched.append((r, ln))
        else:
            if lect_done: continue
            lect_done = True
            aid = m_daily(ln)            # matched only to link the HW due pill; the lesson pill itself is unlinked
            paid = m_practice(ln)
            buckets.append(("lect", {"t": clean(ln), "hw": None}))        # lecture: NO link (future: notes + video)
            emit_due(aid, "HW: " + clean(ln), paid)                        # daily homework -> due-day pill + practice sublink
            if not aid: unmatched.append((r, "DAILY: " + ln))

    order = {"lect":1,"exam":2,"quiz":3,"lab":4,"due":5,"rev":6}
    for kind, ex in sorted(buckets, key=lambda b: order[b[0]]):
        for d, pers in groups.items():
            ev = {"d": iso(d), "p": pcode(pers), "k": kind}; ev.update(ex); ev.setdefault("hw", None)
            events.append(ev)

# hand-placed fall reviews (Exam 2 / Exam 3 / Fall Final) -> assignment ids
for rn in ("2", "3", "F"):
    aid = m_review(rn)
    if aid: key_for(aid)
    else: unmatched.append(("EXTRA", "review " + rn))

ordk = {"info":0,"lect":1,"exam":2,"quiz":3,"lab":4,"due":5,"rev":6}
events.sort(key=lambda e: (e["d"], ordk.get(e["k"], 9)))

# ---- assemble the page -----------------------------------------------------
events_js = "const EVENTS = " + json.dumps(events, separators=(",", ":")) \
    .replace("},{", "},\n  {").replace("[{", "[\n  {").replace("}]", "}\n];") + ";"
aids_js = "const ASSIGNMENT_IDS = {\n" + "".join(f"  '{k}': {v},\n" for k, v in AID.items()) + "};"

# EXTRAS reviews reference ID-based keys (must match key_for)
rev_keys = {rn: f"A{m_review(rn)}" for rn in ("2", "3", "F")}

tpl = pathlib.Path(TPL).read_text()
tpl = tpl.replace("__COURSE__", COURSE_ID).replace("__AIDS__", aids_js).replace("__EVENTS__", events_js)
# point the hand-placed EXTRAS reviews at the matched keys
tpl = tpl.replace("'Exam_2_Review_Build_On'", f"'{rev_keys['2']}'")
tpl = tpl.replace("'Exam_3_Chapter_4_review_Build_On'", f"'{rev_keys['3']}'")
tpl = tpl.replace("'Semester_1_Final_Review'", f"'{rev_keys['F']}'")
pathlib.Path(OUT).write_text(tpl)

print(f"course {COURSE_ID}: {len(events)} events, {len(AID)} assignment ids matched")
print(f"UNMATCHED ({len(unmatched)}):")
for r, t in unmatched: print(f"  row {r}: {t}")
