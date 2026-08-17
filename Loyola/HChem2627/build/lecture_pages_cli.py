#!/usr/bin/env python3
"""
lecture_pages_cli.py — add / move / delete / show entries in lecture_pages.json

Run this from inside the build/ folder (same place you run build_page.py).
After any add/move/delete, run `python3 build_page.py` to regenerate
../index.html.

Commands
--------
show                                   list every entry, soonest date first
show --type lab                        only lab entries (lecture/lab/exam)
show --id LAB3                         just one entry, full detail

move L09 2026-09-16                    set periods 5, 6 AND 7 to this date
move LAB2 2026-09-04 --period 6        set only period 6
move EXAM1_DAY2 2026-09-22 --period 5,7
move L14 --shift 2                     push all set dates forward 2 days
move L14 --shift -1                    pull all set dates back 1 day

add LAB7 --type lab --title "Lab 7" --page-url lab-7
add EXAM4_DAY1 --type exam --title "Exam 4 (Day 1)" --page-url exam-4 \
    --date 2027-01-20
add L38 --type lecture --title "10.1 Gas Pressure" --page-url l38-...

delete LAB7                            remove an entry entirely

Dates are always YYYY-MM-DD. An id's "dates" dict holds one value per
period ("5", "6", "7"); a null/missing period just falls back to whatever
the schedule spreadsheet says for that row (see build_page.py).
"""
import argparse, json, os, sys, datetime

PAGES = "lecture_pages.json"
PERIODS = ("5", "6", "7")


def load():
    if not os.path.exists(PAGES):
        sys.exit(f"{PAGES} not found in {os.getcwd()} — run this from the build/ folder")
    with open(PAGES) as f:
        return json.load(f)


def save(data):
    with open(PAGES, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")


def parse_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        sys.exit(f"bad date {s!r} — use YYYY-MM-DD")


def parse_periods(s):
    if s is None:
        return list(PERIODS)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for p in parts:
        if p not in PERIODS:
            sys.exit(f"bad --period {p!r} — must be 5, 6, 7, or a comma list like 5,7")
    return parts


def fmt_dates(entry):
    d = entry.get("dates") or {}
    return tuple(d.get(p) or "—" for p in PERIODS)


def sort_key(item):
    _id, entry = item
    d = entry.get("dates") or {}
    dates = [d.get(p) for p in PERIODS if d.get(p)]
    return (min(dates) if dates else "9999-99-99", _id)


def cmd_show(args, data):
    if args.id:
        entry = data.get(args.id)
        if not entry:
            sys.exit(f"no such id: {args.id}")
        print(json.dumps(entry, indent=1))
        return
    items = list(data.items())
    if args.type:
        items = [(i, e) for i, e in items if e.get("type") == args.type]
    items.sort(key=sort_key)
    w_id = max([len(i) for i, _ in items] + [2])
    print(f"{'ID'.ljust(w_id)}  {'TYPE':7} {'P5':10} {'P6':10} {'P7':10} TITLE")
    for _id, entry in items:
        p5, p6, p7 = fmt_dates(entry)
        print(f"{_id.ljust(w_id)}  {entry.get('type',''):7} {p5:10} {p6:10} {p7:10} {entry.get('title','')}")


def cmd_move(args, data):
    entry = data.get(args.id)
    if not entry:
        sys.exit(f"no such id: {args.id} (use 'show' to list ids, or 'add' to create it)")
    dates = entry.setdefault("dates", {p: None for p in PERIODS})
    periods = parse_periods(args.period)

    if args.shift is not None:
        for p in periods:
            cur = dates.get(p)
            if not cur:
                continue
            new = parse_date(cur) + datetime.timedelta(days=args.shift)
            dates[p] = new.isoformat()
    else:
        if not args.date:
            sys.exit("move needs a date (YYYY-MM-DD) or --shift N")
        d = parse_date(args.date).isoformat()
        for p in periods:
            dates[p] = d

    save(data)
    p5, p6, p7 = fmt_dates(entry)
    print(f"{args.id}: P5={p5}  P6={p6}  P7={p7}")


def cmd_add(args, data):
    if args.id in data:
        sys.exit(f"{args.id} already exists — use 'move' to change its date, or 'delete' first")
    entry = {
        "type": args.type,
        "title": args.title,
        "page_url": args.page_url,
        "html_url": f"https://loyolahs.instructure.com/courses/{args.course}/pages/{args.page_url}",
        "published": False,
        "dates": {p: None for p in PERIODS},
    }
    if args.date:
        d = parse_date(args.date).isoformat()
        for p in PERIODS:
            entry["dates"][p] = d
    data[args.id] = entry
    save(data)
    print(f"added {args.id}")
    cmd_show(argparse.Namespace(id=args.id), data)


def cmd_delete(args, data):
    if args.id not in data:
        sys.exit(f"no such id: {args.id}")
    if not args.yes:
        ans = input(f"delete {args.id} ({data[args.id].get('title','')})? [y/N] ")
        if ans.strip().lower() != "y":
            print("cancelled")
            return
    del data[args.id]
    save(data)
    print(f"deleted {args.id}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="list entries")
    p_show.add_argument("--type", choices=["lecture", "lab", "exam"])
    p_show.add_argument("--id")
    p_show.set_defaults(func=cmd_show)

    p_move = sub.add_parser("move", help="change an entry's date(s)")
    p_move.add_argument("id")
    p_move.add_argument("date", nargs="?", help="YYYY-MM-DD")
    p_move.add_argument("--period", help="5, 6, 7, or comma list (default: all three)")
    p_move.add_argument("--shift", type=int, help="shift already-set dates by N days instead of setting an absolute date")
    p_move.set_defaults(func=cmd_move)

    p_add = sub.add_parser("add", help="add a new lecture/lab/exam entry")
    p_add.add_argument("id")
    p_add.add_argument("--type", required=True, choices=["lecture", "lab", "exam"])
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--page-url", required=True, help="Canvas page slug, e.g. lab-7")
    p_add.add_argument("--date", help="YYYY-MM-DD, applied to all three periods")
    p_add.add_argument("--course", default="6624")
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="remove an entry")
    p_del.add_argument("id")
    p_del.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_del.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    data = load()
    args.func(args, data)


if __name__ == "__main__":
    main()
