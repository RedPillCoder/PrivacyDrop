"""Headless GUI smoke test: drives the real app, cleans a file, checks UI."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

import app as appmod

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_gui")


def make_jpeg(path):
    img = Image.new("RGB", (48, 36), (180, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Acme Corp"
    exif[0x8825] = {1: "S", 2: (IFDRational(31, 1), IFDRational(57, 1),
                                IFDRational(1, 1)),
                    3: "E", 4: (IFDRational(115, 1), IFDRational(51, 1),
                                IFDRational(1, 1))}
    img.save(path, "JPEG", exif=exif.tobytes())


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    src = os.path.join(TMP, "photo.jpg")
    make_jpeg(src)

    if appmod.HAS_DND:
        root = appmod.TkinterDnD.Tk()
    else:
        import tkinter as tk
        root = tk.Tk()
    a = appmod.PrivacyDropApp(root)
    a.add_path(src)
    assert len(a.items) == 1, "item added"
    a.process_all()

    state = {"done": False, "banner": ""}

    def check():
        if a.items and a.items[0]["status"] in ("ok", "clean", "error"):
            state["done"] = True
            state["banner"] = a.banner.cget("text")

    def loop(n):
        a._poll()
        check()
        if state["done"] or n <= 0:
            root.destroy()
        else:
            root.after(100, lambda: loop(n - 1))

    root.after(100, lambda: loop(50))
    root.mainloop()

    item = a.items[0]
    print("status:", item["status"])
    print("details:", item["details"])
    print("banner:", state["banner"])
    print("out:", item["out"])
    assert item["status"] == "ok", f"expected ok, got {item['status']}"
    assert "EXIF" in item["details"], "EXIF removal reported"
    assert "safe to share" in state["banner"], "banner confirms"
    assert os.path.isfile(item["out"]), "output file written"
    with Image.open(item["out"]) as im:
        assert not dict(im.getexif()), "output has no EXIF"
    print("\nGUI SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
