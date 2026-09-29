"""Create realistic synthetic exam photos (Hebrew text + formula + parabola drawing)."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import exam_core as c
from pathlib import Path
OUT = Path(__file__).resolve().parent / "fixtures"
OUT.mkdir(exist_ok=True)
F = c._font_path()
def page(lines, with_graph=True, size=(1700, 2200)):
    img = Image.new("RGB", size, "white"); d = ImageDraw.Draw(img)
    font = ImageFont.truetype(F, 46); small = ImageFont.truetype(F, 40)
    y = 120
    for ln in lines:
        d.text((size[0]-120, y), ln, font=font, fill=(20,20,20), anchor="ra"); y += 90
    if with_graph:
        ox, oy, s = 850, 1500, 60
        d.line([(ox-420, oy), (ox+420, oy)], fill="black", width=4); d.line([(ox, oy-500), (ox, oy+250)], fill="black", width=4)
        pts = [(ox + x*s, oy - (x*x - 4)*s/1.5) for x in np.linspace(-3.2, 3.2, 200)]
        d.line(pts, fill="black", width=5)
        d.text((ox+430, oy+10), "x", font=small, fill="black"); d.text((ox+15, oy-520), "y", font=small, fill="black")
    return img
q1 = page(["שאלה 1", "נתונה הפונקציה f(x) = x² − 4", "א. מצא את נקודות החיתוך של הגרף עם הצירים.", "ב. מצא את נקודת הקיצון של הפונקציה.", "ג. שרטט סקיצה של גרף הפונקציה."])
# phone-photo look: rotate, shadow gradient, noise, a stray pen mark
def photo(img, angle):
    r = img.rotate(angle, expand=True, fillcolor=(235,235,230), resample=Image.Resampling.BICUBIC)
    arr = np.asarray(r).astype(float)
    grad = np.linspace(0.78, 1.0, arr.shape[1])[None, :, None]
    arr = np.clip(arr*grad + np.random.default_rng(1).normal(0, 6, arr.shape), 0, 255).astype(np.uint8)
    out = Image.fromarray(arr); d = ImageDraw.Draw(out)
    d.ellipse([300, 900, 360, 960], fill=(40, 40, 160))  # stray ink blot to erase
    return out.filter(ImageFilter.GaussianBlur(0.6))
photo(q1, 4.0).save(str(OUT / "q1_photo.jpg"), quality=90)
q2 = page(["שאלה 2", "במשולש ABC נתון: AB = 5, BC = 12, הזווית B ישרה.", "א. חשב את אורך הצלע AC.", "ב. חשב את שטח המשולש."], with_graph=False)
photo(q2, -2.5).save(str(OUT / "q2_photo.jpg"), quality=90)
logo = Image.new("RGB", (300, 300), "white"); ImageDraw.Draw(logo).ellipse([20,20,280,280], outline=(30,90,200), width=18); logo.save(str(OUT / "logo.png"))
print("ok")
