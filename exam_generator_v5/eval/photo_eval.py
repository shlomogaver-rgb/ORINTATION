"""PHOTO test set with free ground truth + the real measurement of reading reliability.

Ground truth comes from Bagrut PDFs: every question region is cut exactly like MODE B does it, its PDF text layer is the
truth (Hebrew words and numbers), and the question image is turned into phone photos (simulated at three levels, or
REAL photos you take of the printed pages).

    python eval/photo_eval.py build  --pdf "tests/documents/*.pdf" --out eval/photo_set
    python eval/photo_eval.py offline --set eval/photo_set           # no API: rectification + line split + OCR proxy
    GEMINI_API_KEY=... python eval/photo_eval.py real --set eval/photo_set [--reader claude] [--limit 20]

Real photos: put <name>.jpg next to <name>.json {"truth": "<question id from index.json>"} in <set>/real/.

The number that matters (real mode) is SILENT ERRORS: words/numbers the reconstruction got wrong that the second reading
did NOT flag. Target: 0. Everything flagged goes to the teacher; everything silent goes to the students."""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEB = re.compile(r"[א-ת][א-ת\"'׳״]+")
NUM = re.compile(r"\d+(?:[.,]\d+)*")
IGNORE = {"המשך", "בעמוד"}


def bag(text: str) -> Counter:
    from reading.consensus import norm_number, norm_word
    words = [norm_word(w) for w in HEB.findall(text or "")]
    nums = [norm_number(n) for n in NUM.findall((text or "").replace("{,}", ","))]
    return Counter(w for w in words if w not in IGNORE and len(w) > 1) + Counter("#" + n for n in nums)


# ------------------------------------------------------------------ build
def build(pdfs: list[str], out: Path, levels=("mild", "medium", "hard")) -> None:
    from PIL import Image

    from document.reconstruct import questions_data
    from document.structure import build_document
    from reading.simulate import phone_photo
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for pdf in pdfs:
        data = Path(pdf).read_bytes()
        model = build_document(data)
        stem = re.sub(r"\W+", "_", Path(pdf).stem).strip("_")
        for q in questions_data(data, model):
            doc = q["document"]
            for part, img_bytes in enumerate(q["images"], 1):
                qid = f"{stem}_q{q['question_number']}_{part}"
                d = out / qid
                d.mkdir(exist_ok=True)
                (d / "clean.png").write_bytes(img_bytes)
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                for k, lvl in enumerate(levels):
                    phone_photo(img, lvl, seed=hash(qid) % 1000 + k).save(d / f"photo_{lvl}.jpg", quality=92)
                index[qid] = {"pdf": pdf, "question": q["question_number"], "part": part,
                              "truth_lines": doc.get("source_lines") if part == 1 else [],
                              "truth_text": doc.get("text_layer", "")}
        print(f"{pdf}: {len(model.questions)} questions")
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(index)} question images -> {out}")


def _items(set_dir: Path, levels: list[str]):
    index = json.loads((set_dir / "index.json").read_text(encoding="utf-8"))
    for qid, it in index.items():
        truth = "\n".join(it["truth_lines"]) or it["truth_text"]
        for lvl in levels:
            p = set_dir / qid / f"photo_{lvl}.jpg"
            if p.exists():
                yield qid, lvl, p.read_bytes(), truth
    real = set_dir / "real"
    for jp in sorted(real.glob("*.jpg")) if real.exists() else []:
        meta = json.loads(jp.with_suffix(".json").read_text(encoding="utf-8"))
        it = index[meta["truth"]]
        yield meta["truth"], "real:" + jp.stem, jp.read_bytes(), "\n".join(it["truth_lines"]) or it["truth_text"]


def _acc(truth: Counter, got: Counter, numbers: bool) -> float:
    t = Counter({k: v for k, v in truth.items() if k.startswith("#") == numbers})
    return sum((t & got).values()) / max(1, sum(t.values()))


