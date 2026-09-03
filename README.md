# ️ PrivacyDrop

**Drop it. Clean it. Share it.**

PrivacyDrop is a small, fast, privacy-first Windows desktop app. Drag & drop
images or documents onto the window (or straight onto the app icon) and it
instantly creates a **sanitized copy** — hidden metadata, GPS location, camera
& device details, author names and other embedded identifiers are removed —
while the original file is **never touched**.

Everything runs **100% locally on your machine**. Nothing is uploaded, no
network, no accounts, no telemetry.

---

## ✨ Features

| | |
|---|---|
| 🖱️ **True drop box** | Drop files onto the window *or* onto `PrivacyDrop.exe` itself — then **drag the cleaned copies back out** to Explorer, double-click to open, or right-click for Open / Show in folder / Copy path |
| 📸 **Images** | JPG/JPEG, JFIF, JPE, PNG, TIFF, WebP, HEIC/HEIF, GIF, BMP |
| 📄 **Documents** | PDF, DOCX, XLSX, PPTX |
| 🎯 **Lossless where it matters** | JPEG / PNG / WebP are cleaned at the *byte level* — **no recompression, zero quality loss** |
| 🧹 **Deep cleaning** | EXIF, GPS, XMP, IPTC, Photoshop IRB, comments, timestamps, thumbnails, device make/model, software tags, PDF author/title/producer, embedded files, Office author/last-modified-by/company, edit-session IDs (rsid), metadata in images *inside* documents |
| 📍 **Location transparency** | When a photo carries GPS coordinates, PrivacyDrop **shows you the position it removed** (e.g. *GPS location (31°57′S, 115°51′E)*) so you know exactly what was leaked |
|  **Document fingerprint reset** | PDFs carry a stable `/ID` identifier that survives edits — it's reset so the cleaned copy can't be traced back to the original |
| 🛡️ **Executable content stripped** | PDF JavaScript, launch actions, XFA forms and Office **VBA macros** are removed by default — you can't accidentally share a document that runs code |
|  **Hardened against hostile files** | Decompression-bomb (zip-bomb) defence, zip-slip / path-traversal / drive-letter entry rejection, input size limits, encrypted-archive handling, and **no XML parsing** of untrusted document metadata (immune to XXE / billion-laughs) |
| ⚙️ **Remembers your settings** | Suffix, subfolder and privacy options persist locally (stored offline — never transmitted) |
| 📊 **Progress & report** | Live progress bar and counts, plus an opt-in *Save Report…* text log of what was removed (with bytes saved) |
| ✅ **Clear confirmation** | Green banner — *"✓ 3 cleaned — safe to share. Originals untouched."* — plus a per-file list of exactly what was removed |
| 🔒 **Originals are sacred** | Only copies are ever written; your source files are never modified or deleted |

---

## 🚀 Get started

### Option A — use the ready-made app (recommended)

