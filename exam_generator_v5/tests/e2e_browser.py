"""Browser end-to-end test (Chromium via Playwright) of the whole app with Gemini mocked.

    python tests/make_fixtures.py
    E2E_STATE_FILE=/tmp/e2e_state.json streamlit run tests/run_mock_app.py --server.port 8599 --server.headless true
    python tests/e2e_browser.py            # in a second terminal

Checks: upload, delete, erase (pixel check), auto-straighten, full-resolution crop, undo, analysis, editing,
Word/PDF/ZIP downloads.  Downloads and screenshots go to tests/e2e_output/.
"""
import json, os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
SHOT = str(HERE / "e2e_output"); OUT = str(HERE / "e2e_output" / "downloads"); os.makedirs(OUT, exist_ok=True)
URL = os.environ.get("APP_URL", "http://localhost:8599")
STATE = os.environ.get("E2E_STATE_FILE", "/tmp/e2e_state.json")
def state(): return json.load(open(STATE))
def idle(page, t=90000):
    page.wait_for_timeout(700)
    page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=t)
    page.wait_for_timeout(700)
def comp_frame(page, name):
    for _ in range(40):
        for f in page.frames:
            if name in f.url: return f
        page.wait_for_timeout(500)
    raise RuntimeError(f"component frame {name} not found")
def wait_state(page, cond, timeout=40):
    for _ in range(timeout * 2):
        try:
            st_ = state()
            if cond(st_): return st_
        except Exception: pass
        page.wait_for_timeout(500)
    page.screenshot(path=f"{SHOT}/failure.png", full_page=True)
    raise RuntimeError(f"state condition not reached; state={state()}; alerts={page.locator('[data-testid=stAlert]').all_inner_texts()[:3]}")
def canvas_el(page):
    """drawable-canvas >= 0.13 renders in the page (components v2); older versions render inside an iframe."""
    for _ in range(40):
        loc = page.locator("canvas.upper-canvas")
        if loc.count():
            return loc.last
        for f in page.frames:
            if "drawable_canvas" in f.url and f.locator("canvas.upper-canvas").count():
                return f.locator("canvas.upper-canvas").last
        page.wait_for_timeout(500)
    raise RuntimeError("erase canvas not found")
