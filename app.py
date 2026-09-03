"""
PrivacyDrop — privacy-first drop box for Windows.

Drag & drop images or documents onto the window (or onto the app icon).
Each file is immediately copied, sanitized (metadata, location, device and
author info removed) and saved as a new file ready for sharing. The original
is never touched.

Run:      python app.py
Build:    build_windows.bat   (produces a standalone PrivacyDrop.exe)
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox

import config
from scrubber import (sanitize_file, Options, default_output_path, supported,
                      SUPPORTED_EXTS)

try:
    from tkinterdnd2 import COPY, DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    COPY = "copy"
    DND_FILES = "DND_Files"
    HAS_DND = False

APP_NAME = "PrivacyDrop"
from version import APP_VERSION
SUFFIX_DEFAULT = "_clean"

COLOR_ACCENT = "#147a3c"      # green — "cleaned / ready to share"
COLOR_BG = "#f5f7f6"
COLOR_DROP = "#eef4f0"
COLOR_DROP_ACTIVE = "#ddefe4"
COLOR_TEXT = "#1c2b23"
COLOR_MUTED = "#5b6b61"

# status -> (icon, color, tag)
STATUS_STYLE = {
    "ok":     ("\u2713", COLOR_ACCENT, "ok"),
    "clean":  ("\u2713", "#1d6fa5", "clean"),
    "skipped": ("\u2013", "#8a928d", "skip"),
    "error":  ("\u2717", "#c0392b", "err"),
}


def open_folder(path: str) -> None:
    """Open a folder in the system file manager."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1024:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def build_report_text(items: list, app_version: str = APP_VERSION) -> str:
    """Render the session results as a plain-text privacy report.

    Lists each file, its outcome, what was removed, and the bytes saved.
    Only ever called when the user explicitly clicks "Save Report…".
    """
    lines = [
        f"{APP_NAME} v{app_version} — sanitization report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 62,
        "",
    ]
    counts = {"ok": 0, "clean": 0, "skipped": 0, "error": 0}
    for item in items:
        status = item.get("status", "")
        counts[status] = counts.get(status, 0) + 1
        lines.append(f"  {os.path.basename(item['path'])}")
        lines.append(f"      status : {status}")
        lines.append(f"      result : {item.get('details') or '—'}")
        out = item.get("out")
        if out and os.path.isfile(out) and os.path.isfile(item["path"]):
            src_sz = os.path.getsize(item["path"])
            out_sz = os.path.getsize(out)
            saved = src_sz - out_sz
            pct = (saved / src_sz * 100) if src_sz else 0.0
            lines.append(
                f"      output : {os.path.basename(out)} "
                f"({_fmt_bytes(src_sz)} â†’ {_fmt_bytes(out_sz)}, "
                f"{'-' if saved >= 0 else '+'}{_fmt_bytes(abs(saved))} "
                f"({pct:+.1f}%))")
        elif out:
            lines.append(f"      output : {os.path.basename(out)}")
        lines.append("")

    lines.append("-" * 62)
    summary = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()) if v)
    lines.append(f"Total files: {len(items)}   ({summary})")
    lines.append("Originals were never modified.")
    return "\n".join(lines) + "\n"


class PrivacyDropApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.items: list[dict] = []      # {path, status, details, out}
        self.jobs: "queue.Queue" = queue.Queue()   # (path, opts, subfolder)
        self.results: "queue.Queue" = queue.Queue()
        self.last_output_dir: str | None = None
        self._job_total = 0
        self._bytes_saved = 0            # cumulative bytes saved this session

        # Persistent preferences (loaded from a local, offline config file).
        prefs = config.load()
        self.suffix = tk.StringVar(value=prefs["suffix"])
        self.subfolder = tk.BooleanVar(value=prefs["subfolder"])
        self.strip_icc = tk.BooleanVar(value=prefs["strip_icc"])
        self.keep_attachments = tk.BooleanVar(value=prefs["keep_attachments"])
        self.remove_scripts = tk.BooleanVar(value=prefs["remove_scripts"])
        self.topmost = tk.BooleanVar(value=prefs["topmost"])

        self._build_ui()
        # Persistent worker thread: it blocks on the jobs queue forever and
        # only reads plain-Python option snapshots (never Tk variables), so
        # all Tkinter access stays on the main thread.
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self.root.after(80, self._poll)

        # Save preferences on close; restore "always on top" if requested.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._toggle_topmost()
        self._bind_shortcuts()
        self._bind_auto_save()

        # Files dropped onto the .exe icon arrive via argv.
        for p in sys.argv[1:]:
            self.add_path(p)
        if self.items:
            self.process_all()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.root.title(f"{APP_NAME} — drop it, clean it, share it")
        self.root.geometry("700x640")
        self.root.minsize(560, 520)
        self.root.configure(bg=COLOR_BG)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabelframe", background=COLOR_BG)
        style.configure("TLabelframe.Label", background=COLOR_BG,
                        foreground=COLOR_MUTED)
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 6))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        padding=(16, 8), background=COLOR_ACCENT,
                        foreground="white")
        style.map("Accent.TButton",
                  background=[("active", "#0e5c2d")])
        style.configure("TCheckbutton", background=COLOR_BG,
                        foreground=COLOR_TEXT, font=("Segoe UI", 9))
        style.configure("TRadiobutton", background=COLOR_BG,
                        foreground=COLOR_TEXT, font=("Segoe UI", 9))

        pad = {"padx": 14, "pady": 6}

        # Header
        header = tk.Frame(self.root, bg=COLOR_BG)
        header.pack(fill="x", **pad)
        tk.Label(header, text=APP_NAME, bg=COLOR_BG, fg=COLOR_ACCENT,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(header,
                 text="Drop files in — get a metadata-free copy back. "
                      "Your originals are never modified.",
                 bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w")

        # Drop zone
        self.drop_border = tk.Frame(self.root, bg=COLOR_DROP,
                                    highlightthickness=2,
                                    highlightbackground="#9fb7a6",
                                    highlightcolor=COLOR_ACCENT)
        self.drop_border.pack(fill="x", padx=14, pady=(10, 4))
        inner = tk.Frame(self.drop_border, bg=COLOR_DROP)
        inner.pack(fill="both", expand=True, padx=18, pady=22)
        self.drop_label = tk.Label(
            inner, bg=COLOR_DROP, fg=COLOR_TEXT,
            font=("Segoe UI", 13, "bold"),
            text="\u2b07  Drag & drop images or documents here  \u2b07")
        self.drop_label.pack()
        self.drop_sub = tk.Label(
            inner, bg=COLOR_DROP, fg=COLOR_MUTED, font=("Segoe UI", 9),
            text="JPG \u00b7 PNG \u00b7 TIFF \u00b7 WebP \u00b7 HEIC \u00b7 "
                 "GIF \u00b7 BMP   |   PDF \u00b7 DOCX \u00b7 XLSX \u00b7 PPTX")
        self.drop_sub.pack(pady=(4, 0))
        tk.Label(inner, bg=COLOR_DROP, fg=COLOR_MUTED, font=("Segoe UI", 8),
                 text="(you can also drop files onto the PrivacyDrop icon)") \
            .pack(pady=(2, 0))

        if HAS_DND:
            for w in (self.drop_border, inner, self.drop_label, self.drop_sub):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", self.on_drop_enter)
                w.dnd_bind("<<DropLeave>>", self.on_drop_leave)
        else:
            self.drop_sub.configure(
                text="Drag & drop unavailable — use \u201cAdd Files\u201d below.")

        # Controls row
        controls = tk.Frame(self.root, bg=COLOR_BG)
        controls.pack(fill="x", padx=14, pady=4)
        ttk.Button(controls, text="\u271a  Add Files\u2026",
                   command=self.choose_files).pack(side="left")
        ttk.Button(controls, text="\u27f3  Clean All",
                   style="Accent.TButton",
                   command=self.process_all).pack(side="left", padx=8)
        ttk.Button(controls, text="\u2715  Clear List",
                   command=self.clear_list).pack(side="left")
        ttk.Button(controls, text="\u2714  Clear Done",
                   command=self.clear_completed).pack(side="left")
        ttk.Button(controls, text="\u21bb  Re-clean All",
                   command=self.reclean_all).pack(side="left")
        ttk.Button(controls, text="\U0001f4c2  Open Output Folder",
                   command=self.open_output).pack(side="right")
        ttk.Button(controls, text="\U0001f4dd  Save Report\u2026",
                   command=self.save_report).pack(side="right", padx=6)
        ttk.Button(controls, text="\u24d8  About",
                   command=self.show_about).pack(side="right")
        ttk.Checkbutton(controls, text="Always on top",
                        variable=self.topmost,
                        command=self._toggle_topmost).pack(side="right",
                                                          padx=8)

        # Options
        opts = ttk.Labelframe(self.root, text="  Options  ")
        opts.pack(fill="x", padx=14, pady=6)
        row1 = tk.Frame(opts, bg=COLOR_BG)
        row1.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(row1, text="File name suffix:").pack(side="left")
        ttk.Entry(row1, textvariable=self.suffix, width=12) \
            .pack(side="left", padx=6)
        ttk.Radiobutton(row1, text="Next to original", value=False,
                        variable=self.subfolder).pack(side="left", padx=8)
        ttk.Radiobutton(row1, text="In a \u201cClean\u201d subfolder",
                        value=True,
                        variable=self.subfolder).pack(side="left", padx=4)
        row2 = tk.Frame(opts, bg=COLOR_BG)
        row2.pack(fill="x", padx=10, pady=(2, 8))
        ttk.Checkbutton(row2, text="Also remove color profiles (ICC)",
                        variable=self.strip_icc).pack(side="left")
        ttk.Checkbutton(row2, text="Keep files embedded inside PDFs",
                        variable=self.keep_attachments).pack(side="left",
                                                             padx=12)
        row3 = tk.Frame(opts, bg=COLOR_BG)
        row3.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Checkbutton(row3, text="Remove macros & scripts (recommended)",
                        variable=self.remove_scripts).pack(side="left")

        # Results table
        table_frame = tk.Frame(self.root, bg=COLOR_BG)
        table_frame.pack(fill="both", expand=True, padx=14, pady=(4, 2))
        cols = ("file", "size", "status", "details")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                 height=9)
        self.tree.heading("file", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("status", text="Status")
        self.tree.heading("details", text="What was removed")
        self.tree.column("file", width=180, anchor="w")
        self.tree.column("size", width=70, anchor="e")
        self.tree.column("status", width=110, anchor="w")
        self.tree.column("details", width=310, anchor="w")
        for tag, color in (("ok", COLOR_ACCENT), ("clean", "#1d6fa5"),
                           ("skip", "#8a928d"), ("err", "#c0392b")):
            self.tree.tag_configure(tag, foreground=color)
        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Interact with results: double-click to open, right-click for a
        # menu, and drag a cleaned row straight back out to Explorer.
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_menu)
        self._menu = tk.Menu(self.root, tearoff=0)
        self._menu.add_command(label="Open cleaned file",
                               command=lambda: self._menu_act("open"))
        self._menu.add_command(label="Open original file",
                               command=lambda: self._menu_act("open_orig"))
        self._menu.add_command(label="Show in folder",
                               command=lambda: self._menu_act("reveal"))
        self._menu.add_command(label="Copy path",
                               command=lambda: self._menu_act("copy"))
        self._menu.add_separator()
        self._menu.add_command(label="Retry",
                               command=lambda: self._menu_act("retry"))
        self._menu.add_command(label="Remove from list",
                               command=lambda: self._menu_act("remove"))
        if HAS_DND:
            try:
                self.tree.drag_source_register(1, DND_FILES)
                self.tree.dnd_bind("<<DragInitCmd>>", self._drag_init)
            except Exception:
                pass

        # Progress + status
        status = tk.Frame(self.root, bg=COLOR_BG)
        status.pack(fill="x", padx=14, pady=(0, 2))
        self.progress = ttk.Progressbar(status, mode="determinate",
                                        maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_label = tk.Label(status, bg=COLOR_BG, fg=COLOR_MUTED,
                                     font=("Segoe UI", 9), text="")
        self.status_label.pack(side="right", padx=(8, 0))

        # Summary banner
        self.banner = tk.Label(self.root, bg=COLOR_BG, fg=COLOR_MUTED,
                               font=("Segoe UI", 11, "bold"),
                               text="Ready. Drop files to begin.")
        self.banner.pack(fill="x", padx=14, pady=(2, 12))

    # ------------------------------------------------------------- actions
    def _toggle_topmost(self) -> None:
        self.root.attributes("-topmost", self.topmost.get())

    def on_drop_enter(self, _event) -> str:
        self.drop_border.configure(bg=COLOR_DROP_ACTIVE)
        self.drop_label.configure(bg=COLOR_DROP_ACTIVE)
        self.drop_sub.configure(bg=COLOR_DROP_ACTIVE)
        return "copy"

    def on_drop_leave(self, _event) -> None:
        self.drop_border.configure(bg=COLOR_DROP)
        self.drop_label.configure(bg=COLOR_DROP)
        self.drop_sub.configure(bg=COLOR_DROP)

    def on_drop(self, event) -> None:
        self.on_drop_leave(event)
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = []
        added = 0
        for p in paths:
            added += self.add_path(p)
        if added:
            self.process_all()

    def choose_files(self) -> None:
        patterns = [("Supported files", "*.jpg *.jpeg *.jfif *.jpe *.png "
                    "*.tif *.tiff *.webp *.heic *.heif *.gif *.bmp *.pdf "
                    "*.docx *.xlsx *.pptx"),
                    ("Images", "*.jpg *.jpeg *.jfif *.jpe *.png *.tif "
                     "*.tiff *.webp *.heic *.heif *.gif *.bmp"),
                    ("Documents", "*.pdf *.docx *.xlsx *.pptx"),
                    ("All files", "*.*")]
        paths = filedialog.askopenfilenames(
            title="Choose images or documents to clean",
            filetypes=patterns)
        added = sum(self.add_path(p) for p in paths)
        if added:
            self.process_all()

    def add_path(self, path: str) -> int:
        """Add a file (or every supported file under a folder)."""
        added = 0
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in sorted(files):
                    added += self.add_path(os.path.join(root, f))
            return added
        if not os.path.isfile(path):
            return 0
        if any(it["path"] == path for it in self.items):
            return 0
        if supported(path):
            item = {"path": path, "status": "pending", "details": "",
                    "out": "", "iid": None}
            self.items.append(item)
            try:
                size_str = _fmt_bytes(os.path.getsize(path))
            except OSError:
                size_str = "\u2014"
            item["iid"] = self.tree.insert(
                "", "end",
                values=(os.path.basename(path), size_str, "queued\u2026", ""))
            added += 1
        else:
            item = {"path": path, "status": "skipped",
                    "details": "unsupported file type", "out": "", "iid": None}
            self.items.append(item)
            item["iid"] = self.tree.insert(
                "", "end",
                values=(os.path.basename(path),
                        "\u2014",
                        STATUS_STYLE["skipped"][0] + " skipped",
                        "unsupported file type"), tags=("skip",))
        return added

    def process_all(self) -> None:
        # Snapshot options on the main thread; the worker only reads these
        # plain values, never the Tk variables directly.
        opts = Options(
            strip_icc=self.strip_icc.get(),
            remove_pdf_attachments=not self.keep_attachments.get(),
            remove_scripts=self.remove_scripts.get(),
            suffix=self.suffix.get())
        subfolder = self.subfolder.get()
        queued = 0
        for item in self.items:
            if item["status"] == "pending":
                item["status"] = "working"
                self.jobs.put((item["path"], opts, subfolder))
                queued += 1
        if queued:
            self._job_total += queued
            self.progress.configure(maximum=max(1, self._job_total),
                                    value=max(0, self._job_total - queued))
            self._update_status()

    def _worker_loop(self) -> None:
        while True:
            try:
                path, opts, subfolder = self.jobs.get(timeout=0.4)
            except queue.Empty:
                continue
            dst = default_output_path(
                path, None, opts.suffix or SUFFIX_DEFAULT,
                subfolder=subfolder)
            try:
                rep = sanitize_file(path, dst, opts)
            except Exception as e:  # never let a bad file kill the worker
                from scrubber import Report
                rep = Report(src=path, dst=dst, status="error", error=str(e))
            self.results.put(rep)

    def _poll(self) -> None:
        try:
            while True:
                rep = self.results.get_nowait()
                self._apply_result(rep)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _apply_result(self, rep) -> None:
        item = next((i for i in self.items if i["path"] == rep.src), None)
        if item is None:
            return
        icon, color, tag = STATUS_STYLE.get(
            rep.status, STATUS_STYLE["skipped"])
        item["status"] = rep.status
        item["details"] = rep.summary()
        item["out"] = rep.dst

        # Track bytes saved for this file (cumulative).
        saved = 0
        out_size_str = "\u2014"
        if rep.ok and os.path.isfile(rep.dst) and os.path.isfile(rep.src):
            try:
                src_sz = os.path.getsize(rep.src)
                out_sz = os.path.getsize(rep.dst)
                saved = src_sz - out_sz
                if saved > 0:
                    self._bytes_saved += saved
                out_size_str = f"{_fmt_bytes(src_sz)} \u2192 {_fmt_bytes(out_sz)}"
            except OSError:
                pass

        if rep.ok:
            self.last_output_dir = os.path.dirname(rep.dst)
        if item["iid"] is not None and self.tree.exists(item["iid"]):
            label = {
                "ok": icon + "  Cleaned",
                "clean": icon + "  Clean (already)",
                "skipped": icon + "  Skipped",
                "error": icon + "  Failed",
            }.get(rep.status, rep.status)
            self.tree.item(item["iid"], values=(
                os.path.basename(rep.src), out_size_str, label,
                rep.error if rep.status == "error" else rep.summary()),
                tags=(tag,))
        # Advance progress only once per job completion.
        if not item.get("_counted"):
            item["_counted"] = True
            done = self.progress["value"] + 1
            self.progress.configure(value=min(done, self.progress["maximum"]))
        self._update_banner()
        self._update_status()

    def _update_banner(self) -> None:
        counts = {"ok": 0, "clean": 0, "skipped": 0, "error": 0}
        pending = 0
        for i in self.items:
            if i["status"] == "pending" or i["status"] == "working":
                pending += 1
            elif i["status"] in counts:
                counts[i["status"]] += 1
        done = len(self.items) - pending
        if pending:
            self.banner.configure(
                text=f"\u231b  Cleaning\u2026 {done} done, {pending} in progress",
                fg=COLOR_MUTED)
        elif not self.items:
            self.banner.configure(text="Ready. Drop files to begin.",
                                  fg=COLOR_MUTED)
        else:
            parts = []
            if counts["ok"]:
                parts.append(f"{counts['ok']} cleaned")
            if counts["clean"]:
                parts.append(f"{counts['clean']} already clean")
            if counts["skipped"]:
                parts.append(f"{counts['skipped']} skipped")
            if counts["error"]:
                parts.append(f"{counts['error']} failed")
            if counts["error"]:
                self.banner.configure(
                    text=f"\u2717  {'\u00b7 '.join(parts)} — see list for errors",
                    fg="#c0392b")
            else:
                self.banner.configure(
                    text=f"\u2713  {'\u00b7 '.join(parts)} — safe to share. "
                         f"Originals untouched.",
                    fg=COLOR_ACCENT)

    def clear_list(self) -> None:
        if self.items:
            counts = {"ok": 0, "clean": 0, "skipped": 0, "error": 0,
                      "pending": 0, "working": 0}
            for i in self.items:
                counts[i["status"]] = counts.get(i["status"], 0) + 1
            pending = counts["pending"] + counts["working"]
            done = sum(v for k, v in counts.items() if k not in ("pending", "working"))
            if done and not messagebox.askyesno(
                    APP_NAME,
                    f"Remove all {len(self.items)} items from the list?\n\n"
                    f"  {done} finished item(s) will be removed\n"
                    f"  {pending} item(s) still in progress will be kept\n\n"
                    "This action cannot be undone."):
                return
        for i in self.items:
            if i["iid"] is not None:
                self.tree.delete(i["iid"])
        self.items.clear()
        self._job_total = 0
        self._bytes_saved = 0
        self.progress.configure(value=0, maximum=1)
        self._update_banner()
        self._update_status()

    def clear_completed(self) -> None:
        """Remove only finished items (ok/clean/skipped/error), keeping pending ones."""
        keep = []
        for i in self.items:
            if i["status"] in ("pending", "working"):
                keep.append(i)
            else:
                if i["iid"] is not None and self.tree.exists(i["iid"]):
                    self.tree.delete(i["iid"])
                # Adjust progress for counted items
                if i.get("_counted") and self.progress["value"] > 0:
                    self.progress.configure(value=self.progress["value"] - 1)
        self.items = keep
        # Reset bytes saved since those files are no longer tracked
        self._bytes_saved = 0
        self._update_banner()
        self._update_status()

    def reclean_all(self) -> None:
        """Reset all finished items to pending and re-clean with current options.

        Useful when the user has changed options (e.g. toggled "strip ICC")
        and wants to re-apply them to the existing list.
        """
        reset = 0
        for item in self.items:
            if item["status"] in ("ok", "clean", "skipped", "error"):
                item["status"] = "pending"
                item["details"] = ""
                item["out"] = ""
                item["_counted"] = False
                if item["iid"] is not None and self.tree.exists(item["iid"]):
                    try:
                        size_str = _fmt_bytes(os.path.getsize(item["path"]))
                    except OSError:
                        size_str = "\u2014"
                    self.tree.item(item["iid"], values=(
                        os.path.basename(item["path"]), size_str, "queued\u2026", ""),
                        tags=())
                reset += 1
        if reset:
            self._job_total = 0  # reset progress since we're re-queuing
            self._bytes_saved = 0
            self.progress.configure(value=0, maximum=1)
            self.process_all()

    def open_output(self) -> None:
        target = self.last_output_dir
        if not target and self.items:
            target = os.path.dirname(self.items[0]["path"])
        if not target:
            target = os.path.expanduser("~")
        if not os.path.isdir(target):
            target = os.path.expanduser("~")
        open_folder(target)

    # --------------------------------------------------- preferences / state
    def _save_settings(self) -> None:
        try:
            config.save({
                "suffix": self.suffix.get(),
                "subfolder": bool(self.subfolder.get()),
                "strip_icc": bool(self.strip_icc.get()),
                "keep_attachments": bool(self.keep_attachments.get()),
                "remove_scripts": bool(self.remove_scripts.get()),
                "topmost": bool(self.topmost.get()),
            })
        except Exception:
            pass  # never let config persistence break the app

    def _on_close(self) -> None:
        self._save_settings()
        self.root.destroy()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.choose_files())
        self.root.bind("<Control-O>", lambda _e: self.choose_files())
        self.root.bind("<Delete>", lambda _e: self._remove_selected())
        self.root.bind("<Control-r>", lambda _e: self.reclean_all())
        self.root.bind("<Control-R>", lambda _e: self.reclean_all())
        # Tree keyboard navigation
        self.tree.bind("<Up>", self._on_tree_up)
        self.tree.bind("<Down>", self._on_tree_down)
        self.tree.bind("<Control-a>", lambda _e: self._select_all())
        self.tree.bind("<Control-A>", lambda _e: self._select_all())
        self.tree.bind("<Control-c>", lambda _e: self._copy_selected_paths())
        self.tree.bind("<Control-C>", lambda _e: self._copy_selected_paths())

    def _bind_auto_save(self) -> None:
        """Save preferences immediately when any option widget changes.

        Prevents data loss if the app crashes before WM_DELETE_WINDOW fires.
        The suffix entry saves on Return or focus-out; toggles save on change.
        """
        for var in (self.subfolder, self.strip_icc, self.keep_attachments,
                    self.remove_scripts, self.topmost):
            var.trace_add("write", lambda *_a: self._save_settings())
        # Suffix: save when user presses Enter or leaves the field
        self.suffix.trace_add("write", self._on_suffix_changed)
        self._suffix_save_pending = False

    def _on_suffix_changed(self, *_args) -> None:
        """Debounce suffix saves — user may still be typing."""
        if self._suffix_save_pending:
            return
        self._suffix_save_pending = True
        self.root.after(800, self._flush_suffix_save)

    def _flush_suffix_save(self) -> None:
        self._suffix_save_pending = False
        self._save_settings()

    def _on_tree_up(self, _event) -> None:
        sel = self.tree.selection()
        if sel:
            prev = self.tree.prev(sel[0])
            if prev:
                self.tree.selection_set(prev)
                self.tree.focus(prev)
                self.tree.see(prev)
        return "break"

    def _on_tree_down(self, _event) -> None:
        sel = self.tree.selection()
        if sel:
            nxt = self.tree.next(sel[0])
            if nxt:
                self.tree.selection_set(nxt)
                self.tree.focus(nxt)
                self.tree.see(nxt)
        return "break"

    def _select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def _copy_selected_paths(self) -> None:
        paths = []
        for iid in self.tree.selection():
            item = self._item_for_iid(iid)
            if item:
                out = item.get("out")
                if out:
                    paths.append(out)
        if paths:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(paths))

    def _update_status(self) -> None:
        counts = {"ok": 0, "clean": 0, "skipped": 0, "error": 0}
        pending = 0
        for i in self.items:
            if i["status"] in ("pending", "working"):
                pending += 1
            elif i["status"] in counts:
                counts[i["status"]] += 1
        if pending:
            done = counts["ok"] + counts["clean"] + counts["skipped"] + counts["error"]
            self.status_label.configure(
                text=f"\u231b {pending} in progress, {done} done\u2026")
        elif self.items:
            saved_part = ""
            if self._bytes_saved > 0:
                saved_part = f" \u00b7 {_fmt_bytes(self._bytes_saved)} metadata saved"
            self.status_label.configure(
                text=f"{counts['ok']} cleaned \u00b7 {counts['clean']} already "
                     f"clean \u00b7 {counts['error']} failed{saved_part}")
        else:
            self.status_label.configure(text="")

    # ----------------------------------------------------- results actions
    def _item_for_iid(self, iid) -> dict | None:
        return next((i for i in self.items if i["iid"] == iid), None)

    def _selected_item(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._item_for_iid(sel[0])

    def _on_tree_double_click(self, _event) -> None:
        item = self._selected_item()
        if item:
            if item["status"] == "error" and item.get("details"):
                messagebox.showerror(APP_NAME,
                    f"Failed to clean:\n{os.path.basename(item['path'])}\n\n"
                    f"Error: {item['details']}")
            else:
                self._open_item(item)

    def _on_tree_menu(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        item = self._selected_item()
        if item is None:
            return
        # grey out "open" for items with no output
        self._menu.entryconfigure(
            0, state="normal" if (item.get("out") and
                                  os.path.isfile(item["out"])) else "disabled")
        self._menu.entryconfigure(
            1, state="normal")
        self._menu.entryconfigure(
            2, state="normal" if item.get("out") else "disabled")
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _menu_act(self, action: str) -> None:
        item = self._selected_item()
        if item is None:
            return
        if action == "open":
            self._open_item(item)
        elif action == "open_orig":
            open_folder(item["path"])
        elif action == "reveal":
            out = item.get("out")
            if out:
                if sys.platform.startswith("win"):
                    subprocess.Popen(
                        ["explorer", "/select,", os.path.normpath(out)])
                else:
                    open_folder(os.path.dirname(out))
        elif action == "copy":
            out = item.get("out")
            if out:
                self.root.clipboard_clear()
                self.root.clipboard_append(out)
        elif action == "retry":
            self._retry_item(item)
        elif action == "remove":
            self.remove_item(item)

    def _open_item(self, item: dict) -> None:
        out = item.get("out")
        if out and os.path.isfile(out):
            open_folder(out)
        else:
            open_folder(os.path.dirname(item["path"]))

    def _remove_selected(self) -> None:
        item = self._selected_item()
        if item:
            self.remove_item(item)

    def remove_item(self, item: dict) -> None:
        if item["iid"] is not None and self.tree.exists(item["iid"]):
            self.tree.delete(item["iid"])
        if item in self.items:
            self.items.remove(item)
        if item.get("_counted") and self.progress["value"] > 0:
            self.progress.configure(value=self.progress["value"] - 1)
        self._update_banner()
        self._update_status()

    def _retry_item(self, item: dict) -> None:
        if item["status"] in ("pending", "working"):
            return
        item["status"] = "pending"
        item["details"] = ""
        item["out"] = ""
        item["_counted"] = False
        if item["iid"] is not None and self.tree.exists(item["iid"]):
            try:
                size_str = _fmt_bytes(os.path.getsize(item["path"]))
            except OSError:
                size_str = "\u2014"
            self.tree.item(item["iid"], values=(
                os.path.basename(item["path"]), size_str, "queued\u2026", ""),
                tags=())
        self.process_all()

    # --------------------------------------------------------- drag source
    def _drag_init(self, _event):
        """Provide the cleaned file(s) when the user drags rows out.

        Returns the tkdnd (actions, types, data) tuple.  Only files that
        were actually cleaned are draggable.
        """
        if not HAS_DND:
            return (COPY, DND_FILES, "")
        paths = []
        for iid in self.tree.selection():
            item = self._item_for_iid(iid)
            out = item.get("out") if item else ""
            if out and os.path.isfile(out):
                paths.append(out)
        if not paths:
            return (COPY, DND_FILES, "")
        return (COPY, DND_FILES, paths[0] if len(paths) == 1
                else tuple(paths))

    # ------------------------------------------------------------- report
    def save_report(self) -> None:
        if not self.items:
            messagebox.showinfo(APP_NAME, "Nothing to report yet.\n"
                                "Drop some files in first.")
            return
        default_name = datetime.now().strftime(
            f"{APP_NAME}-report-%Y%m%d-%H%M%S.txt")
        path = filedialog.asksaveasfilename(
            title="Save cleaning report",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text file", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_report_text(self.items, APP_VERSION))
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not save the report:\n{e}")
            return
        messagebox.showinfo(
            APP_NAME, f"Report saved to:\n{path}")

    def show_about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Privacy-first drop box: drag images or documents in, get a "
            "metadata-free copy back.\n\n"
            "Removes: EXIF & GPS location, camera/device details, author "
            "info, timestamps, document properties, edit-session IDs, "
            "embedded files, macros & scripts, and PDF document IDs.\n\n"
            "100% offline — nothing is ever uploaded.\n"
            "Your original files are never modified.")


def main() -> None:
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    try:
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "icon.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    PrivacyDropApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
