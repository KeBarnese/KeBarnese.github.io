Honors Chem 26-27 schedule page — build folder
Run everything from inside this build/ folder.

Change a due date:
  1) edit due_dates.json (find the assignment by "_title"; edit the "5"/"6"/"7" date)
  2) python3 build_page.py        -> writes ../index.html
  3) commit/push ../index.html

Refresh IDs after copying/renaming assignments in Canvas:
  export CANVAS_TOKEN=...
  python3 canvas_get_ids.py > canvas_ids_6624_renamed.txt
  python3 build_page.py

Pull real due dates from Canvas instead of editing by hand:
  export CANVAS_TOKEN=...
  python3 canvas_pull_due.py       -> rewrites due_dates.json
  python3 build_page.py

Lecture / lab / exam pills link to their Canvas pages, and can be moved by
hand without touching the schedule spreadsheet:
  lecture_pages.json now holds one entry per lecture (L01, L02, ...), lab
  (LAB1-LAB6) and exam day (EXAM1_DAY1, EXAM1_DAY2, EXAM2_DAY1, ...,
  FINAL_DAY1, FINAL_DAY2). Each entry has "page_url" (the Canvas page slug
  it links to) and "dates" (the day it happens for periods 5/6/7).

  * Editing an entry's "dates" moves that lecture/lab/exam to a new day on
    the calendar -- no spreadsheet edit, no re-running any Canvas script.
    A period left null (or a whole id you haven't touched) just falls back
    to whatever the schedule spreadsheet already says, so nothing breaks
    until you start moving things.
  * Exam ids come in DAY1/DAY2 pairs pointing at the SAME Canvas page (an
    exam usually spans two class meetings but is one page of material).
  * Lecture ids are still matched to spreadsheet rows via notes/map.json,
    same as before; lab/exam ids are matched straight off the schedule
    line's text ("Lab 4", "Exam 2 ... part 1", etc.).

  Easiest way to edit: use lecture_pages_cli.py (see below) instead of
  hand-editing the json. Either way, always follow up with:
    python3 build_page.py
  If lecture_pages.json is missing entirely, pills just go back to being
  plain unlinked labels -- nothing breaks.

lecture_pages_cli.py — add / move / delete / show entries by hand:
  python3 lecture_pages_cli.py show                    # everything, soonest first
  python3 lecture_pages_cli.py show --type lab
  python3 lecture_pages_cli.py move LAB3 2026-09-26     # all 3 periods
  python3 lecture_pages_cli.py move EXAM1_DAY2 2026-09-22 --period 5,7
  python3 lecture_pages_cli.py move L14 --shift 2       # push 2 days later
  python3 lecture_pages_cli.py add LAB7 --type lab --title "Lab 7" --page-url lab-7
  python3 lecture_pages_cli.py delete LAB7
  Then: python3 build_page.py

Set due dates + publish in Canvas (SIS stays OFF):
  export CANVAS_TOKEN=...
  python3 canvas_due_publish.py            # preview
  python3 canvas_due_publish.py --live --apply
