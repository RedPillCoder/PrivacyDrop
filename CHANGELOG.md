# Changelog

All notable changes to PrivacyDrop are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — 2026-08-28

### Added
- **Drag-out to Explorer** — drag a cleaned row straight back out to drop the
  clean copy anywhere, plus double-click to open and right-click context menu
  (Open / Show in folder / Copy path / Retry / Remove from list).
- **Persistent settings** — suffix, subfolder, privacy options, and "always on
  top" now remember themselves between launches. Stored locally at
  `%APPDATA%\PrivacyDrop\config.json` (or `~/.privacydrop.json` elsewhere).
  The config loader sanitises hostile / malformed files (bad types, path
  traversal characters in the suffix, oversized values, unknown keys all
  rejected safely).
- **Progress bar** — determinate progress with live counts ("3 cleaned · 1
  already clean · 0 failed").
- **Save Report…** — opt-in plain-text receipt of the session: what was
  removed per file plus bytes saved (e.g. 941 B → 709 B, −25%). Nothing is
  logged unless you click the button.
- **About dialog** — version, supported formats, and privacy guarantees one
  click away.
- **Keyboard shortcuts** — `Ctrl+O` add files, `Delete` remove selected row.

### Changed
- JPEG lossless cleaning now also validates the SOI signature and rejects
  garbage inputs with a clear error (instead of silently copying them).
- File dialog patterns updated to include `.jfif` and `.jpe` JPEG aliases.

### Fixed
- `_counted` key is consistently a `dict` key (never `getattr`), avoiding
  crashes when an item is removed mid-session.

### Security
- Config loader hardens against hostile files: suffix is filename-sanitised
  (rejects `/ \ : * ? " < > |`), all values type-coerced to defaults, unknown
  keys ignored, path is never logged or transmitted.

---

## [1.0.0] — 2026-08

### Added
- Privacy-first drag & drop box for Windows.
- **Lossless** metadata removal for JPEG, PNG, WebP (byte-level segment/chunk
  stripping — no recompression).
- **Re-encode** cleaning for TIFF, GIF, BMP, HEIC (quality-preserving save).
- **PDF** sanitisation: document info, XMP, embedded file attachments,
  JavaScript / launch actions / XFA forms, `/PieceInfo` editing history, and
  document `/ID` fingerprint reset.
- **Office** (DOCX / XLSX / PPTX) sanitisation: core + app + custom
  properties, VBA macro projects, edit-session IDs (`w:rsid`), VBA references
  in `[Content_Types].xml` / `.rels`, thumbnail timestamps zeroed, and EXIF
  scrubbed from every embedded image.
- GPS location transparency — when a photo carries coordinates, PrivacyDrop
  shows the exact position it removed (e.g. *GPS location (31°57′S, 115°51′E)*).
- Hardened against hostile inputs: decompression-bomb (zip-bomb) defence,
  zip-slip / path-traversal / drive-letter entry rejection, input size limits,
  encrypted-archive handling, and no XML parsing of untrusted document
  metadata (immune to XXE / billion-laughs).
- Original files are **never** modified — only copies are written, and they
  are written atomically (temp file + rename) so a crash leaves no stray file.
- 100% offline — no network code, no telemetry, no accounts.

[1.1.0]: https://github.com/privacypdrop/privacypdrop/releases/tag/v1.1.0
[1.0.0]: https://github.com/privacypdrop/privacypdrop/releases/tag/v1.0.0