def successes(page): return page.locator('[data-testid="stAlertContentSuccess"]').all_inner_texts()
def errors(page): return page.locator('[data-testid="stAlertContentError"]').all_inner_texts()
step = sys.argv[1] if len(sys.argv) > 1 else "all"
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1400, "height": 1100}, accept_downloads=True); page = ctx.new_page()
    page.goto(URL); page.get_by_text("שלב 1: הגדרת הבחינה").wait_for(timeout=60000); idle(page)
    page.get_by_label("שם בית הספר").fill("מקיף י' אשדוד"); page.keyboard.press("Tab")
    page.get_by_label("שם המורה / רכז המקצוע").fill("רונית כהן"); page.keyboard.press("Tab")
    n = page.get_by_label("מספר שאלות בטופס"); n.fill("2"); n.press("Enter"); idle(page)
    page.locator('input[type="file"]').first.set_input_files(str(FIX / "logo.png")); idle(page)
    page.get_by_role("button", name="המשך להעלאת שאלות").click(); page.get_by_text("שלב 2: העלאת שאלות").wait_for(); idle(page)
    page.locator('input[type="file"]').first.set_input_files(str(FIX / "q1_photo.jpg")); wait_state(page, lambda s: len(s["images"].get("1", [])) == 1); idle(page)
    # switch to question 2 (the editor tools must work there too — V5.0 showed a blank frame)
    page.get_by_role("radiogroup").get_by_text("שאלה 2", exact=True).click(); idle(page)
    page.locator('input[type="file"]').first.set_input_files(str(FIX / "q2_photo.jpg")); wait_state(page, lambda s: len(s["images"].get("2", [])) == 1); idle(page)
    s = state()["images"]; print("1) uploaded:", {k: [r["size"] for r in v] for k, v in s.items()})

    # ---- Q2: CROP tool must be visible ----
    page.get_by_text("✂️ חיתוך").first.click(); idle(page)
    cf = comp_frame(page, "streamlit_cropper"); page.wait_for_timeout(1500)
    h = cf.frame_element().bounding_box()["height"]
    assert h > 300, f"cropper frame of question 2 is blank (height {h})"
    page.get_by_role("button", name="💾 שמור חיתוך").click(); wait_state(page, lambda s: s["images"]["2"][0]["edited"]); idle(page)
    print("2) Q2 crop: frame height", round(h), "| size after crop:", state()["images"]["2"][0]["size"])
    page.screenshot(path=f"{SHOT}/q2_crop.png")
    cropped2 = state()["images"]["2"][0]

    # ---- Q2: ERASE after CROP (canvas must be visible and work on the cropped image) ----
    page.get_by_text("🧽 מחיקת סימנים").first.click(); idle(page)
    canvas = canvas_el(page); canvas.scroll_into_view_if_needed(); page.wait_for_timeout(800)
    h = canvas.bounding_box()["height"]
    assert h > 300, f"erase canvas of question 2 is blank (height {h})"
    bb = canvas.bounding_box()
    page.mouse.move(bb["x"] + 40, bb["y"] + 40); page.mouse.down(); page.mouse.move(bb["x"] + 90, bb["y"] + 80, steps=6); page.mouse.up()
    idle(page)
    page.get_by_role("button", name="💾 שמור מחיקה").click()
    after2 = wait_state(page, lambda s: s["images"]["2"][0]["digest"] != cropped2["digest"])["images"]["2"][0]; idle(page)
    assert after2["size"] == cropped2["size"] and after2["history"] == cropped2["history"] + 1
    print("3) Q2 crop->erase OK | size kept", after2["size"], "| history", after2["history"])

    # ---- back to Q1: ERASE with pixel check ----
    page.get_by_role("radiogroup").get_by_text("שאלה 1", exact=True).click(); idle(page)
    page.get_by_text("🧽 מחיקת סימנים").first.click(); idle(page)
    canvas = canvas_el(page); canvas.scroll_into_view_if_needed(); page.wait_for_timeout(800)
    bb = canvas.bounding_box()
    page.mouse.move(bb["x"] + 110, bb["y"] + 358); page.mouse.down()
    page.mouse.move(bb["x"] + 135, bb["y"] + 380, steps=5); page.mouse.move(bb["x"] + 162, bb["y"] + 407, steps=5); page.mouse.up()
    idle(page)
    page.get_by_role("button", name="💾 שמור מחיקה").click()
    r = wait_state(page, lambda s: s["images"]["1"][0]["edited"])["images"]["1"][0]; idle(page)
    assert r["blot_mean"] > 250 and r["pixels_changed_pct"] < 1.0, "erase check failed"
    print("4) Q1 erase: blot", round(r["blot_mean_orig"]), "->", round(r["blot_mean"]), "| changed %:", round(r["pixels_changed_pct"], 3))

    # ---- Q1: AUTO STRAIGHTEN + CROP + UNDO ----
    page.get_by_text("🔄 סיבוב ויישור").first.click(); idle(page)
    page.get_by_role("button", name="📐 יישור אוטומטי").first.click(); wait_state(page, lambda s: s["images"]["1"][0]["size"] != [1850, 2314]); idle(page)
    size = state()["images"]["1"][0]["size"]
    caption = page.locator('[data-testid="stImageCaption"]').first.inner_text()
    assert f"{size[0]}×{size[1]}" in caption, f"gallery not refreshed after straighten: {caption} vs {size}"
    assert page.get_by_role("button", name="↩️ בטל").first.is_enabled(), "undo button stale after straighten"
    print("5) straighten:", successes(page)[:1], "| size:", size, "| gallery refreshed:", caption)
    page.get_by_text("✂️ חיתוך").first.click(); idle(page)
    comp_frame(page, "streamlit_cropper"); page.wait_for_timeout(1500)
    before = state()["images"]["1"][0]["size"]
    page.get_by_role("button", name="💾 שמור חיתוך").click(); wait_state(page, lambda s: s["images"]["1"][0]["size"] != before); idle(page)
    cropped = state()["images"]["1"][0]["size"]
    print("6) crop full-res size:", cropped)
    page.get_by_role("button", name="↩️ בטל").first.click(); wait_state(page, lambda s: s["images"]["1"][0]["size"] != cropped); idle(page)
    print("7) undo -> size:", state()["images"]["1"][0]["size"])
    # erase -> ... -> crop sequence on Q1 ended with undo; crop again so the final image is erase+straighten+crop
    page.get_by_role("button", name="💾 שמור חיתוך").click(); wait_state(page, lambda s: s["images"]["1"][0]["size"] != [2008, 2438]); idle(page)
    final = {k: [r["digest"] for r in v] for k, v in state()["images"].items()}

    # ---- ANALYSIS ----
    page.get_by_role("button", name="אישור ומעבר לפענוח").click(); page.get_by_text("שלב 3: פענוח").wait_for(); idle(page)
    box = page.get_by_role("textbox", name="Gemini API Key"); box.fill("test-key"); box.press("Enter"); idle(page)
    page.get_by_role("button", name="🚀 התחל פענוח").click()
    t0 = time.time(); waits = set()
    while not page.get_by_text("שלב 4: בקרת איכות").count():
        for txt in page.locator('[data-testid="stProgress"]').all_inner_texts():
            if "ממתין" in txt: waits.add(txt.strip()[:40])
        if time.time() - t0 > 240: raise RuntimeError("analysis did not finish")
        page.wait_for_timeout(1000)
    idle(page)
    print(f"8) analysis finished in {time.time() - t0:.0f}s | waiting messages shown: {sorted(waits)[:2]}")
    sent = state()["sent_for_analysis"]
    assert sent == final, f"image sent for analysis is not the edited one: {sent} vs {final}"
    print("   edited images were sent for analysis:", sent == final)
    # ---- diagram review: approve the reconstruction of question 1 in the browser ----
    assert set(state()["diagrams"].values()) == {"pending"}
    page.get_by_role("button", name="✅ אשר שחזור").first.scroll_into_view_if_needed()
    page.screenshot(path=f"{SHOT}/review_q1.png", full_page=True)
    page.get_by_role("button", name="✅ אשר שחזור").first.click()
    wait_state(page, lambda s: "approved" in s["diagrams"].values()); idle(page)
    print("   diagram statuses after approve:", state()["diagrams"])
    # ---- EXAM_QUALITY: question 2 -> explicit, audited raster override (checkbox + button) ----
    page.get_by_text("שאלה 2", exact=True).first.click(); idle(page)
    btn = page.get_by_role("button", name="📷 השתמש בסריקה (חריג)").first
    btn.scroll_into_view_if_needed()
    assert btn.is_disabled(), "raster override must require the explicit confirmation"
    page.get_by_text("אני מאשר/ת שימוש חריג בסריקה").first.click(); idle(page)
    page.get_by_role("button", name="📷 השתמש בסריקה (חריג)").first.click()
    wait_state(page, lambda s: "raster_override" in s["diagrams"].values()); idle(page)
    print("   diagram statuses after raster override:", state()["diagrams"])
    # ---- constraint-aware DRAG in the real browser (custom SVG component inside an iframe) ----
    page.get_by_role("button", name="✏️ ערוך שחזור").first.click(); idle(page)
    frame_el = None
    for _ in range(60):
        frame_el = next((f for f in page.frames if "geo_drag" in (f.url or "")), None)
        if frame_el and frame_el.locator("#pt-A").count():
            break
        page.wait_for_timeout(500)
    assert frame_el is not None, "drag component did not load"
    before = state()["diagram_details"]["q2f1"]
    pt = frame_el.locator("#pt-A")
    pt.scroll_into_view_if_needed()
    bb = pt.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.mouse.down()
    page.mouse.move(bb["x"] + 60, bb["y"] + 45, steps=8)
    page.mouse.up()
    after = wait_state(page, lambda s: s["diagram_details"]["q2f1"]["edits"] > before["edits"], timeout=60)["diagram_details"]["q2f1"]
    idle(page)
    moved = after["points"]["A"] != before["points"]["A"]
    assert moved, "point A did not move"
    assert abs(after["right_angle_B_dot"]) < 1e-6, "drag broke the right angle constraint"
    assert state()["diagrams"]["q2f1"] != "raster_override" and state()["diagrams"]["q2f1"] != "approved"   # decision invalidated
    print("   drag: A", before["points"]["A"], "->", after["points"]["A"], "| right angle kept, dot =", round(after["right_angle_B_dot"], 9),
          "| status:", state()["diagrams"]["q2f1"])
    page.get_by_role("button", name="✅ אשר שחזור").first.click()
    wait_state(page, lambda s: s["diagrams"]["q2f1"] == "approved"); idle(page)
    # ---- LaTeX formula edit on question 1 (equivalent factorised form) ----
    page.get_by_text("שאלה 1", exact=True).first.click(); idle(page)
    page.get_by_role("button", name="✏️ ערוך שחזור").first.click(); idle(page)
    box = page.get_by_label("נוסחה").first
    box.fill("(x-2)(x+2)"); box.press("Enter"); idle(page)
    page.get_by_role("button", name="💾 החל נוסחה ובדוק מחדש").first.click()
    d1 = wait_state(page, lambda s: s["diagram_details"]["q1f1"]["edits"] >= 1)["diagram_details"]["q1f1"]; idle(page)
    assert d1["expression"] == "(x-2)(x+2)" and state()["diagrams"]["q1f1"] != "approved"
    page.get_by_role("button", name="✅ אשר שחזור").first.click()
    wait_state(page, lambda s: s["diagrams"]["q1f1"] == "approved"); idle(page)
    print("   latex edit -> re-approved:", state()["diagrams"])
    print("   step4:", successes(page)[:2], errors(page)[:2])
    page.screenshot(path=f"{SHOT}/e_step4.png", full_page=True)

    # ---- DOCUMENTS ----
    page.get_by_role("button", name="אישור והפקת קבצים").click(); page.get_by_text("שלב 5: הפקת הקבצים").wait_for(); idle(page)
    page.get_by_role("button", name="🖨️ הפק PDF").click(); page.get_by_role("button", name="⬇️ מבחן (PDF)").wait_for(timeout=120000); idle(page)
    for label in ["⬇️ מבחן (Word)", "⬇️ פתרונות (Word)", "⬇️ מחוון (Word)", "⬇️ מבחן (PDF)", "⬇️ פתרונות (PDF)", "⬇️ מחוון (PDF)", "📦 הורד הכל (ZIP)"]:
        with page.expect_download() as d:
            page.get_by_role("button", name=label).click()
        dl = d.value; path = f"{OUT}/{dl.suggested_filename}"; dl.save_as(path); print("9) downloaded:", dl.suggested_filename, os.path.getsize(path))
    page.screenshot(path=f"{SHOT}/e_step5.png", full_page=True)
    b.close()
print("E2E PASSED")
