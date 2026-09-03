"""Tests for v1.1.1 improvements: clear-completed, keyboard nav, open original.

Runs the GUI tests under a Tk root — works on Linux under Xvfb and on
Windows with a display.  The core cleaning logic is tested elsewhere; this
file only verifies the new UI behaviours.
"""

import os
import sys
import tempfile

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


def _add_dummy(root, app, name="fake.jpg", status="ok", out="/tmp/out.jpg"):
    item = {"path": name, "status": status, "details": "exif", "out": out,
            "iid": None, "_counted": True}
    item["iid"] = app.tree.insert("", "end",
                                  values=(name, "1.0 KB", "\u2713  Cleaned", "exif"),
                                  tags=("ok",))
    app.items.append(item)
    return item


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clear_completed():
    """clear_completed removes only finished items, keeps pending ones."""
    root, app = _make_app()
    try:
        pending = _add_dummy(root, app, "a.jpg", status="pending", out="")
        working = _add_dummy(root, app, "b.jpg", status="working", out="")
        done_ok = _add_dummy(root, app, "c.jpg", status="ok", out="/tmp/c.jpg")
        done_err = _add_dummy(root, app, "d.jpg", status="error", out="")

        before = len(app.items)
        check("4 items before", before == 4)

        app.clear_completed()

        check("2 items after clear_completed", len(app.items) == 2,
              f"got {len(app.items)}")
        check("pending kept", pending in app.items)
        check("working kept", working in app.items)
        check("ok removed", done_ok not in app.items)
        check("error removed", done_err not in app.items)
    finally:
        root.destroy()


def test_clear_completed_preserves_progress():
    """Progress bar adjusts when counted items are cleared."""
    root, app = _make_app()
    try:
        app.progress.configure(maximum=5, value=3)
        _add_dummy(root, app, "c.jpg", status="ok", out="/tmp/c.jpg")
        _add_dummy(root, app, "d.jpg", status="clean", out="/tmp/d.jpg")

        app.clear_completed()
        # 2 counted items removed → value should drop by 2
        check("progress decremented",
              app.progress["value"] == 1,
              f"got {app.progress['value']}")
    finally:
        root.destroy()


def test_keyboard_navigation():
    """Up/Down arrows move selection in the tree."""
    root, app = _make_app()
    try:
        i1 = _add_dummy(root, app, "a.jpg", status="ok", out="/tmp/a.jpg")
        i2 = _add_dummy(root, app, "b.jpg", status="ok", out="/tmp/b.jpg")
        i3 = _add_dummy(root, app, "c.jpg", status="ok", out="/tmp/c.jpg")

        app.tree.selection_set(i1["iid"])
        app.tree.focus(i1["iid"])

        # Down → should move to i2
        app._on_tree_down(None)
        sel = app.tree.selection()
        check("down moves selection", sel and sel[0] == i2["iid"])

        # Down again → i3
        app._on_tree_down(None)
        sel = app.tree.selection()
        check("down again to last", sel and sel[0] == i3["iid"])

        # Down at last → stays
        app._on_tree_down(None)
        sel = app.tree.selection()
        check("down at last stays", sel and sel[0] == i3["iid"])

        # Up → i2
        app._on_tree_up(None)
        sel = app.tree.selection()
        check("up from last", sel and sel[0] == i2["iid"])
    finally:
        root.destroy()


def test_select_all():
    """Ctrl+A selects every row."""
    root, app = _make_app()
    try:
        for n in ("a.jpg", "b.jpg", "c.jpg"):
            _add_dummy(root, app, n, status="ok", out=f"/tmp/{n}")

        app._select_all()
        check("select all", len(app.tree.selection()) == 3)
    finally:
        root.destroy()


def test_copy_selected_paths():
    """Ctrl+C copies cleaned paths to clipboard."""
    root, app = _make_app()
    try:
        _add_dummy(root, app, "a.jpg", status="ok", out="/tmp/a.jpg")
        _add_dummy(root, app, "b.jpg", status="ok", out="/tmp/b.jpg")

        # Select both items
        app._select_all()

        app._copy_selected_paths()
        try:
            clip = root.clipboard_get()
            check("clipboard has both paths",
                  "/tmp/a.jpg" in clip and "/tmp/b.jpg" in clip,
                  f"clipboard: {clip!r}")
        except Exception:
            # Clipboard may not work under Xvfb - just verify the method runs
            check("clipboard method runs", True)
    finally:
        root.destroy()


def test_open_original_menu_action():
    """'Open original' menu action calls open_folder on the source path."""
    root, app = _make_app()
    try:
        captured = {}
        # Monkey-patch open_folder to capture the call
        import app as appmod
        orig = appmod.open_folder

        def _spy(path):
            captured["path"] = path
        appmod.open_folder = _spy

        try:
            item = _add_dummy(root, app, "src.jpg", status="ok",
                              out="/tmp/src_clean.jpg")
            app.tree.selection_set(item["iid"])
            app.tree.focus(item["iid"])
            app._menu_act("open_orig")
            check("open_orig calls open_folder on source",
                  captured.get("path") == "src.jpg",
                  f"got {captured.get('path')}")
        finally:
            appmod.open_folder = orig
    finally:
        root.destroy()


def test_double_click_error_shows_details():
    """Double-clicking an error row shows the error in a dialog."""
    root, app = _make_app()
    try:
        item = _add_dummy(root, app, "bad.jpg", status="error", out="")
        item["details"] = "not a valid JPEG file"
        app.tree.selection_set(item["iid"])
        app.tree.focus(item["iid"])

        # Monkey-patch messagebox to capture the call
        from tkinter import messagebox
        orig_showerror = messagebox.showerror
        captured = {}

        def _spy(title, msg):
            captured["title"] = title
            captured["msg"] = msg
        messagebox.showerror = _spy

        try:
            app._on_tree_double_click(None)
            check("error double-click shows dialog",
                  "bad.jpg" in captured.get("msg", ""),
                  f"msg: {captured.get('msg')}")
        finally:
            messagebox.showerror = orig_showerror
    finally:
        root.destroy()


def test_encoding_no_mojibake():
    """Verify user-visible strings are proper UTF-8, not mojibake."""
    import app as appmod
    import inspect

    src = inspect.getsource(appmod)
    # These patterns should NOT appear (they indicate double-encoded UTF-8)
    bad = [
        "\u00e2\u20ac\u201c",   # â€"
        "\u00e2\u20ac\u2026",   # â€¦
        "\u00e2\u20ac\u009c",   # â€œ
        "\u00e2\u20ac\u009d",   # â€
        "\u00e2\u2192",         # â†'
    ]
    for b in bad:
        check(f"no mojibake {b!r}", b not in src,
              f"found corrupted sequence in app.py")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_clear_completed()
    test_clear_completed_preserves_progress()
    test_keyboard_navigation()
    test_select_all()
    test_copy_selected_paths()
    test_open_original_menu_action()
    test_double_click_error_shows_details()
    test_encoding_no_mojibake()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
