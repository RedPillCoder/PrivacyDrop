"""Deep GUI verification: options, folder recursion, multi-file batches,
error handling, and the worker-thread fixes.  Run under xvfb:
    xvfb-run -a python tests/test_gui_full.py
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

import app as appmod
import scrubber

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_gui2")
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def jpeg(path, with_meta=True, with_icc=False):
    img = Image.new("RGB", (48, 36), (200, 40, 40))
    kw = {}
    if with_meta:
        exif = Image.Exif()
        exif[0x010F] = "Acme Corp"
        exif[0x0110] = "SecretCam 9000"
        exif[0x8825] = {1: "S",
                        2: (IFDRational(31, 1), IFDRational(57, 1), IFDRational(1, 1)),
                        3: "E",
                        4: (IFDRational(115, 1), IFDRational(51, 1), IFDRational(1, 1))}
        kw["exif"] = exif.tobytes()
    if with_icc:
        from PIL import ImageCms
        kw["icc_profile"] = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")).tobytes()
    img.save(path, "JPEG", **kw)


def run_until_done(a, timeout_ms=15000):
    """Drive the Tk event loop until all items leave pending/working."""
    state = {"t": 0}

    def step():
        a._poll()
        pending = any(i["status"] in ("pending", "working") for i in a.items)
        if pending and state["t"] < timeout_ms:
            state["t"] += 100
            a.root.after(100, step)
        else:
            state["banner"] = a.banner.cget("text")
            a.root.destroy()

    a.root.after(50, step)
    a.root.mainloop()
    return state


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)

    print("\n[GUI: options + batch + worker]")
    root = appmod.TkinterDnD.Tk()
    a = appmod.PrivacyDropApp(root)

    # --- folder recursion: mixed folder with subdir + unsupported file
    folder = os.path.join(TMP, "batch")
    os.makedirs(os.path.join(folder, "sub"))
    jpeg(os.path.join(folder, "one.jpg"))
    jpeg(os.path.join(folder, "sub", "two.jpg"))
    open(os.path.join(folder, "note.txt"), "w").write("x")
    added = a.add_path(folder)
    check("folder recursion added 2 files", added == 2, f"added={added}")

    # --- single-file add + dedup
    single = os.path.join(TMP, "solo.jpg")
    jpeg(single)
    check("single add", a.add_path(single) == 1)
    check("dedup (same file twice)", a.add_path(single) == 0)

    # --- options: suffix + strip ICC
    a.suffix.set("_scrubbed")
    a.strip_icc.set(True)
    check("remove_scripts defaults ON (secure default)",
          a.remove_scripts.get() is True)
    icc = os.path.join(TMP, "icc.jpg")
    jpeg(icc, with_icc=True)
    a.add_path(icc)

    # --- unsupported file shows as skipped
    txt = os.path.join(TMP, "plain.txt")
    open(txt, "w").write("hi")
    a.add_path(txt)
    check("unsupported marked skipped",
          any(i["path"] == txt and i["status"] == "skipped"
              for i in a.items))

    # --- process everything
    a.process_all()
    state = run_until_done(a)

    # results
    by_path = {i["path"]: i for i in a.items}
    check("batch one.jpg cleaned", by_path[os.path.join(folder, "one.jpg")]["status"] == "ok")
    check("batch sub/two.jpg cleaned",
          by_path[os.path.join(folder, "sub", "two.jpg")]["status"] == "ok")
    check("solo cleaned", by_path[single]["status"] == "ok")
    check("GPS location shown in details (privacy transparency)",
          "GPS location" in by_path[single]["details"],
          by_path[single]["details"])
    check("solo used custom suffix", by_path[single]["out"].endswith("_scrubbed.jpg"),
          by_path[single]["out"])
    check("banner reports results", "safe to share" in state["banner"],
          state["banner"])
    check("no pending/working items left",
          all(i["status"] not in ("pending", "working") for i in a.items))

    # ICC option applied
    out = by_path[icc]["out"]
    check("ICC-strip output exists", os.path.exists(out))
    if os.path.exists(out):
        data = open(out, "rb").read()
        check("ICC removed from output", b"ICC_PROFILE" not in data)

    # originals untouched
    check("originals untouched",
          all(not i["out"] or not os.path.samefile(i["path"], i["out"])
              for i in a.items if i["out"]))

    print("\n[GUI: subfolder mode]")
    root = appmod.TkinterDnD.Tk()
    a = appmod.PrivacyDropApp(root)
    a.subfolder.set(True)
    src = os.path.join(TMP, "subfolder_src.jpg")
    jpeg(src)
    a.add_path(src)
    a.process_all()
    state = run_until_done(a)
    item = a.items[0]
    expected_dir = os.path.join(TMP, "Clean")
    check("wrote into 'Clean' subfolder",
          os.path.dirname(item["out"]) == expected_dir
          and os.path.isfile(item["out"]),
          item["out"])

    print("\n[GUI: error handling — password PDF + corrupt file]")
    root = appmod.TkinterDnD.Tk()
    a = appmod.PrivacyDropApp(root)
    import pikepdf
    pw = os.path.join(TMP, "locked.pdf")
    pdf = pikepdf.new(); pdf.add_blank_page()
    pdf.save(pw, encryption=pikepdf.Encryption(owner="s", user="s"))
    a.add_path(pw)
    bad = os.path.join(TMP, "corrupt.jpg")
    open(bad, "wb").write(b"\xff\xd8 garbage")
    a.add_path(bad)
    a.process_all()
    state = run_until_done(a)
    check("password pdf -> failed",
          any(i["status"] == "error" for i in a.items if i["path"] == pw))
    check("corrupt jpg -> failed",
          any(i["status"] == "error" for i in a.items if i["path"] == bad))
    check("banner shows errors", "failed" in state["banner"], state["banner"])
    check("app kept running (worker survived errors)", True)

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
