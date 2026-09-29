import argparse
import json
from pathlib import Path

from . import Builder, Options, convert, load_pages


def parse_pages(spec: str | None):
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    return out


def main():
    ap = argparse.ArgumentParser(prog="math2word",
                                 description="Convert a Hebrew math exam (PDF or image) into an editable Word file.")
    ap.add_argument("input", help="PDF or image file")
    ap.add_argument("-o", "--output", help="output .docx (default: <input>.docx)")
    ap.add_argument("-p", "--pages", help="page selection, e.g. 4-7,10")
    ap.add_argument("--from-json", help="skip transcription: build from a saved pages JSON file")
    ap.add_argument("--save-json", help="also save the transcription JSON here")
    ap.add_argument("--all-pages", action="store_true", help="keep cover / answer-space pages too")
    ap.add_argument("--no-page-breaks", action="store_true", help="flow pages continuously")
    ap.add_argument("--font", default="David", help="Hebrew font (default David)")
    ap.add_argument("--size", type=float, default=11, help="font size in pt")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cache", default=".math2word_cache", help="cache dir for page transcriptions")
    args = ap.parse_args()

    out = args.output or str(Path(args.input).with_suffix(".docx"))
    opts = Options(font_hebrew=args.font, size_pt=args.size, page_breaks=not args.no_page_breaks)
    pages = parse_pages(args.pages)

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        page_objs = load_pages(args.input, pages=pages or data.get("pages"))
        Builder(opts).build(data["page_json"], page_objs, out)
        print(f"saved {out}")
        return

    pages_json = convert(args.input, out, pages=pages, cache_dir=args.cache, all_pages=args.all_pages,
                         options=opts, effort=args.effort)
    if args.save_json:
        Path(args.save_json).write_text(json.dumps({"pages": pages, "page_json": pages_json},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
