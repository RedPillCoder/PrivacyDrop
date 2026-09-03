"""Tests for round 3 improvements: PDF form field clearing, bytes-saved
tracking, file-size column, and Clear List confirmation.
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
# PDF form field value clearing
# ---------------------------------------------------------------------------

def test_pdf_form_fields_cleared():
    """PDF AcroForm text field values (/V and /DV) are cleared."""
    from pikepdf import Pdf, Name, Array, Dictionary, String
    from scrubber import sanitize_file, Options

    pdf = Pdf.new()
    pdf.add_blank_page(page_size=(100, 100))
    pdf.Root[Name('/AcroForm')] = Dictionary(Fields=Array([
        Dictionary(Type=Name('/Annot'), Subtype=Name('/Widget'),
                   FT=Name('/Tx'), T='FullName',
                   V='John Smith', DV='John Smith'),
        Dictionary(Type=Name('/Annot'), Subtype=Name('/Widget'),
                   FT=Name('/Tx'), T='Email',
                   V='john@example.com'),
    ]))

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'form.pdf')
        dst = os.path.join(td, 'form_clean.pdf')
        pdf.save(src)

        rep = sanitize_file(src, dst, Options())

        check("form PDF cleaned", rep.ok)
        check("form values reported as removed",
              any("form field" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        with Pdf.open(dst) as p:
            af = p.Root.get(Name('/AcroForm'))
            if af:
                has_any_value = False
                for field in af.get(Name('/Fields'), []):
                    if Name('/V') in field or Name('/DV') in field:
                        has_any_value = True
                check("no field values remain", not has_any_value)
            else:
                check("AcroForm gone entirely", True)


def test_pdf_form_fields_preserve_structure():
    """Form field labels (/T) and structure are preserved; only values cleared."""
    from pikepdf import Pdf, Name, Array, Dictionary, String
    from scrubber import sanitize_file, Options

    pdf = Pdf.new()
    pdf.add_blank_page(page_size=(100, 100))
    pdf.Root[Name('/AcroForm')] = Dictionary(Fields=Array([
        Dictionary(Type=Name('/Annot'), Subtype=Name('/Widget'),
                   FT=Name('/Tx'), T='FullName',
                   V='Secret Name'),
    ]))

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'form.pdf')
        dst = os.path.join(td, 'form_clean.pdf')
        pdf.save(src)

        sanitize_file(src, dst, Options())

        with Pdf.open(dst) as p:
            af = p.Root.get(Name('/AcroForm'))
            check("AcroForm still present", af is not None)
            if af and Name('/Fields') in af:
                field = af[Name('/Fields')][0]
                label = str(field.get(Name('/T'), ''))
                check("field label preserved", label == 'FullName')
                check("/V cleared", Name('/V') not in field)


# ---------------------------------------------------------------------------
# File-size column in results tree
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


def test_file_size_column_present():
    """Tree has a 'size' column."""
    root, app = _make_app()
    try:
        cols = app.tree["columns"]
        check("size column exists", "size" in cols, f"cols: {cols}")
    finally:
        root.destroy()


def test_add_path_shows_size():
    """Adding a file shows its size in the size column."""
    root, app = _make_app()
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            # Write > 1 KB so _fmt_bytes returns KB not B
            f.write(b'\xff\xd8\xff\xe0' + b'\x00' * 2000)
            src = f.name
        try:
            app.add_path(src)
            iid = app.items[-1]["iid"]
            values = app.tree.item(iid, "values")
            size_str = values[1]
            check("size column shows value", size_str != "\u2014" and size_str != "",
                  f"got: {size_str!r}")
            check("size shows KB for >1KB file",
                  "KB" in size_str,
                  f"got: {size_str!r}")
        finally:
            os.unlink(src)
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Bytes-saved tracking
# ---------------------------------------------------------------------------

def test_bytes_saved_initialized_zero():
    """Bytes saved starts at zero."""
    root, app = _make_app()
    try:
        check("initial bytes saved == 0", app._bytes_saved == 0)
    finally:
        root.destroy()


def test_bytes_saved_reset_on_clear():
    """Clear List resets bytes saved to zero."""
    root, app = _make_app()
    try:
        app._bytes_saved = 5000
        # Mock out the messagebox so the confirmation auto-confirms
        from tkinter import messagebox
        orig = messagebox.askyesno
        messagebox.askyesno = lambda *a, **kw: True
        try:
            app.clear_list()
            check("bytes saved reset after clear", app._bytes_saved == 0)
        finally:
            messagebox.askyesno = orig
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Clear List confirmation dialog
# ---------------------------------------------------------------------------

def test_clear_list_asks_confirmation():
    """Clear List shows a confirmation dialog when items exist."""
    root, app = _make_app()
    try:
        from tkinter import messagebox
        calls = []
        orig = messagebox.askyesno
        messagebox.askyesno = lambda *a, **kw: calls.append((a, kw)) or False
        try:
            # Add an item so clear_list has something to ask about
            app.add_path.__wrapped__ if hasattr(app.add_path, '__wrapped__') else None
            # Create a dummy item directly
            item = {"path": "/tmp/test.jpg", "status": "ok", "details": "exif",
                    "out": "/tmp/test_clean.jpg", "iid": None, "_counted": True}
            item["iid"] = app.tree.insert("", "end",
                                          values=("test.jpg", "1.0 KB",
                                                  "\u2713  Cleaned", "exif"),
                                          tags=("ok",))
            app.items.append(item)

            app.clear_list()
            check("confirmation dialog shown", len(calls) == 1,
                  f"calls: {len(calls)}")
            # User said No, so item should still be there
            check("item preserved when user says No", len(app.items) == 1)
        finally:
            messagebox.askyesno = orig
    finally:
        root.destroy()


def test_clear_list_no_confirmation_when_empty():
    """Clear List does NOT show dialog when list is empty."""
    root, app = _make_app()
    try:
        from tkinter import messagebox
        calls = []
        orig = messagebox.askyesno
        messagebox.askyesno = lambda *a, **kw: calls.append(True) or True
        try:
            app.clear_list()
            check("no dialog when empty", len(calls) == 0,
                  f"calls: {len(calls)}")
        finally:
            messagebox.askyesno = orig
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_pdf_form_fields_cleared()
    test_pdf_form_fields_preserve_structure()
    test_file_size_column_present()
    test_add_path_shows_size()
    test_bytes_saved_initialized_zero()
    test_bytes_saved_reset_on_clear()
    test_clear_list_asks_confirmation()
    test_clear_list_no_confirmation_when_empty()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