Download the latest release from
[GitHub Releases](https://github.com/privacypdrop/privacypdrop/releases) and
run `PrivacyDrop-<version>-Setup.exe`. No Python needed.

On first launch Windows SmartScreen may ask you to confirm — click
**More info → Run anyway** (this is normal for open-source apps without a
paid code-signing certificate).

### Option B — build from source (Windows)

Requires [Python 3.10+](https://www.python.org/downloads/).

1. Double-click **`build_windows.bat`**
2. Wait for the one-click build to finish
3. Your app is at **`dist\PrivacyDrop.exe`**

### Option C — run from source (developers)

```bat
run_windows.bat
```

…or manually:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

HEIC/HEIF (iPhone) support is included out of the box.

---

## 🔍 What exactly gets removed

| Format | Removed |
|---|---|
| **JPG/JPEG/JFIF/JPE** | EXIF (camera make/model, lens, serial, date/time, **GPS location**), XMP, IPTC, Photoshop Image Resources, comments, embedded thumbnail, MPF/other APP blocks — *losslessly, no re-encoding* |
| **PNG** | Text chunks (author, software, description), `eXIf` (EXIF incl. GPS), `tIME` timestamp, unknown ancillary chunks — *losslessly* |
| **WebP** | EXIF, XMP chunks + VP8X flags — *losslessly* |
| **TIFF / GIF / BMP / HEIC** | All identity tags (Make, Model, Software, Artist, GPS, comments) re-stripped on save |
| **PDF** | Document info (Title, Author, Subject, Keywords, Creator, Producer, dates), XMP metadata (root *and* page-level), **embedded file attachments**, **JavaScript, launch actions & XFA forms**, `/PieceInfo` editing history, and the **document `/ID` fingerprint is reset** |
| **DOCX / XLSX / PPTX** | Author, last modified by, title, comments, dates, company, manager, application tags, custom properties, **VBA macro projects**, **edit-session IDs (w:rsid)**, **macro references** in `[Content_Types].xml`/`.rels` — **plus** EXIF scrubbed from every image embedded inside the document, and thumbnail timestamps zeroed |

**Colour profiles (ICC)** are kept by default so photos keep rendering
correctly — tick *"Also remove color profiles"* if you want them gone too.

**Macros & scripts** (VBA projects, PDF JavaScript, launch actions, XFA
forms) are stripped by default. Untick *"Remove macros & scripts"* only if
you deliberately need to share executable content.

---

## 🔐 Privacy guarantees

- **Offline by design** — no network code at all.
- **Original files are never modified** — a copy is always written with your
  chosen suffix (default `_clean`), and it is written **atomically** (temp
  file + rename), so a crash can never leave a half-written file.
- **Hostile inputs are contained** — oversized files, zip bombs, zip-slip /
  traversal entries, encrypted archives and entity-laden XML are all rejected
  or neutralized without parsing untrusted XML.
- **No history** — no log of your files is kept anywhere.
- **Open source** — read `scrubber.py`; the cleaning logic is plain,
  auditable Python.

### Honest limitations

- Cleaning is for **common metadata** (the stuff that normally leaks identity
  and location). A determined adversary with specialised forensics may still
  infer things from file content itself (e.g. text *inside* the document, or
  what's visible in a photo). Review what you share.
- **PDFs** keep annotations/form fields and normal (non-executable) actions
  like links (they're content, not identity) — only executable content
  (JavaScript, launch actions, XFA) is removed.
- **Legacy `.doc` / `.xls` / `.ppt`** files are not supported — save them as
  the modern `.docx/.xlsx/.pptx` format first.
- Password-protected PDFs and encrypted Office packages are skipped with a
  clear message.

---

## 📁 Project layout

```
privacydrop/
├── app.py                 # the drag & drop GUI (tkinter)
├── scrubber.py            # the sanitization engine (also usable as a CLI)
├── config.py              # local, offline user preferences
├── version.py             # single source of truth for the version number
├── requirements.txt       # runtime Python dependencies
├── requirements-dev.txt   # test dependencies (includes requirements.txt)
├── build_windows.bat      # one-click Windows build → dist\PrivacyDrop.exe
├── build_release.bat      # full release build on Windows (zips + checksums)
├── build_release.sh       # full release build on Linux / macOS / WSL
├── installer.nsi          # NSIS installer script (Windows)
├── run_windows.bat        # run from source without building
├── assets/icon.ico        # app icon
── tests/                 # automated tests (engine, security, privacy, GUI)
└── release/               # built release artifacts (created by build scripts)
```

### Keyboard shortcuts

- **Ctrl+O** — add files
- **Delete** — remove the selected row
- **Double-click** a row — open the cleaned file
- **Right-click** a row — Open / Show in folder / Copy path / Retry / Remove
- **Drag a cleaned row** back out to Explorer to drop the clean copy anywhere

### CLI (power users)

```bash
python scrubber.py photo.jpg report.pdf --out cleaned/ --suffix _safe
```

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
python -m tests.test_engine        # core cleaning: metadata removed, quality kept
python -m tests.test_full          # every format, option & edge case
python -m tests.test_security      # hostile-input hardening (bombs, zip-slip, XML, macros, JS)
python -m tests.test_privacy       # GPS reporting, /ID reset, rsids, macro-refs
python -m tests.test_app_features  # config, aliases, report, drag-out, progress
python -m tests.test_gui_full      # GUI behaviour (run under Xvfb on Linux)
```

All 287+ automated checks must pass before a release is built.

---

## 📦 Releases

Tag a new version, push, and CI does the rest:

```bash
# 1. Bump the version (single source of truth)
echo "1.2.0" > VERSION
#    also update version.py:  APP_VERSION = "1.2.0"

# 2. Update CHANGELOG.md under an "Unreleased" heading, then rename to the version

# 3. Tag & push — GitHub Actions builds and drafts the release
git add -A && git commit -m "release: v1.2.0"
git tag v1.2.0
git push origin main --tags
```

CI runs the full test suite on Python 3.10–3.13, then creates a draft
GitHub Release with the portable zip, source zip, checksums, and installer
(if `makensis` is available).  Review the draft and hit **Publish**.

For a manual build on Windows, run `build_release.bat`.  On Linux/macOS/WSL,
run `./build_release.sh`.

See `release/README.md` for a description of every artifact and how to
verify downloads.

---

##  License

MIT — do what you like with it. Keep your metadata to yourself.
See [LICENSE](LICENSE) for the full text.
