"""Minimal upload page: PDF/image in, Word file out.

    ANTHROPIC_API_KEY=... python web/app.py   ->  http://localhost:5000
"""
import sys
import tempfile
from pathlib import Path

from flask import Flask, abort, render_template_string, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from math2word import Options, convert  # noqa: E402
from math2word.__main__ import parse_pages  # noqa: E402

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

PAGE = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>המרת שאלות מתמטיקה ל־Word</title>
<style>
 body{font-family:Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;background:#f7f7f8;color:#222}
 form{background:#fff;padding:24px;border-radius:10px;box-shadow:0 1px 4px #0002}
 label{display:block;margin:14px 0 6px;font-weight:bold} input,select{font-size:16px;width:100%}
 button{margin-top:20px;font-size:17px;padding:10px 22px;border:0;border-radius:8px;background:#2458d6;color:#fff;cursor:pointer}
 small{color:#666}
</style></head><body>
<h1>PDF / תמונה ← Word</h1>
<form method="post" enctype="multipart/form-data" onsubmit="this.querySelector('button').textContent='ממיר… (כדקה לעמוד)'">
 <label>קובץ שאלון (PDF או תמונה)</label><input type="file" name="file" required accept=".pdf,image/*">
 <label>עמודים <small>(לא חובה, למשל 4-7,10)</small></label><input name="pages" dir="ltr">
 <label>גופן עברי</label><select name="font"><option>David</option><option>Arial</option><option>Times New Roman</option><option>Frank Ruehl</option></select>
 <label>גודל גופן</label><select name="size"><option>11</option><option>12</option><option>10</option></select>
 <label><input type="checkbox" name="flow" style="width:auto"> ללא מעבר עמוד בין עמודי המקור</label>
 <button>המר</button>
</form></body></html>"""


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template_string(PAGE)
    f = request.files.get("file")
    if not f or Path(f.filename).suffix.lower() not in ALLOWED:
        abort(400, "unsupported file type")
    tmp = Path(tempfile.mkdtemp(prefix="math2word-"))
    src = tmp / ("input" + Path(f.filename).suffix.lower())
    f.save(src)
    out = tmp / (Path(f.filename).stem + ".docx")
    opts = Options(font_hebrew=request.form.get("font", "David"), size_pt=float(request.form.get("size", 11)),
                   page_breaks=not request.form.get("flow"))
    convert(src, out, pages=parse_pages(request.form.get("pages") or None), options=opts)
    return send_file(out, as_attachment=True, download_name=out.name)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