# ------------------------------------------------------------------ offline (no API)
def offline(set_dir: Path, levels: list[str]) -> dict:
    from PIL import Image

    from reading.lines import split_lines
    from reading.rectify import rectify_photo_bytes
    try:
        import pytesseract
    except Exception:
        pytesseract = None
    rows = []
    for qid, lvl, photo, truth in _items(set_dir, levels):
        t0 = time.time()
        flat, info = rectify_photo_bytes(photo)
        n_lines = len(split_lines(flat, 1))
        row = {"id": qid, "level": lvl, "perspective": info.get("perspective"), "lines": n_lines,
               "truth_lines": len([l for l in truth.split("\n") if l.strip()]), "seconds": round(time.time() - t0, 2)}
        if pytesseract:
            tb = bag(truth)
            for name, img in (("before", photo), ("after", flat)):
                txt = pytesseract.image_to_string(Image.open(io.BytesIO(img)), lang="heb+eng", config="--psm 4")
                row[f"ocr_{name}_words"] = round(_acc(tb, bag(txt), False), 3)
                row[f"ocr_{name}_numbers"] = round(_acc(tb, bag(txt), True), 3)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    return {"rows": rows}


# ------------------------------------------------------------------ real (Gemini reader A + reader B)
def real(set_dir: Path, levels: list[str], reader_name: str, limit: int | None) -> dict:
    import exam_core as c
    import reading
    from reading.rectify import rectify_photo_bytes
    from reading.second_reader import make_reader

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is required for the real run")
    service = c.GeminiService(key, os.environ.get("GEMINI_MODEL") or c.DEFAULT_MODEL)
    reader = make_reader(service, {"SECOND_READER": reader_name, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY")})
    meta = {"language": "עברית", "exam_name": "eval"}
    rows = []
    for n, (qid, lvl, photo, truth) in enumerate(_items(set_dir, levels)):
        if limit and n >= limit:
            break
        flat, _ = rectify_photo_bytes(photo)
        question = {"question_number": 1, "points": 100.0, "images": [flat]}
        t0 = time.time()
        try:
            q = c.analyze_question(service, meta, question)
            if reader_name == "claude":
                reading.run_reading_check(service, q, question, reader=reader)
        except Exception as exc:
            rows.append({"id": qid, "level": lvl, "error": str(exc)[:300]})
            continue
        tb = bag(truth)
        ab = bag("\n".join(reading.texts_of(q)))
        wrong = (tb - ab) + (ab - tb)                          # every word / number the reconstruction got wrong
        report = (q.reading_check or {}).get("report") or {}
        flagged = Counter()
        for cf in report.get("conflicts", []):
            flagged += bag(f"{cf.get('a', '')} {cf.get('b', '')}")
        whole_question_flagged = report.get("status") == "INCOMPLETE" or bool((q.reading_check or {}).get("error"))
        silent = Counter() if whole_question_flagged else (wrong - flagged)
        rows.append({
            "id": qid, "level": lvl, "seconds": round(time.time() - t0, 1),
            "a_words": round(_acc(tb, ab, False), 3), "a_numbers": round(_acc(tb, ab, True), 3),
            "errors": sum(wrong.values()), "flagged_conflicts": len(report.get("conflicts", [])),
            "silent_errors": sum(silent.values()), "silent_examples": list(silent)[:8],
            "status": report.get("status") or (q.reading_check or {}).get("error", "")[:60],
        })
        print(json.dumps(rows[-1], ensure_ascii=False))
    ok = [r for r in rows if "error" not in r]
    summary = {
        "items": len(rows), "failed_calls": len(rows) - len(ok),
        "questions_with_silent_errors": sum(1 for r in ok if r["silent_errors"]),
        "silent_errors_total": sum(r["silent_errors"] for r in ok),
        "errors_total": sum(r["errors"] for r in ok),
        "questions_flagged": sum(1 for r in ok if r["flagged_conflicts"]),
        "mean_a_words": round(sum(r["a_words"] for r in ok) / max(1, len(ok)), 3),
        "mean_a_numbers": round(sum(r["a_numbers"] for r in ok) / max(1, len(ok)), 3),
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return {"rows": rows, "summary": summary}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["build", "offline", "real"])
    ap.add_argument("--pdf", default=str(ROOT / "tests" / "documents" / "*.pdf"))
    ap.add_argument("--set", "--out", dest="set", default=str(ROOT / "eval" / "photo_set"))
    ap.add_argument("--levels", default="mild,medium,hard")
    ap.add_argument("--reader", default="gemini", choices=["gemini", "claude"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    set_dir, levels = Path(a.set), a.levels.split(",")
    if a.mode == "build":
        build(sorted(glob.glob(a.pdf)), set_dir, tuple(levels))
        return
    res = offline(set_dir, levels) if a.mode == "offline" else real(set_dir, levels, a.reader, a.limit)
    out = set_dir / f"results_{a.mode}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", out)


if __name__ == "__main__":
    main()
