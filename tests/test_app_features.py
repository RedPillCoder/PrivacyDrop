"""Tests for the UX / convenience feature set:

  * persistent preferences (config module) — load/save/sanitize
  * JPEG alias extensions (.jfif / .jpe)
  * session report text generation
  * GUI: settings load, progress bar, drag-source data, context-menu
    actions, retry/remove, double-click, save-on-close, shortcuts

Run the GUI parts under Xvfb:
    xvfb-run -a python tests/test_app_features.py
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import app as appmod
import scrubber
from scrubber import sanitize_file, Options, default_output_path, supported

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_feat")
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def make_exif():
    exif = Image.Exif()
    exif[0x010F] = "Acme Corp"
    exif[0x0110] = "SecretCam 9000"
    exif[0x8825] = {1: "S",
                    2: (IFDRational(31, 1), IFDRational(57, 1), IFDRational(1, 1)),
                    3: "E",
                    4: (IFDRational(115, 1), IFDRational(51, 1), IFDRational(1, 1))}
    return exif


# ------------------------------------------------------------- config

def t_config():
    print("\n[Config persistence]")
    cfg = os.path.join(TMP, "cfg.json")
    os.environ["PRIVACYDROP_CONFIG"] = cfg
    if os.path.exists(cfg):
        os.unlink(cfg)

    # defaults when no file
    d = config.load()
    check("defaults returned", d == config.DEFAULTS, str(d))
    check("remove_scripts default secure", d["remove_scripts"] is True)

    # save / load round-trip
    config.save({"suffix": "_scrubbed", "subfolder": True,
                 "strip_icc": True, "keep_attachments": False,
                 "remove_scripts": False, "topmost": True})
    d = config.load()
    check("suffix persisted", d["suffix"] == "_scrubbed")
    check("subfolder persisted", d["subfolder"] is True)
    check("strip_icc persisted", d["strip_icc"] is True)
    check("remove_scripts persisted", d["remove_scripts"] is False)

    # hostile / malformed config files fall back safely
    open(cfg, "w").write('{"suffix": 123, "strip_icc": "yes", '
                         '"subfolder": {"nested": true}}')
    d = config.load()
    check("bad types coerced to defaults",
          d["suffix"] == config.DEFAULTS["suffix"]
          and d["strip_icc"] is False and d["subfolder"] is False, str(d))

    open(cfg, "w").write("NOT JSON AT ALL {{{")
    d = config.load()
    check("invalid JSON -> defaults", d == config.DEFAULTS)

    # suffix filename-safety
    config.save({"suffix": 'bad/name\\with:chars*?"<>|'})
    d = config.load()
    check("suffix sanitized", d["suffix"] == "badnamewithchars", d["suffix"])

    config.save({"suffix": ""})
    check("empty suffix -> default", config.load()["suffix"]
          == config.DEFAULTS["suffix"])

    # very long suffix capped
    config.save({"suffix": "x" * 500})
    check("long suffix rejected", config.load()["suffix"]
          == config.DEFAULTS["suffix"])

    # unknown keys ignored
    config.save({"evil": "injected", "suffix": "_s"})
    d = config.load()
    check("unknown keys dropped", "evil" not in d and d["suffix"] == "_s")

    os.environ.pop("PRIVACYDROP_CONFIG", None)


# ------------------------------------------------------------- aliases

def t_jpeg_aliases():
    print("\n[JPEG alias extensions: .jfif / .jpe]")
    for ext in (".jfif", ".jpe"):
        src = os.path.join(TMP, f"alias{ext}")
        Image.new("RGB", (48, 36), (90, 60, 30)).save(
            src, "JPEG", exif=make_exif().tobytes(), comment=b"hi")
        check(f"supported({ext})", supported(src) is True)
        check(f"dispatched as JPEG ({ext})", ext in scrubber.JPEG_EXTS)
        dst = default_output_path(src, os.path.join(TMP, "out"), "_clean")
        rep = sanitize_file(src, dst, Options())
        check(f"{ext} cleaned", rep.status == "ok", rep.summary())
        check(f"{ext} GPS reported", "GPS location" in rep.summary(),
              rep.summary())
        with Image.open(dst) as im:
            im.load()
            check(f"{ext} output valid & EXIF-free", im.size == (48, 36)
                  and not dict(im.getexif()))
        check(f"{ext} keeps extension", os.path.splitext(dst)[1] == ext)

    # garbage .jfif must error, not be copied
    bad = os.path.join(TMP, "bad.jfif")
    open(bad, "wb").write(b"nope")
    rep = sanitize_file(bad, default_output_path(bad, None, "_clean"),
                        Options())
    check("garbage .jfif -> error", rep.status == "error")


# ------------------------------------------------------------- report text

def t_report_text():
    print("\n[Report text generation]")
    items = [
        {"path": "/tmp/photo.jpg", "status": "ok",
         "details": "EXIF metadata, GPS location (31Â°57'S, 115Â°51'E)",
         "out": "/tmp/photo_clean.jpg"},
        {"path": "/tmp/plain.jpg", "status": "clean",
         "details": "no metadata found", "out": "/tmp/plain_clean.jpg"},
        {"path": "/tmp/note.txt", "status": "skipped",
         "details": "unsupported file type", "out": ""},
    ]
    txt = appmod.build_report_text(items, "9.9.9")
    check("header present", "PrivacyDrop v9.9.9" in txt)
    check("mentions GPS", "GPS location" in txt)
    check("mentions skipped", "skipped" in txt)
    check("originals note", "never modified" in txt)
    check("per-file listing", "photo.jpg" in txt and "note.txt" in txt)


# ------------------------------------------------------------- GUI

def t_gui_features():
    print("\n[GUI: new features]")
    cfg = os.path.join(TMP, "guicfg.json")
    os.environ["PRIVACYDROP_CONFIG"] = cfg
    if os.path.exists(cfg):
        os.unlink(cfg)
    config.save({"suffix": "_scrubbed", "strip_icc": True, "topmost": True})

    if appmod.HAS_DND:
        root = appmod.TkinterDnD.Tk()
    else:
        import tkinter as tk
        root = tk.Tk()
    a = appmod.PrivacyDropApp(root)

    # settings loaded
    check("suffix loaded from config", a.suffix.get() == "_scrubbed")
    check("strip_icc loaded", a.strip_icc.get() is True)
    check("topmost loaded", a.topmost.get() is True)
    check("remove_scripts secure default", a.remove_scripts.get() is True)

    # add files and process; track progress
    paths = []
    for i in range(3):
        p = os.path.join(TMP, f"f{i}.jpg")
        Image.new("RGB", (24, 24), (i, i, i)).save(p, "JPEG",
                                                   exif=make_exif().tobytes())
        paths.append(p)
        a.add_path(p)
    a.process_all()
    check("progress max == 3", a.progress["maximum"] == 3)

    state = {"done": False}

    def step():
        a._poll()
        pending = any(i["status"] in ("pending", "working") for i in a.items)
        if pending and not state["done"]:
            a.root.after(80, step)
        else:
            state["done"] = True
            state["progress"] = a.progress["value"]
            state["status"] = a.status_label.cget("text")
            state["banner"] = a.banner.cget("text")
            a.root.destroy()

    a.root.after(80, step)
    a.root.mainloop()

    check("progress reached max", state.get("progress") == 3,
          str(state.get("progress")))
    check("status label summary", "cleaned" in state.get("status", ""),
          state.get("status"))
    check("banner ok", "safe to share" in state.get("banner", ""))
    by_path = {i["path"]: i for i in a.items}
    check("custom suffix used", by_path[paths[0]]["out"].endswith("_scrubbed.jpg"))

    # drag-source data for a cleaned row
    if appmod.HAS_DND:
        root2 = appmod.TkinterDnD.Tk()
    else:
        import tkinter as _tk
        root2 = _tk.Tk()
    a2 = appmod.PrivacyDropApp(root2)
    p = os.path.join(TMP, "drag.jpg")
    Image.new("RGB", (20, 20), (1, 2, 3)).save(p, "JPEG",
                                               exif=make_exif().tobytes())
    a2.add_path(p)
    a2.process_all()

    def step2():
        a2._poll()
        if any(i["status"] in ("pending", "working") for i in a2.items):
            a2.root.after(80, step2)
        else:
            item = a2.items[0]
            a2.tree.selection_set(item["iid"])
            actions, dtype, data = a2._drag_init(None)
            check("drag actions COPY", actions in ("copy", 1, appmod.COPY),
                  str(actions))
            check("drag type DND_FILES", dtype == appmod.DND_FILES or
                  "Files" in str(dtype), str(dtype))
            check("drag data is cleaned path", data == item["out"],
                  f"{data!r} vs {item['out']!r}")
            # nothing selected -> empty drag data
            a2.tree.selection_remove(item["iid"])
            _a, _t, data2 = a2._drag_init(None)
            check("no selection -> empty drag", not data2)
            a2.root.destroy()

    a2.root.after(80, step2)
    a2.root.mainloop()

    # context menu / retry / remove behaviours
    if appmod.HAS_DND:
        root3 = appmod.TkinterDnD.Tk()
    else:
        import tkinter as _tk
        root3 = _tk.Tk()
    a3 = appmod.PrivacyDropApp(root3)
    p3 = os.path.join(TMP, "retry.jpg")
    Image.new("RGB", (20, 20), (9, 9, 9)).save(p3, "JPEG",
                                               exif=make_exif().tobytes())
    a3.add_path(p3)
    a3.process_all()

    def step3():
        a3._poll()
        if any(i["status"] in ("pending", "working") for i in a3.items):
            a3.root.after(80, step3)
        else:
            item = a3.items[0]
            a3.tree.selection_set(item["iid"])
            # retry an already-cleaned item -> goes back through the queue
            a3._retry_item(item)
            check("retry resets to pending/working",
                  item["status"] in ("pending", "working"), item["status"])
            # remove a single item
            a3.remove_item(item)
            check("remove_item drops row", a3.items == [])
            check("tree empty after remove",
                  len(a3.tree.get_children()) == 0)
            a3.root.destroy()

    a3.root.after(80, step3)
    a3.root.mainloop()

    # save-on-close writes config
    if appmod.HAS_DND:
        root4 = appmod.TkinterDnD.Tk()
    else:
        import tkinter as _tk
        root4 = _tk.Tk()
    a4 = appmod.PrivacyDropApp(root4)
    a4.suffix.set("_saved")
    a4._on_close()
    d = config.load()
    check("close saves settings", d["suffix"] == "_saved", str(d))

    os.environ.pop("PRIVACYDROP_CONFIG", None)


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(os.path.join(TMP, "out"), exist_ok=True)
    t_config()
    t_jpeg_aliases()
    t_report_text()
    t_gui_features()
    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
