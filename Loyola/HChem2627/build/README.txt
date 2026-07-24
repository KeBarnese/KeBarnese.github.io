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

Set due dates + publish in Canvas (SIS stays OFF):
  export CANVAS_TOKEN=...
  python3 canvas_due_publish.py            # preview
  python3 canvas_due_publish.py --live --apply
