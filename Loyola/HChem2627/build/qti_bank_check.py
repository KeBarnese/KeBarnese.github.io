#!/usr/bin/env python3
"""
qti_bank_check.py — parse a Canvas QTI 1.2 quiz/item-bank export (the .zip
you get from a New Quiz's "Export" button, which fully resolves any linked
item bank into <objectbank><item>... entries) and report:
  1. a clean, readable dump of every question + choices + correct answer(s)
  2. structural red flags: no correct answer set, more than one correct
     answer on a single-answer item, a correct-answer id that doesn't match
     any actual choice, duplicate/near-duplicate choice text, empty stems

This is a STRUCTURAL checker -- it can't judge whether the marked-correct
chemistry answer is actually the right chemistry, only whether the file
itself is internally consistent. Content correctness still needs a human
(or a read-through of the printed dump) to sanity-check.

USAGE
  python3 qti_bank_check.py path/to/export.zip
  python3 qti_bank_check.py path/to/some.xml.qti
  python3 qti_bank_check.py path/to/folder-with-many-zips/
"""
import sys, os, re, glob, zipfile, html
import xml.etree.ElementTree as ET

NS = {"q": "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"}


def strip_html(s):
    if s is None:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_qti_files(path):
    out = []
    if os.path.isdir(path):
        for p in glob.glob(os.path.join(path, "**", "*"), recursive=True):
            if p.lower().endswith((".qti", ".xml.qti")):
                out.append(("file", p))
            elif p.lower().endswith(".zip"):
                out.append(("zip", p))
    elif path.lower().endswith(".zip"):
        out.append(("zip", path))
    else:
        out.append(("file", path))
    return out


def load_qti_roots(path):
    """Yield (source_label, ET.Element root) for every QTI item file found."""
    for kind, p in find_qti_files(path):
        if kind == "zip":
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    if name.lower().endswith((".qti", ".xml.qti")):
                        data = z.read(name)
                        try:
                            root = ET.fromstring(data)
                        except ET.ParseError as e:
                            print(f"!! could not parse {p}:{name} -- {e}")
                            continue
                        yield f"{p}:{name}", root
        else:
            with open(p, "rb") as f:
                data = f.read()
            try:
                root = ET.fromstring(data)
            except ET.ParseError as e:
                print(f"!! could not parse {p} -- {e}")
                continue
            yield p, root


def qtimeta(item_el, label):
    for f in item_el.findall(".//q:qtimetadatafield", NS):
        lbl = f.find("q:fieldlabel", NS)
        if lbl is not None and lbl.text == label:
            entry = f.find("q:fieldentry", NS)
            return entry.text if entry is not None else None
    return None


