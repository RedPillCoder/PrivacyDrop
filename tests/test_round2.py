"""Tests for round 2 improvements: reclean_all, auto-save, Office thumbnails.

GUI tests use a Tk root (works on Linux under Xvfb).
Engine tests are platform-independent.
"""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


# ---------------------------------------------------------------------------
# Helper: build a minimal Tk + app instance
# ---------------------------------------------------------------------------
def _make_app():
    import tkinter as tk
    from app import PrivacyDropApp, HAS_DND

    if HAS_DND:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = PrivacyDropApp(root)
    return root, app


def _add_item(root, app, name, status="ok", out="", details="exif"):
    item = {"path": name, "status": status, "details": details, "out": out,
            "iid": None, "_counted": status in ("ok", "clean", "skipped", "error")}
    label = {
        "ok": "\u2713  Cleaned",
        "clean": "\u2713  Clean (already)",
        "skipped": "\u2013  Skipped",
        "error": "\u2717  Failed",
        "pending": "queued\u2026",
        "working": "working\u2026",
    }.get(status, status)
    item["iid"] = app.tree.insert("", "end",
                                  values=(name, "1.0 KB", label, details),
                                  tags=({"ok": "ok", "clean": "clean",
                                         "skipped": "skip", "error": "err"}.get(status, "")))
    app.items.append(item)
    return item


# ---------------------------------------------------------------------------
# reclean_all tests
# ---------------------------------------------------------------------------

def test_reclean_resets_finished_items():
    """reclean_all resets ok/clean/skipped/error to working (via process_all).

    Note: reclean_all resets to pending then calls process_all(), which
    immediately transitions pending items to working and queues them.
    """
    root, app = _make_app()
    try:
        working_before = _add_item(root, app, "b.jpg", status="working")
        ok_item = _add_item(root, app, "c.jpg", status="ok", out="/tmp/c.jpg")
        err_item = _add_item(root, app, "d.jpg", status="error")

        app.reclean_all()

        # process_all() turns pending -> working, so ok/error become working
        check("working stays working", working_before["status"] == "working")
        check("ok -> working (re-queued)", ok_item["status"] == "working")
        check("error -> working (re-queued)", err_item["status"] == "working")
        check("ok details cleared", ok_item["details"] == "")
        check("ok out cleared", ok_item["out"] == "")
        check("ok _counted reset", ok_item["_counted"] == False)
    finally:
        root.destroy()


def test_reclean_resets_progress():
    """reclean_all resets progress bar; job_total reflects re-queued count."""
    root, app = _make_app()
    try:
        app.progress.configure(maximum=5, value=3)
        _add_item(root, app, "c.jpg", status="ok", out="/tmp/c.jpg")
        _add_item(root, app, "d.jpg", status="clean", out="/tmp/d.jpg")

        app.reclean_all()
        check("progress reset to 0", app.progress["value"] == 0)
        # job_total should equal number of items re-queued (2 in this case)
        check("job_total reflects re-queued items",
              app._job_total == 2,
              f"got {app._job_total}")
    finally:
        root.destroy()


def test_reclean_nothing_if_all_pending():
    """reclean_all with only pending items does nothing harmful."""
    root, app = _make_app()
    try:
        _add_item(root, app, "a.jpg", status="pending")
        _add_item(root, app, "b.jpg", status="pending")

        app.reclean_all()
        # reclean_all only resets finished items; pending items stay pending
        check("pending items unchanged",
              all(i["status"] == "pending" for i in app.items))
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Auto-save tests
# ---------------------------------------------------------------------------

def test_auto_save_on_toggle():
    """Toggling an option saves config immediately."""
    root, app = _make_app()
    try:
        import config as configmod
        saved = {"called": 0}
        orig_save = configmod.save

        def _spy(settings):
            saved["called"] += 1
            saved["settings"] = settings
        configmod.save = _spy

        try:
            # Toggle strip_icc
            app.strip_icc.set(True)
            # Let Tk process the trace
            root.update_idletasks()
            check("auto-save called on toggle", saved["called"] >= 1)
            if saved["called"] >= 1:
                check("strip_icc saved as True",
                      saved["settings"].get("strip_icc") == True)
        finally:
            configmod.save = orig_save
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Office thumbnail scrub tests
# ---------------------------------------------------------------------------

def test_thumbnail_at_word_root_scrubbed():
    """JPEG thumbnails at word/thumbnail.jpeg should have EXIF stripped."""
    from scrubber import sanitize_office, Options, _read_zip_safely

    with tempfile.TemporaryDirectory() as td:
        # Create a minimal docx with a thumbnail at word/thumbnail.jpeg
        src = os.path.join(td, "doc.docx")
        with zipfile.ZipFile(src, "w") as z:
            # Minimal docx structure
            z.writestr("[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="jpeg" ContentType="image/jpeg"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
            z.writestr("_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>')
            z.writestr("word/_rels/document.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr("word/document.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>')

            # Add a JPEG thumbnail at word/thumbnail.jpeg with EXIF
            from PIL import Image
            import io
            img = Image.new("RGB", (10, 10), color="red")
            buf = io.BytesIO()
            img.save(buf, "JPEG", exif=b"Exif\x00\x00" + b"\x00" * 20)
            z.writestr("word/thumbnail.jpeg", buf.getvalue())

        dst = os.path.join(td, "doc_clean.docx")
        opts = Options()
        rep = sanitize_office(src, dst, opts)

        check("thumbnail scrubbed", rep.ok)
        # Verify the thumbnail in the output has no EXIF
        with zipfile.ZipFile(dst, "r") as z:
            thumb_data = z.read("word/thumbnail.jpeg")
            check("no Exif header in output thumbnail",
                  b"Exif\x00\x00" not in thumb_data,
                  "Exif header still present")


# ---------------------------------------------------------------------------
# Ctrl+R shortcut test
# ---------------------------------------------------------------------------

def test_ctrl_r_shortcut_bound():
    """Ctrl+R should trigger reclean_all."""
    root, app = _make_app()
    try:
        # Check that the binding exists
        bindings = root.bind("<Control-r>")
        check("Ctrl+R bound", bindings != "")

        # Check Ctrl+R also bound
        bindings2 = root.bind("<Control-R>")
        check("Ctrl+R (uppercase) bound", bindings2 != "")
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_reclean_resets_finished_items()
    test_reclean_resets_progress()
    test_reclean_nothing_if_all_pending()
    test_auto_save_on_toggle()
    test_thumbnail_at_word_root_scrubbed()
    test_ctrl_r_shortcut_bound()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
