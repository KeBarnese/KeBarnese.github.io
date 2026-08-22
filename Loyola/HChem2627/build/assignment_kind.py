"""
assignment_kind.py — classify a Canvas assignment's Chem 4 / Honors Chem "kind"
from its title. Shared by canvas_pull_due.py (stamps new pulls) and by the
one-time due_dates.json backfill. Keep this the single source of truth for
the classification rules so the two never drift apart.

Kinds:
  daily_homework   - "<section>, ... Daily Homework" (needs a practice sub-link).
                     Also "Introduction" -- the first-day assignment is graded
                     as a daily homework, so it is classified as one.
  chapter_homework - "Chapter N Homework[, part P]" / "Chapter N-M Homework"
  worksheet        - the graded in-class worksheets, "Worksheet N: <topic>"
  planner_check    - the biweekly planner/notes checks,
                     "Planner & Notes Check N"
  gradebook_total  - an assignment that only CARRIES POINTS and must not get a
                     calendar pill: the per-exam containers ("Exam 2 (Ch. 3)",
                     which holds Day 1 + Day 2 summed) and the curved
                     "Semester 1 Final Exam". The Day 1 / Day 2 pills that do
                     appear on the calendar come from lecture_pages.json.
                     build_page.py skips these outright.
  lab_due          - "Lab N" (the lab report's Canvas due date), and the
                     "Safety Contract", which is graded with the labs
  postlab_quiz      - "Post-Lab Quiz #N" / "Post Lab Quiz #N"
  quiz              - any other "... Quiz #N ..." / "quiz #N ..."
  info              - no longer assigned automatically (kept so an entry in
                     due_dates.json that was hand-set to "info" still renders).
  other             - anything that doesn't match a rule above -- still gets a
                       plain due pill, but is flagged in the build's UNMATCHED
                       report so a human can add a rule or an explicit
                       override if it's wrong. Nothing in the course currently
                       lands here; a new [KIND?] warning means a title arrived
                       that no rule below anticipated.

NOTE: build_page.py has its own kind -> (label, pill) mapping. If you add a
kind here, add a branch there too, or it falls through to "other" and gets
flagged as unclassified on every build.
"""
import re


def classify(title):
    t = (title or "").strip()
    low = t.lower()

    if "daily homework" in low:
        return "daily_homework"
    # the first-day "Introduction" assignment is graded as a daily homework
    if low == "introduction":
        return "daily_homework"
    if low.startswith("chapter") and "homework" in low:
        return "chapter_homework"
    # Points-only gradebook containers: the per-exam totals ("Exam 3 (ch. 4-5)"
    # = Day 1 + Day 2) and the curved final. These must not become pills; the
    # Day 1 / Day 2 pills come from lecture_pages.json. "review" is excluded so
    # an exam-review assignment can never be swallowed by this rule.
    if "review" not in low and (re.match(r"exam\s*\d+\b", low) or "final exam" in low):
        return "gradebook_total"
    # graded in-class worksheets -- "worksheet" anywhere in the title, so both
    # "Worksheet 4: Net Ionic Equations" and "Net Ionic Equations Worksheet" hit
    if re.search(r"\bworksheets?\b", low):
        return "worksheet"
    # biweekly planner / notes checks
    if re.search(r"\bcheck(s|ed)?\b", low) and ("planner" in low or "notes" in low):
        return "planner_check"
    if re.fullmatch(r"lab\s*\d+", low):
        return "lab_due"
    # the safety contract is graded alongside the lab reports
    if "safety contract" in low:
        return "lab_due"
    if re.search(r"post[\s-]?lab", low) and "quiz" in low:
        return "postlab_quiz"
    if "quiz" in low:
        return "quiz"
    return "other"


if __name__ == "__main__":
    # quick self-test against the titles we know about
    samples = [
        ("1.2, Material Classification, Daily Homework", "daily_homework"),
        ("Chapter 1 Homework part 1",                    "chapter_homework"),
        ("Chapter 6-8 Homework",                         "chapter_homework"),
        ("Lab 3",                                        "lab_due"),
        ("Post-Lab Quiz #3",                             "postlab_quiz"),
        ("Post Lab Quiz #2",                             "postlab_quiz"),
        ("Quiz #2 Dimensional Analysis",                 "quiz"),
        ("quiz #4",                                      "quiz"),
        ("Quiz #8 (ch. 7-8)",                            "quiz"),
        ("Introduction",                                 "daily_homework"),
        # points-only containers -> no calendar pill
        ("Exam 1 (Chapters 1 & 2)",                      "gradebook_total"),
        ("Exam 2 (Ch. 3)",                               "gradebook_total"),
        ("Exam 3 (ch. 4-5)",                             "gradebook_total"),
        ("Semester 1 Final Exam 2026",                    "gradebook_total"),
        ("Exam 4 (Ch. 6-8)",                             "gradebook_total"),
        # ...but an exam REVIEW must never be swallowed by that rule
        ("Exam 1 Review - Build On",                     "other"),
        ("Semester 1 Final Review",                      "other"),
        ("Quiz #5, ion review",                          "quiz"),
        # graded with the labs
        ("Safety Contract",                              "lab_due"),
        # the 7 worksheets
        ("Worksheet 1: Dimensional Analysis",            "worksheet"),
        ("Worksheet 2: Nomenclature",                    "worksheet"),
        ("Worksheet 3: Stoichiometry / Limiting Reactant","worksheet"),
        ("Worksheet 4: Net Ionic Equations",             "worksheet"),
        ("Worksheet 5: Enthalpies of Formation",         "worksheet"),
        ("Worksheet 6: Electron Configuration",          "worksheet"),
        ("Worksheet 7: Lewis Structures",                "worksheet"),
        ("Net Ionic Equations Worksheet",                "worksheet"),
        # the 9 planner/notes checks
        ("Planner & Notes Check 1",                      "planner_check"),
        ("Planner & Notes Check 9",                      "planner_check"),
        ("Notes Check 3",                                "planner_check"),
        ("Planner Check",                                "planner_check"),
    ]
    bad = 0
    for s, want in samples:
        got = classify(s)
        flag = "ok  " if got == want else "FAIL"
        if got != want:
            bad += 1
        print(f"  {flag} {got:18s} <- {s}"
              + ("" if got == want else f"   (expected {want})"))
    print(f"\n{len(samples) - bad}/{len(samples)} passed")
    raise SystemExit(1 if bad else 0)
