"""
assignment_kind.py — classify a Canvas assignment's Chem 4 / Honors Chem "kind"
from its title. Shared by canvas_pull_due.py (stamps new pulls) and by the
one-time due_dates.json backfill. Keep this the single source of truth for
the classification rules so the two never drift apart.

Kinds:
  daily_homework   - "<section>, ... Daily Homework" (needs a practice sub-link)
  chapter_homework - "Chapter N Homework[, part P]" / "Chapter N-M Homework"
  lab_due          - "Lab N" (the lab report's Canvas due date)
  postlab_quiz      - "Post-Lab Quiz #N" / "Post Lab Quiz #N"
  quiz              - any other "... Quiz #N ..." / "quiz #N ..."
  info              - "Introduction" (first-day marker, no due-pill styling)
  other             - anything that doesn't match a rule above (e.g. "Safety
                       Contract") -- still gets a plain due pill, but is
                       flagged in the build's UNMATCHED report so a human can
                       add a rule or an explicit override if it's wrong.
"""
import re


def classify(title):
    t = (title or "").strip()
    low = t.lower()

    if "daily homework" in low:
        return "daily_homework"
    if low.startswith("chapter") and "homework" in low:
        return "chapter_homework"
    if re.fullmatch(r"lab\s*\d+", low):
        return "lab_due"
    if re.search(r"post[\s-]?lab", low) and "quiz" in low:
        return "postlab_quiz"
    if "quiz" in low:
        return "quiz"
    if low == "introduction":
        return "info"
    return "other"


if __name__ == "__main__":
    # quick self-test against the titles we know about
    samples = [
        "1.2, Material Classification, Daily Homework",
        "Chapter 1 Homework part 1",
        "Chapter 6-9 Homework",
        "Lab 3",
        "Post-Lab Quiz #3",
        "Post Lab Quiz #2",
        "Quiz #2 Dimensional Analysis",
        "quiz #4",
        "Introduction",
        "Safety Contract",
    ]
    for s in samples:
        print(f"{classify(s):18s} <- {s}")