def parse_item(item_el):
    qtype = qtimeta(item_el, "question_type") or "unknown"
    stem_el = item_el.find(".//q:presentation/q:material/q:mattext", NS)
    stem = strip_html(stem_el.text if stem_el is not None else "")
    issues = []

    if not stem:
        issues.append("empty question stem")

    resprocessing = item_el.find("q:resprocessing", NS)

    if qtype in ("multiple_choice_question", "true_false_question", "multiple_answers_question"):
        response_lid = item_el.find(".//q:response_lid", NS)
        choices = {}
        if response_lid is not None:
            for lbl in response_lid.findall(".//q:response_label", NS):
                ident = lbl.get("ident")
                mtext = lbl.find(".//q:mattext", NS)
                choices[ident] = strip_html(mtext.text if mtext is not None else "")

        # dedupe check
        seen = {}
        for ident, text in choices.items():
            key = text.lower().strip()
            if key and key in seen:
                issues.append(f"duplicate choice text: \"{text}\" ({seen[key]} & {ident})")
            else:
                seen[key] = ident

        correct_idents = []
        if resprocessing is not None:
            for cond in resprocessing.findall(".//q:respcondition", NS):
                setvar = cond.find(".//q:setvar", NS)
                is_full_credit = setvar is not None and setvar.text and setvar.text.strip() in ("100",)
                is_additive = setvar is not None and setvar.get("action") == "Add"
                if is_full_credit or is_additive:
                    for veq in cond.findall(".//q:varequal", NS):
                        correct_idents.append(veq.text)

        unknown = [c for c in correct_idents if c not in choices]
        if unknown:
            issues.append(f"correct-answer id(s) not found among choices: {unknown}")
        if qtype == "multiple_choice_question" and len([c for c in correct_idents if c in choices]) > 1:
            issues.append(f"single-answer question has >1 correct answer marked: {correct_idents}")
        if not correct_idents:
            issues.append("no correct answer found (resprocessing empty/missing)")

        correct_text = [choices.get(c, f"<missing:{c}>") for c in correct_idents]
        return {"type": qtype, "stem": stem, "choices": list(choices.values()),
                "correct": correct_text, "issues": issues}

    if qtype == "matching_question":
        pairs = []
        shared_choice_text = {}
        for rl in item_el.findall(".//q:response_lid", NS):
            for lbl in rl.findall(".//q:response_label", NS):
                ident = lbl.get("ident")
                mtext = lbl.find(".//q:mattext", NS)
                shared_choice_text[ident] = strip_html(mtext.text if mtext is not None else "")
        for rl in item_el.findall(".//q:response_lid", NS):
            rl_ident = rl.get("ident", "")
            left_mtext = rl.find("q:material/q:mattext", NS)
            left_text = strip_html(left_mtext.text if left_mtext is not None else "")
            correct_right = None
            if resprocessing is not None:
                for cond in resprocessing.findall(".//q:respcondition", NS):
                    for veq in cond.findall(".//q:varequal", NS):
                        if veq.get("respident") == rl_ident:
                            correct_right = shared_choice_text.get(veq.text, f"<missing:{veq.text}>")
            if left_text:
                pairs.append((left_text, correct_right))
                if correct_right is None:
                    issues.append(f"no match found for left item: \"{left_text}\"")
        return {"type": qtype, "stem": stem,
                "choices": [f"{l} -> {r}" for l, r in pairs],
                "correct": [f"{l} -> {r}" for l, r in pairs if r], "issues": issues}

    if qtype == "ordering_question":
        idents_in_order = []
        text_by_ident = {}
        for lbl in item_el.findall(".//q:response_label", NS):
            ident = lbl.get("ident")
            mtext = lbl.find(".//q:mattext", NS)
            text_by_ident[ident] = strip_html(mtext.text if mtext is not None else "")
        correct_order = []
        if resprocessing is not None:
            cond = resprocessing.find(".//q:respcondition", NS)
            if cond is not None:
                for veq in cond.findall(".//q:varequal", NS):
                    correct_order.append(veq.text)
        unknown = [c for c in correct_order if c not in text_by_ident]
        if unknown:
            issues.append(f"correct-order id(s) not found among choices: {unknown}")
        if len(set(correct_order)) != len(correct_order):
            issues.append("correct order lists the same choice more than once")
        if not correct_order:
            issues.append("no correct order found (resprocessing empty/missing)")
        return {"type": qtype, "stem": stem,
                "choices": list(text_by_ident.values()),
                "correct": [text_by_ident.get(c, f"<missing:{c}>") for c in correct_order],
                "issues": issues}

    if qtype in ("short_answer_question", "fill_in_multiple_blanks_question"):
        # response_str/render_fib blanks; accepted answers are literal text
        # inside <varequal>, not ident lookups (no response_label choices).
        blanks = {}   # respident -> [accepted answers]
        for rstr in item_el.findall(".//q:response_str", NS):
            blanks[rstr.get("ident", "response1")] = []
        if not blanks:
            blanks["response1"] = []
        if resprocessing is not None:
            for cond in resprocessing.findall(".//q:respcondition", NS):
                setvar = cond.find(".//q:setvar", NS)
                is_credit = setvar is not None and setvar.text and setvar.text.strip() not in ("0",)
                if not is_credit:
                    continue
                for veq in cond.findall(".//q:varequal", NS):
                    rid = veq.get("respident", "response1")
                    blanks.setdefault(rid, []).append(veq.text)
        no_answers = [rid for rid, answers in blanks.items() if not answers]
        if no_answers:
            issues.append(f"blank(s) with no accepted answer found: {no_answers}")
        correct = [f"{rid}: {' / '.join(a or '' for a in answers)}" for rid, answers in blanks.items()]
        return {"type": qtype, "stem": stem, "choices": [], "correct": correct, "issues": issues}

    if qtype == "numerical_question":
        conds = []
        if resprocessing is not None:
            for cond in resprocessing.findall(".//q:respcondition", NS):
                setvar = cond.find(".//q:setvar", NS)
                if not (setvar is not None and setvar.text and setvar.text.strip() not in ("0",)):
                    continue
                cv = cond.find("q:conditionvar", NS)
                if cv is None:
                    continue
                eq = cv.find(".//q:varequal", NS)
                gte = cv.find(".//q:vargte", NS)
                lte = cv.find(".//q:varlte", NS)
                if eq is not None:
                    conds.append(f"= {eq.text}")
                elif gte is not None and lte is not None:
                    conds.append(f"[{gte.text} .. {lte.text}]")
                elif gte is not None:
                    conds.append(f">= {gte.text}")
                elif lte is not None:
                    conds.append(f"<= {lte.text}")
        if not conds:
            issues.append("no numeric accepted answer/range found (resprocessing empty or unrecognized shape)")
        return {"type": qtype, "stem": stem, "choices": [], "correct": conds, "issues": issues}

    if qtype in ("essay_question", "file_upload_question", "text_only_question"):
        # no answer key expected -- not an error, just informational
        return {"type": qtype, "stem": stem, "choices": [], "correct": ["(no answer key -- open response)"], "issues": issues}

    # unsupported/unseen type (e.g. calculated_question, multiple_dropdowns_question,
    # or anything else) -- don't silently drop it, dump the raw XML for manual review.
    raw = ET.tostring(item_el, encoding="unicode")
    raw_compact = re.sub(r"\s+", " ", raw).strip()
    issues.append(f"unhandled question_type '{qtype}' -- raw item XML follows for manual review")
    return {"type": qtype, "stem": stem, "choices": [], "correct": [],
            "issues": issues, "raw": raw_compact}


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 qti_bank_check.py <export.zip|file.xml.qti|folder>")
    path = sys.argv[1]

    total_items = 0
    total_issues = 0
    for source, root in load_qti_roots(path):
        bank_title = None
        title_field = root.find(".//q:qtimetadatafield[q:fieldlabel='bank_title']/q:fieldentry", NS)
        if title_field is not None:
            bank_title = title_field.text
        items = root.findall(".//q:item", NS)
        if not items:
            continue
        print(f"\n{'='*90}\n{source}")
        if bank_title:
            print(f"bank: {bank_title}")
        print(f"{len(items)} item(s)\n{'-'*90}")
        for item_el in items:
            parsed = parse_item(item_el)
            total_items += 1
            flag = " ⚠" if parsed["issues"] else ""
            print(f"\n[{parsed['type']}]{flag} {parsed['stem']}")
            mc_like = parsed["type"] in ("multiple_choice_question", "true_false_question",
                                          "multiple_answers_question")
            for c in parsed["choices"]:
                mark = " *" if (mc_like and c in parsed["correct"]) else ""
                print(f"    - {c}{mark}")
            if not mc_like and parsed["correct"]:
                print(f"    correct: {parsed['correct']}")
            for issue in parsed["issues"]:
                print(f"    !! {issue}")
                total_issues += 1
            if "raw" in parsed:
                print(f"    raw: {parsed['raw'][:800]}")

    print(f"\n{'='*90}\n{total_items} item(s) checked, {total_issues} structural issue(s) flagged.")
    if total_items == 0:
        print("(no <item> elements found -- check the file/zip actually contains QTI content)")


if __name__ == "__main__":
    main()
