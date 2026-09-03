"""
PrivacyDrop — metadata sanitization engine (security-hardened).

Removes hidden metadata, location data, device details, author information
and other embedded identifiers from images and documents, while preserving
the original content and quality as much as possible.

Design principles
-----------------
* The ORIGINAL file is never modified. A sanitized copy is always written.
* Output is written atomically (temp file + rename): a crash mid-write can
  never leave a half-written "_clean" file that looks valid.
* JPEG, PNG and WebP are cleaned at the byte level (no re-compression), so
  image quality is preserved losslessly.
* Untrusted input is treated as hostile:
    - input size limits and decompression-bomb protection on Office zips,
    - zip-slip / path-traversal / absolute-path / drive-letter entry defence,
    - no XML parsing of untrusted document metadata (regex scan + template
      replacement only — immune to XXE / billion-laughs),
    - executable content is stripped by default (PDF JavaScript & launch
      actions, XFA forms, Office VBA macro projects).

This module is pure logic — no GUI — so it can be used as a CLI too:

    python scrubber.py photo.jpg report.pdf --out cleaned/
"""

from __future__ import annotations

import contextlib
import os
import re
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field

try:
    from PIL import Image
    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False

try:
    import pikepdf
    HAS_PIKEPDF = True
except Exception:
    HAS_PIKEPDF = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except Exception:
    HAS_HEIF = False


# --------------------------------------------------------------------------
# Supported formats & resource limits
# --------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".jfif", ".jpe",
              ".png", ".tif", ".tiff", ".webp",
              ".gif", ".bmp", ".heic", ".heif", ".avif",
              ".svg"}
DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx",
            ".odt", ".ods", ".odp"}
SUPPORTED_EXTS = IMAGE_EXTS | DOC_EXTS

# All extensions that are really JPEG under the hood.
JPEG_EXTS = {".jpg", ".jpeg", ".jfif", ".jpe"}

# Resource limits (defend against crafted / hostile inputs).
MAX_INPUT_BYTES = 512 * 1024 * 1024          # 512 MiB per file
MAX_ZIP_ENTRIES = 20_000
MAX_ZIP_ENTRY_UNCOMPRESSED = 512 * 1024 * 1024   # per entry, 512 MiB
MAX_ZIP_TOTAL_UNCOMPRESSED = 1 * 1024 * 1024 * 1024  # 1 GiB total


class ScrubError(Exception):
    """Raised for inputs that cannot be processed safely."""


# --------------------------------------------------------------------------
# Result reporting
# --------------------------------------------------------------------------

@dataclass
class Report:
    """Outcome of sanitizing a single file."""
    src: str = ""
    dst: str = ""
    status: str = "ok"          # ok | clean | skipped | error
    removed: list = field(default_factory=list)   # human-readable items removed
    notes: list = field(default_factory=list)     # extra info / warnings
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "clean")

    def summary(self) -> str:
        if self.status == "ok":
            return ", ".join(self.removed) or "metadata removed"
        if self.status == "clean":
            return "no metadata found"
        if self.status == "skipped":
            return "unsupported file type"
        return self.error or "failed"


@dataclass
class Options:
    """Sanitization options."""
    strip_icc: bool = False              # also remove color profiles (ICC)
    remove_pdf_attachments: bool = True  # drop files embedded in PDFs
    remove_scripts: bool = True          # strip JS/launch actions & macros
    suffix: str = "_clean"               # appended to output file name


def supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def image_ext(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


# --------------------------------------------------------------------------
# Atomic, safe output writing
# --------------------------------------------------------------------------

def _atomic_write(path: str, writer) -> None:
    """Write ``path`` via a temp file in the same directory, then rename.

    Guarantees readers never observe a partially-written file, and a failure
    leaves no stray output.  ``writer(tmp_path)`` must write the content.
    
    Security: validates that the destination directory exists and is not a
    symlink before writing, preventing symlink attacks on output files.
    """
    d = os.path.dirname(path) or "."
    
    # Validate destination directory is real (not a symlink)
    if os.path.islink(d):
        raise ScrubError(f"output directory is a symlink: {d}")
    
    os.makedirs(d, exist_ok=True)
    
    # Re-check after makedirs (TOCTOU protection)
    if os.path.islink(d):
        raise ScrubError(f"output directory became a symlink: {d}")
    
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".privacydrop-", suffix=".part")
    try:
        os.close(fd)
        writer(tmp)
        os.replace(tmp, path)            # atomic on the same filesystem
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _write(data: bytes, dst: str) -> None:
    _atomic_write(dst, lambda p: _write_bytes(p, data))


def _read_limited(path: str) -> bytes:
    """Read a file with an explicit size cap (refuse oversized inputs)."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        # Don't leak full path in error message
        raise ScrubError(f"cannot read file: {os.path.basename(path)}")
    if size > MAX_INPUT_BYTES:
        raise ScrubError(
            f"file too large to process safely "
            f"(>{MAX_INPUT_BYTES // (1024 * 1024)} MB)")
    with open(path, "rb") as f:
        data = f.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ScrubError("file too large to process safely")
    return data


# --------------------------------------------------------------------------
# EXIF GPS extraction (privacy transparency: tell the user what we found)
# --------------------------------------------------------------------------

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def _gps_from_exif(blob: bytes):
    """Return a human-readable GPS position from an EXIF blob, or None.

    ``blob`` may carry the leading ``Exif\\x00\\x00`` header (JPEG APP1) or be
    raw TIFF (PNG eXIf).  Parsing is bounds-checked and never raises; it only
    ever *reads* the bytes we control, so it is safe on hostile input.
    """
    data = blob[6:] if blob[:6] == b"Exif\x00\x00" else blob
    if len(data) < 8:
        return None
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        return None
    if struct.unpack(endian + "H", data[2:4])[0] != 42:
        return None
    ifd0 = struct.unpack(endian + "I", data[4:8])[0]
    if ifd0 + 2 > len(data):
        return None

    gps_off = _find_ifd_tag(data, ifd0, endian, 0x8825)
    if gps_off is None:
        return None
    lat = _read_ifd_rationals(data, gps_off, endian, 0x0002, 3)
    lon = _read_ifd_rationals(data, gps_off, endian, 0x0004, 3)
    if lat is None or lon is None:
        return None
    lat_ref = _read_ifd_ascii(data, gps_off, endian, 0x0001)
    lon_ref = _read_ifd_ascii(data, gps_off, endian, 0x0003)
    return f"{_dms(lat)}{lat_ref or ''}, {_dms(lon)}{lon_ref or ''}"


def _find_ifd_tag(data, ifd_off, endian, want):
    if ifd_off + 2 > len(data):
        return None
    n = struct.unpack(endian + "H", data[ifd_off:ifd_off + 2])[0]
    for i in range(n):
        base = ifd_off + 2 + i * 12
        if base + 12 > len(data):
            return None
        tag, typ, cnt = struct.unpack(endian + "HHI", data[base:base + 8])
        if tag == want and typ == 4 and cnt == 1:
            return struct.unpack(endian + "I", data[base + 8:base + 12])[0]
    return None


def _read_ifd_entry(data, ifd_off, endian, want, typ, cnt):
    if ifd_off + 2 > len(data):
        return None
    n = struct.unpack(endian + "H", data[ifd_off:ifd_off + 2])[0]
    for i in range(n):
        base = ifd_off + 2 + i * 12
        if base + 12 > len(data):
            return None
        tag, t, c = struct.unpack(endian + "HHI", data[base:base + 8])
        if tag != want:
            continue
        size = _TYPE_SIZE.get(t)
        if size is None:
            return None
        total = size * c
        if total <= 4:
            return data[base + 8:base + 8 + total]
        off = struct.unpack(endian + "I", data[base + 8:base + 12])[0]
        if off + total > len(data):
            return None
        return data[off:off + total]
    return None


def _read_ifd_rationals(data, ifd_off, endian, want, cnt):
    raw = _read_ifd_entry(data, ifd_off, endian, want, 5, cnt)
    if raw is None or len(raw) < cnt * 8:
        return None
    out = []
    for i in range(cnt):
        num, den = struct.unpack(endian + "II", raw[i * 8:i * 8 + 8])
        if den == 0:
            return None
        out.append(num / den)
    return out


def _read_ifd_ascii(data, ifd_off, endian, want):
    raw = _read_ifd_entry(data, ifd_off, endian, want, 2, 2)
    if not raw:
        return ""
    return raw.rstrip(b"\x00").decode("ascii", "ignore")


def _dms(r) -> str:
    d, m, s = int(r[0]), int(r[1]), r[2]
    return f"{d}\u00b0{m}'{s:.0f}\""


# EXIF tags that identify a device / person / location (vs. structural tags
# such as width & height).  Used to report metadata found in TIFF/HEIC.
_IDENTITY_EXIF_TAGS = (271, 272, 305, 306, 315, 33432, 34855, 36867, 36868,
                       42036, 42037, 37377, 37378, 37380, 37382, 37383, 37385)


def _gps_str_from_ifd(gps: dict):
    """Format a Pillow GPS-IFD dict as a human-readable position, or None."""
    try:
        lat, lon = gps.get(2), gps.get(4)
        if not lat or not lon:
            return None
        la = [float(x) for x in lat]
        lo = [float(x) for x in lon]
        lat_ref = str(gps.get(1, "")).strip()
        lon_ref = str(gps.get(3, "")).strip()
        return f"{_dms(la)}{lat_ref}, {_dms(lo)}{lon_ref}"
    except Exception:
        return None


# --------------------------------------------------------------------------
# JPEG — lossless metadata segment removal (no re-compression)
# --------------------------------------------------------------------------

def strip_jpeg_bytes(data: bytes, keep_icc: bool = True):
    """Remove metadata APP/COM segments from JPEG bytes losslessly.

    Returns (new_bytes, removed_items).  Keeps JFIF (APP0) and the Adobe
    color-transform marker (APP14) because they describe how to decode the
    image, not who made it.
    """
    removed: list = []
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return data, removed

    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    n_exif = n_xmp = n_icc = n_com = n_photoshop = n_other = 0
    gps = None

    while i < n - 1:
        if data[i] != 0xFF:
            j = data.find(b"\xff\xd9", i)
            if j == -1:
                out += data[i:]
                break
            out += data[i:j + 2]
            break

        b = data[i + 1]
        if b == 0x00 or b == 0xFF:      # fill / padding byte
            i += 1
            continue
        if b == 0xD8:                    # SOI (shouldn't appear mid-file)
            out += b"\xff\xd8"; i += 2; continue
        if b == 0xD9:                    # EOI
            out += b"\xff\xd9"; break
        if b == 0x01 or 0xD0 <= b <= 0xD7:   # TEM / RSTn (no length)
            out += data[i:i + 2]; i += 2; continue
        if b == 0xDA:                    # SOS: header + raw entropy data
            if i + 4 > n:
                out += data[i:]; break
            seglen = (data[i + 2] << 8) | data[i + 3]
            out += data[i:i + 2 + seglen]
            i += 2 + seglen
            j = data.find(b"\xff\xd9", i)
            if j == -1:
                out += data[i:]; break
            out += data[i:j + 2]; break

        if i + 4 > n:
            out += data[i:]; break
        seglen = (data[i + 2] << 8) | data[i + 3]
        if seglen < 2 or i + 2 + seglen > n:
            out += data[i:]; break
        seg = data[i:i + 2 + seglen]
        payload = seg[4:]

        if b == 0xE0:                    # APP0 — keep only JFIF
            if payload.startswith(b"JFIF\x00"):
                out += seg
            else:
                n_other += 1
        elif b == 0xE1:                  # APP1 — EXIF / XMP
            if payload.startswith(b"Exif\x00\x00"):
                n_exif += 1
                if gps is None:
                    gps = _gps_from_exif(payload)
            elif payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
                n_xmp += 1
            else:
                n_other += 1
        elif b == 0xE2:                  # APP2 — ICC (keep?) or MPF etc.
            if payload.startswith(b"ICC_PROFILE\x00"):
                if keep_icc:
                    out += seg
                else:
                    n_icc += 1
            else:
                n_other += 1
        elif b == 0xEE:                  # APP14 Adobe color transform — keep
            out += seg
        elif 0xC0 <= b <= 0xCF or b in (0xDB, 0xDD, 0xDC, 0xDE, 0xDF):
            out += seg                    # structural: SOF/DHT/JPG/DAC/DQT/DRI/DNL
        elif b == 0xFE:                  # COM comment
            n_com += 1
        elif b == 0xED:                  # APP13 — Photoshop IRB (layers, paths, IPTC-NAA)
            n_photoshop += 1
        else:                            # APP3–APP15 (IPTC, other…)
            n_other += 1
        i += 2 + seglen

    if n_exif:
        removed.append("EXIF metadata")
    if gps:
        removed.append(f"GPS location ({gps})")
    if n_xmp:
        removed.append("XMP metadata")
    if n_icc:
        removed.append("ICC color profile")
    if n_com:
        removed.append("embedded comment")
    if n_photoshop:
        removed.append("Photoshop metadata (layers/paths/IPTC)")
    if n_other:
        removed.append(f"{n_other} other embedded block(s)")
    return bytes(out), removed


# --------------------------------------------------------------------------
# PNG — lossless ancillary-chunk removal
# --------------------------------------------------------------------------

# Ancillary PNG chunks that affect rendering and contain no identity info.
PNG_KEEP_ANCILLARY = {b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"bKGD",
                      b"hIST", b"sPLT", b"sBIT", b"pHYs"}

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def strip_png_bytes(data: bytes, keep_icc: bool = True):
    removed: list = []
    if data[:8] != PNG_SIG:
        return data, removed

    out = bytearray(PNG_SIG)
    i, n = 8, len(data)
    n_text = n_exif = n_time = n_icc = n_other = 0
    gps = None

    while i + 8 <= n:
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        cend = i + 8 + length
        if cend + 4 > n:
            out += data[i:]
            break
        chunk = data[i:cend + 4]
        i = cend + 4

        if ctype == b"IEND":
            out += chunk
            break

        keep = True
        if ctype == b"iCCP":
            if not keep_icc:
                keep = False
                n_icc += 1
        elif ctype in (b"tEXt", b"zTXt", b"iTXt"):
            keep = False
            n_text += 1
        elif ctype == b"eXIf":
            keep = False
            n_exif += 1
            if gps is None:
                gps = _gps_from_exif(chunk[8:-4])   # chunk = len+type+data+crc
        elif ctype == b"tIME":
            keep = False
            n_time += 1
        elif chr(ctype[0]).islower() and ctype not in PNG_KEEP_ANCILLARY:
            keep = False
            n_other += 1

        if keep:
            out += chunk

    if n_text:
        removed.append(f"{n_text} text chunk(s)")
    if n_exif:
        removed.append("EXIF metadata")
    if gps:
        removed.append(f"GPS location ({gps})")
    if n_time:
        removed.append("modification timestamp")
    if n_icc:
        removed.append("ICC color profile")
    if n_other:
        removed.append(f"{n_other} unknown chunk(s)")
    return bytes(out), removed


# --------------------------------------------------------------------------
# WebP — lossless RIFF-chunk removal
# --------------------------------------------------------------------------

def strip_webp_bytes(data: bytes, keep_icc: bool = True):
    """Remove EXIF/XMP/ICC RIFF chunks from a WebP losslessly.

    Two passes: first work out which chunks to drop, then emit the file with
    the RIFF size and VP8X flag bits corrected.
    """
    removed: list = []
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return data, removed

    chunks: list = []
    i, n = 12, len(data)
    while i + 8 <= n:
        fourcc = data[i:i + 4]
        size = struct.unpack("<I", data[i + 4:i + 8])[0]
        if i + 8 + size > n:
            break
        chunks.append((fourcc, data[i + 8:i + 8 + size]))
        i += 8 + size
        if size % 2 == 1:
            i += 1               # skip RIFF padding byte

    drop = {c[0] for c in chunks if c[0] in (b"EXIF", b"XMP ")}
    has_exif = b"EXIF" in drop
    has_xmp = b"XMP " in drop
    has_icc = any(c[0] == b"ICCP" for c in chunks)
    if not keep_icc and has_icc:
        drop.add(b"ICCP")

    body = bytearray()
    for fourcc, payload in chunks:
        if fourcc in drop:
            continue
        if fourcc == b"VP8X" and len(payload) >= 1:
            flags = payload[0]
            if has_exif:
                flags &= ~0x08
            if has_xmp:
                flags &= ~0x10
            if not keep_icc and has_icc:
                flags &= ~0x02
            payload = bytes([flags]) + payload[1:]
        body += fourcc + struct.pack("<I", len(payload)) + payload
        if len(payload) % 2 == 1:
            body += b"\x00"

    out = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body

    if has_exif:
        removed.append("EXIF metadata")
    if has_xmp:
        removed.append("XMP metadata")
    if not keep_icc and has_icc:
        removed.append("ICC color profile")
    return out, removed


# --------------------------------------------------------------------------
# SVG — text-level metadata, comment, and script removal
# --------------------------------------------------------------------------

# SVG metadata, comments, and scripts carry editor identity, timestamps,
# project info, and embedded JavaScript.  Regex-based removal (no XML parsing
# of untrusted content) so we stay immune to XXE and entity-expansion attacks.

# Dublin Core + creator/publisher/identifier metadata
_SVG_META_RE = re.compile(
    rb'<metadata[^>]*>.*?</metadata>', re.DOTALL)
# XML comments (<!-- ... -->)
_SVG_COMMENT_RE = re.compile(rb'<!--.*?-->', re.DOTALL)
# Script blocks
_SVG_SCRIPT_RE = re.compile(rb'<script[^>]*>.*?</script>', re.DOTALL)
# Editor-specific metadata (Inkscape, Illustrator, etc.)
_SVG_EDITOR_RE = re.compile(
    rb'<(?:inkscape|sodipodi|illustrator|adobe|dc|cc)[^>]*>.*?</(?:inkscape|sodipodi|illustrator|adobe|dc|cc)[^>]*>',
    re.DOTALL)
# Embedded raster images (data: URIs) — these can carry their own EXIF/XMP
_SVG_EMBEDDED_IMAGE_RE = re.compile(
    rb'<image[^>]*(?:xlink:href|href)\s*=\s*"data:image/[^"]*"[^>]*>')
# XML processing instructions (<?xml ... ?>, <?xml-stylesheet ... ?>)
_SVG_PI_RE = re.compile(rb'<\?[^>]*\?>')


def strip_svg_bytes(data: bytes, keep_icc: bool = True):
    """Remove metadata, comments, scripts, and editor info from SVG.

    SVG is plain text, so processing is lossless at the text level (no
    re-encoding).  Returns (cleaned_bytes, removed_items).
    """
    removed: list = []
    out = data

    # Metadata block
    if _SVG_META_RE.search(out):
        out = _SVG_META_RE.sub(b"", out)
        removed.append("metadata block")

    # Comments
    n_comments = len(_SVG_COMMENT_RE.findall(out))
    if n_comments:
        out = _SVG_COMMENT_RE.sub(b"", out)
        removed.append(f"{n_comments} comment(s)")

    # Scripts
    if _SVG_SCRIPT_RE.search(out):
        out = _SVG_SCRIPT_RE.sub(b"", out)
        removed.append("script block(s)")

    # Editor-specific metadata
    n_editor = len(_SVG_EDITOR_RE.findall(out))
    if n_editor:
        out = _SVG_EDITOR_RE.sub(b"", out)
        removed.append(f"{n_editor} editor metadata block(s)")

    # XML processing instructions (keep only <?xml ... ?> declaration)
    n_pi = len(_SVG_PI_RE.findall(out))
    if n_pi > 1:  # keep the XML declaration if present
        # Remove all PI except the first if it's an XML declaration
        pis = list(_SVG_PI_RE.finditer(out))
        for pi in (pis[1:] if pis and pis[0].group().startswith(b'<?xml') else pis):
            out = out[:pi.start()] + out[pi.end():]
        removed.append(f"{n_pi - (1 if pis and pis[0].group().startswith(b'<?xml') else 0)} processing instruction(s)")

    # Embedded raster images (data: URIs) can carry their own EXIF/XMP
    # metadata.  We can't reliably scrub metadata from embedded images without
    # re-encoding, so we report their presence for transparency.
    n_embedded = len(_SVG_EMBEDDED_IMAGE_RE.findall(out))
    if n_embedded:
        removed.append(f"{n_embedded} embedded image(s) present (metadata not scrubbed)")

    return out, removed


# --------------------------------------------------------------------------
# Generic re-encode via Pillow (used for TIFF, GIF, BMP, HEIC, AVIF)
# --------------------------------------------------------------------------

def _jpeg_supports_keep() -> bool:
    if not HAS_PIL:
        return False
    try:
        import io as _io
        im = Image.new("RGB", (8, 8))
        buf = _io.BytesIO()
        im.save(buf, "JPEG", quality="keep", subsampling="keep")
        return True
    except Exception:
        return False


JPEG_KEEP = _jpeg_supports_keep()


def _reencode_image(src: str, dst: str, opts: Options, fmt: str) -> Report:
    rep = Report(src=src, dst=dst)
    if not HAS_PIL:
        rep.status = "error"
        rep.error = "Pillow is not installed"
        return rep

    try:
        with Image.open(src) as img:
            info = dict(img.info)
            frames = getattr(img, "n_frames", 1)
            save_kwargs = {}

            # Detect identity metadata for reporting.  Some formats expose
            # EXIF as ``info['exif']`` bytes (HEIC); others (TIFF) store it as
            # native tags reachable via getexif()/get_ifd().
            exif_detected = "exif" in info
            gps_str = None
            if exif_detected and isinstance(info["exif"], bytes):
                gps_str = _gps_from_exif(info["exif"])
            if not exif_detected:
                try:
                    ex = img.getexif()
                    if any(t in ex for t in _IDENTITY_EXIF_TAGS):
                        exif_detected = True
                    gps_ifd = ex.get_ifd(0x8825) if ex else {}
                    if gps_ifd:
                        gps_str = _gps_str_from_ifd(dict(gps_ifd))
                except Exception:
                    pass

            if "icc_profile" in info and not opts.strip_icc:
                save_kwargs["icc_profile"] = info["icc_profile"]

            if fmt == "JPEG":
                save_kwargs["optimize"] = False
                if JPEG_KEEP:
                    save_kwargs["quality"] = "keep"
                    save_kwargs["subsampling"] = "keep"
                else:
                    save_kwargs["quality"] = 95
            elif fmt == "PNG":
                save_kwargs["compress_level"] = 6

            frame_list = []
            for f in range(frames):
                img.seek(f)
                fr = img.copy()
                # Strip embedded metadata carried in the frame's info dict
                # (GIF comments/XMP extensions, HEIC EXIF, etc.) so the
                # encoder cannot re-embed it.  Keep only rendering-relevant
                # timing data for animations.
                cleaned = dict(fr.info)
                for k in ("comment", "extension", "exif", "xmp", "author",
                          "description", "software", "metadata",
                          "thumbnails"):
                    cleaned.pop(k, None)
                fr.info = cleaned
                frame_list.append(fr)

            def _save(tmp_path: str) -> None:
                if frames == 1:
                    frame_list[0].save(tmp_path, format=fmt, **save_kwargs)
                else:
                    frame_list[0].save(tmp_path, format=fmt, save_all=True,
                                       append_images=frame_list[1:],
                                       **save_kwargs)

            _atomic_write(dst, _save)

        if exif_detected:
            rep.removed.append("EXIF metadata")
        if gps_str:
            rep.removed.append(f"GPS location ({gps_str})")
        if "xmp" in info:
            rep.removed.append("XMP metadata")
        if "comment" in info:
            rep.removed.append("embedded comment")
        if "icc_profile" in info and opts.strip_icc:
            rep.removed.append("ICC color profile")
        rep.status = "ok" if rep.removed else "clean"
        return rep
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception:
        rep.status = "error"
        rep.error = "could not process image"
        return rep


# --------------------------------------------------------------------------
# Image dispatcher
# --------------------------------------------------------------------------

def _valid_image(data: bytes) -> bool:
    """Cheap integrity check: can Pillow decode (verify) these bytes?"""
    if not HAS_PIL:
        return True
    try:
        import io as _io
        with Image.open(_io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


def _finalize_lossless(src: str, dst: str, raw: bytes, out: bytes,
                       removed: list, kind: str) -> Report:
    """Validate and write a losslessly-cleaned image, reporting the outcome."""
    final = raw if not removed else out
    if not _valid_image(final):
        return Report(src=src, dst=dst, status="error",
                      error=f"source {kind} appears corrupt — nothing written")
    _write(final, dst)
    if removed:
        return Report(src=src, dst=dst, status="ok", removed=removed)
    return Report(src=src, dst=dst, status="clean",
                  notes=["already free of metadata"])


def sanitize_image(src: str, dst: str, opts: Options) -> Report:
    ext = os.path.splitext(src)[1].lower()
    try:
        raw = _read_limited(src)
    except ScrubError as e:
        return Report(src=src, dst=dst, status="error", error=str(e))

    # Lossless paths — validate the file signature first so that empty or
    # garbage files are reported as errors instead of being copied silently.
    if ext in JPEG_EXTS:
        if raw[:2] != b"\xff\xd8":
            return Report(src=src, dst=dst, status="error",
                          error="not a valid JPEG file")
        out, removed = strip_jpeg_bytes(raw, keep_icc=not opts.strip_icc)
        return _finalize_lossless(src, dst, raw, out, removed, "JPEG")

    if ext == ".png":
        if raw[:8] != PNG_SIG:
            return Report(src=src, dst=dst, status="error",
                          error="not a valid PNG file")
        out, removed = strip_png_bytes(raw, keep_icc=not opts.strip_icc)
        return _finalize_lossless(src, dst, raw, out, removed, "PNG")

    if ext == ".webp":
        if raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
            return Report(src=src, dst=dst, status="error",
                          error="not a valid WebP file")
        out, removed = strip_webp_bytes(raw, keep_icc=not opts.strip_icc)
        return _finalize_lossless(src, dst, raw, out, removed, "WebP")

    if ext == ".svg":
        # SVG is text-based; validate it looks like an SVG file
        if b"<svg" not in raw[:1024].lower():
            return Report(src=src, dst=dst, status="error",
                          error="not a valid SVG file")
        out, removed = strip_svg_bytes(raw, keep_icc=not opts.strip_icc)
        # For SVG, we don't validate via _valid_image (Pillow can't handle
        # all SVGs), so write directly
        final = raw if not removed else out
        _write(final, dst)
        if removed:
            return Report(src=src, dst=dst, status="ok", removed=removed)
        return Report(src=src, dst=dst, status="clean",
                      notes=["no metadata found"])

    # Re-encode paths
    if ext in (".heic", ".heif") and not HAS_HEIF:
        return Report(src=src, dst=dst, status="skipped",
                      error="HEIC needs the optional 'pillow-heif' package")

    fmt = {".tif": "TIFF", ".tiff": "TIFF", ".gif": "GIF", ".bmp": "BMP",
           ".heic": "HEIF", ".heif": "HEIF",
           ".avif": "AVIF"}.get(ext)
    if fmt is None:
        return Report(src=src, dst=dst, status="skipped",
                      error="unsupported image type")
    return _reencode_image(src, dst, opts, fmt)


# --------------------------------------------------------------------------
# PDF — metadata + embedded scripts/attachments removal
# --------------------------------------------------------------------------

def _is_js_or_launch(v) -> bool:
    """True if ``v`` is an action dictionary that runs code or a program."""
    try:
        return str(v["/S"]) in ("/JavaScript", "/Launch")
    except Exception:
        return False


def _strip_pdf_unsafe(pdf, remove_scripts: bool = True) -> dict:
    """Remove executable and identity-leaking objects from a PDF.

    Mutates ``pdf`` in place (pikepdf live objects) and returns counts by
    category:
      * scripts  — JavaScript, launch actions, XFA forms
      * metadata — XMP (/Metadata anywhere) and editing history (/PieceInfo)
      * docid    — the trailer /ID document fingerprint

    Non-executable actions (e.g. GoTo links) and visible content (annotations,
    form fields) are kept.  ``remove_scripts=False`` keeps scripts but still
    removes secondary metadata and resets the document ID.
    """
    counts = {"scripts": 0, "metadata": 0, "docid": 0}
    seen = set()

    def clean(obj, depth: int) -> None:
        if depth > 64:
            return
        if getattr(obj, "is_indirect", False):
            key = tuple(obj.objgen)
            if key in seen:
                return
            seen.add(key)
        try:
            keys = list(obj.keys())
        except Exception:
            try:
                count = len(obj)
            except Exception:
                return
            for i in range(count):
                clean(obj[i], depth + 1)
            return
        for k in keys:
            v = obj[k]
            s = str(k)
            if s == "/Metadata":        # XMP (root or page level)
                del obj[k]
                counts["metadata"] += 1
            elif s == "/PieceInfo":     # editing history (Illustrator etc.)
                del obj[k]
                counts["metadata"] += 1
            elif remove_scripts and s in ("/JS", "/JavaScript"):
                del obj[k]
                counts["scripts"] += 1
            elif s == "/AA":            # additional actions
                try:
                    for ak in list(v.keys()):
                        av = v[ak]
                        if remove_scripts and _is_js_or_launch(av):
                            del v[ak]
                            counts["scripts"] += 1
                        else:
                            clean(av, depth + 1)
                    if len(v) == 0:
                        del obj[k]
                except Exception:
                    clean(v, depth + 1)
            elif s in ("/A", "/OpenAction"):
                if remove_scripts and _is_js_or_launch(v):
                    del obj[k]
                    counts["scripts"] += 1
                else:
                    clean(v, depth + 1)
            else:
                clean(v, depth + 1)

    for obj in list(pdf.objects):
        clean(obj, 0)

    # Document-level JavaScript name tree.
    if remove_scripts:
        try:
            names = pdf.Root["/Names"]
            if "/JavaScript" in list(names.keys()):
                del names["/JavaScript"]
                counts["scripts"] += 1
        except Exception:
            pass

        # XFA (XML Forms Architecture) can carry scripts and is a known risk.
        try:
            acroform = pdf.Root["/AcroForm"]
            if "/XFA" in list(acroform.keys()):
                del acroform["/XFA"]
                counts["scripts"] += 1
        except Exception:
            pass

    # AcroForm text-field values (/V and /DV) carry personal data filled in
    # by the user (name, address, email, etc.).  Strip them whether or not
    # remove_scripts is set — form *structure* (field labels, layout) is
    # preserved; only the filled-in content is cleared.
    try:
        acroform = pdf.Root["/AcroForm"]
        fields = acroform.get("/Fields")
        if fields is not None:
            cleared = 0
            for field in fields:
                if "/V" in field:
                    del field["/V"]
                    cleared += 1
                if "/DV" in field:
                    del field["/DV"]
                    cleared += 1
                # /TU (tooltip) and /TM (mapping name) can carry form template
                # info or author guidance text — strip them too.
                if "/TU" in field:
                    del field["/TU"]
                    cleared += 1
                if "/TM" in field:
                    del field["/TM"]
                    cleared += 1
            if cleared:
                counts["form_values"] = cleared
    except Exception:
        pass

    # The trailer /ID is a stable document fingerprint (its first element
    # survives any edit).  Replace it so the sanitized copy can't be
    # correlated back to the original document.
    try:
        trailer = pdf.trailer
        if "/ID" in trailer:
            trailer["/ID"] = pikepdf.Array([
                pikepdf.String(b"\x00" * 16),
                pikepdf.String(b"\x00" * 16),
            ])
            counts["docid"] += 1
    except Exception:
        pass

    # PDF annotations can leak author information, comments, and timestamps.
    # Strip sensitive fields from all annotations while preserving the
    # annotation structure (so the document still displays correctly).
    annotation_author_count = 0
    for page in pdf.pages:
        if '/Annots' not in page:
            continue
        annots = page['/Annots']
        if not hasattr(annots, '__len__'):
            continue
        for annot in annots:
            if not hasattr(annot, 'keys'):
                continue
            # Remove author identity
            for key in ['/Author', '/T', '/RC', '/NM', '/CreationDate', '/M', '/Subj']:
                if key in annot:
                    del annot[key]
                    annotation_author_count += 1
    if annotation_author_count:
        counts["annotation_authors"] = annotation_author_count

    # PDF incremental updates: ensure we're not leaving old versions with
    # metadata in the file.  pikepdf's save() with linearize=False and
    # full=True creates a clean single-version PDF, but let's be explicit.
    # The save() call below uses full=True by default via pikepdf.

    # PDF outline/bookmark items can carry author metadata (/NM unique ID,
    # /T title that may identify the bookmark creator in PDF 2.0).
    # Strip /NM and /T from outline items while preserving the tree structure.
    outline_counts = {"n": 0}
    if "/Outlines" in pdf.Root:
        outlines = pdf.Root["/Outlines"]
        # Strip the root outlines dict itself (unusual but possible)
        _strip_outline_authors(outlines, outline_counts)
        # Walk the item tree
        if "/First" in outlines:
            _strip_outline_authors(outlines["/First"], outline_counts)
    if outline_counts["n"]:
        counts["outline_authors"] = outline_counts["n"]

    return counts


def _strip_outline_authors(item, counts: dict) -> None:
    """Recursively strip /NM from PDF outline items.

    PDF 2.0 outline items can carry /NM (unique identifier) that may be used
    to track document versions or identify the bookmark creator.  We preserve
    the tree structure and /Title (visible bookmark text) but strip /NM.
    """
    try:
        if "/NM" in item:
            del item["/NM"]
            counts["n"] += 1
    except Exception:
        pass
    # Walk the tree
    try:
        if "/First" in item:
            _strip_outline_authors(item["/First"], counts)
    except Exception:
        pass
    try:
        if "/Next" in item:
            _strip_outline_authors(item["/Next"], counts)
    except Exception:
        pass


def sanitize_pdf(src: str, dst: str, opts: Options) -> Report:
    rep = Report(src=src, dst=dst)
    if not HAS_PIKEPDF:
        rep.status = "error"
        rep.error = "pikepdf is not installed"
        return rep

    try:
        if os.path.getsize(src) > MAX_INPUT_BYTES:
            rep.status = "error"
            rep.error = (f"file too large to process safely "
                         f"(>{MAX_INPUT_BYTES // (1024 * 1024)} MB)")
            return rep
    except OSError:
        rep.status = "error"
        rep.error = "cannot read file"
        return rep

    try:
        with pikepdf.open(src) as pdf:
            removed: list = []

            # 1. Document information dictionary (Title, Author, Creator…)
            docinfo_keys = [str(k) for k in pdf.docinfo.keys()]
            for k in list(pdf.docinfo.keys()):
                del pdf.docinfo[k]
            if docinfo_keys:
                removed.append("document info (" + ", ".join(docinfo_keys) + ")")

            # 2. Embedded files / attachments
            if opts.remove_pdf_attachments:
                try:
                    names = pdf.Root.get("/Names")
                    if names is not None and "/EmbeddedFiles" in names:
                        del names["/EmbeddedFiles"]
                        removed.append("embedded file attachments")
                except Exception:
                    pass

            # 3. Executable content + secondary metadata + document ID.
            counts = _strip_pdf_unsafe(pdf, remove_scripts=opts.remove_scripts)
            if counts["scripts"]:
                removed.append(
                    f"{counts['scripts']} script/action element(s) removed")
            if counts["metadata"]:
                removed.append(
                    f"{counts['metadata']} metadata object(s) removed "
                    f"(XMP / editing history)")
            if counts["docid"]:
                removed.append("document ID (fingerprint) reset")
            if counts.get("form_values"):
                removed.append(
                    f"{counts['form_values']} form field value(s) cleared")
            if counts.get("annotation_authors"):
                removed.append(
                    f"{counts['annotation_authors']} annotation author field(s) removed")
            if counts.get("outline_authors"):
                removed.append(
                    f"{counts['outline_authors']} bookmark/outline field(s) removed")

            _atomic_write(dst, lambda p: pdf.save(p))

        rep.status = "ok" if removed else "clean"
        rep.removed = removed
        if not removed:
            rep.notes.append("no metadata found")
        return rep
    except pikepdf.PasswordError:
        rep.status = "error"
        rep.error = "PDF is password-protected — remove the password first"
        return rep
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception as e:
        rep.status = "error"
        # Don't leak internal error details or paths
        rep.error = "could not process PDF"
        return rep


# --------------------------------------------------------------------------
# Office (OOXML: docx / xlsx / pptx)
# --------------------------------------------------------------------------

CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties'
    ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:creator></dc:creator><cp:lastModifiedBy></cp:lastModifiedBy>'
    '</cp:coreProperties>'
)

APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties'
    ' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
    ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '<Application></Application>'
    '</Properties>'
)

CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties'
    ' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"'
    ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"/>'
)

# NOTE: kept lower-case because they are compared against ``name.lower()``.
# Includes both the standard media dirs and part-root thumbnails (e.g.
# word/thumbnail.jpeg) so embedded images at any depth get their EXIF scrubbed.
_MEDIA_DIRS = ("word/media/", "xl/media/", "ppt/media/", "docprops/",
               "word/", "xl/", "ppt/")

# Regex-based metadata detection — we deliberately avoid parsing untrusted
# XML (ElementTree/lxml), which keeps us immune to XXE and entity-expansion
# ("billion laughs") attacks.  The detected content is discarded and replaced
# with a fixed, safe template.
_CORE_FIELD_RE = re.compile(
    r"<(?:dc|cp|dcterms):(creator|lastModifiedBy|title|description|subject"
    r"|keywords|category|contentStatus|created|modified|identifier|language"
    r"|version|revision)\b[^>]*>\s*([^<]*)",
    re.IGNORECASE)

_APP_FIELD_RE = re.compile(
    r"<(Company|Manager|Application|AppVersion|HyperlinkBase|TotalTime|"
    r"PresentationFormat|Notes|Security)\b[^>]*>\s*([^<]*)",
    re.IGNORECASE)


def _docprop_fields(data: bytes) -> list:
    fields = set()
    text = data.decode("utf-8", "ignore")
    for m in _CORE_FIELD_RE.finditer(text):
        if m.group(2).strip():
            fields.add(m.group(1))
    return sorted(fields)


def _appprop_fields(data: bytes) -> list:
    fields = set()
    text = data.decode("utf-8", "ignore")
    for m in _APP_FIELD_RE.finditer(text):
        if m.group(2).strip():
            fields.add(m.group(1))
    return sorted(fields)


def _check_zip_entry_name(name: str) -> None:
    """Reject zip entries that could escape the archive (zip-slip defence)."""
    if not name or len(name) > 512:
        raise ScrubError("document contains a suspicious entry name")
    if name.startswith(("/", "\\")):
        raise ScrubError("document contains an absolute-path entry")
    if re.match(r"^[A-Za-z]:", name):
        raise ScrubError("document contains a drive-letter entry")
    if "\x00" in name:
        raise ScrubError("document contains a null-byte entry name")
    parts = name.replace("\\", "/").split("/")
    if ".." in parts:
        raise ScrubError("document contains a path-traversal entry")


def _read_zip_safely(src: str):
    """Read an Office package with decompression-bomb & zip-slip protection.

    Returns (contents: dict[name->bytes], infos: list[ZipInfo]).
    """
    contents: dict = {}
    infos: list = []
    total = 0
    try:
        with zipfile.ZipFile(src, "r") as z:
            infos = z.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ScrubError(
                    f"document has too many entries ({len(infos)})")
            for info in infos:
                name = info.filename
                _check_zip_entry_name(name)
                if info.is_dir():
                    continue
                n = 0
                chunks = []
                try:
                    with z.open(info) as f:
                        while True:
                            chunk = f.read(1 << 20)
                            if not chunk:
                                break
                            n += len(chunk)
                            if n > MAX_ZIP_ENTRY_UNCOMPRESSED:
                                raise ScrubError(
                                    f"entry '{name}' is too large when "
                                    f"decompressed (possible zip bomb)")
                            chunks.append(chunk)
                except RuntimeError as e:
                    raise ScrubError(
                        "document is encrypted or password-protected") from e
                total += n
                if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
                    raise ScrubError(
                        "document is too large after decompression")
                contents[name] = b"".join(chunks)
    except zipfile.BadZipFile:
        raise ScrubError("not a valid Office document (bad zip archive)")
    if not infos:
        raise ScrubError("document appears to be empty")
    return contents, infos


def _is_macro_part(name: str) -> bool:
    low = name.lower()
    return low.endswith("vbaproject.bin") or \
        low.endswith("vbaprojectsignature.bin") or \
        low.endswith("/vbadata.xml")


# WordprocessingML edit-session identifiers (w:rsid*) can be used to trace a
# document's editing history back to a machine.  We strip them with regex —
# no XML parsing of untrusted data.
_RSID_ATTR_RE = re.compile(rb'\s+w:rsid\w*="[0-9A-Fa-f]*"')
_RSIDS_BLOCK_RE = re.compile(rb'<w:rsids[^>]*>.*?</w:rsids>', re.DOTALL)
# Track change author identifiers (w:author, w:date, w:id on w:ins/w:del)
# carry reviewer names and timestamps.  Strip the attributes but keep the
# content elements themselves.
_TRACK_AUTHOR_RE = re.compile(rb'\s+w:author="[^"]*"')
_TRACK_DATE_RE = re.compile(rb'\s+w:date="[^"]*"')
# Comment range markers (w:commentRangeStart, w:commentRangeEnd, w:commentReference)
_COMMENT_RANGE_RE = re.compile(rb'<w:comment(?:Range(?:Start|End)|Reference)[^>]*/?>', re.DOTALL)
# VBA references in [Content_Types].xml and *.rels, removed when macros go.
_VBA_REF_RE = re.compile(rb'<\s*(?:Override|Relationship)\b[^>]*>',
                         re.IGNORECASE)


def _strip_rsids(data: bytes) -> bytes:
    return _RSIDS_BLOCK_RE.sub(b"", _RSID_ATTR_RE.sub(b"", data))


def _count_rsids(data: bytes) -> int:
    return len(_RSID_ATTR_RE.findall(data)) + len(_RSIDS_BLOCK_RE.findall(data))


def _strip_vba_refs(data: bytes) -> bytes:
    """Strip VBA macro references from [Content_Types].xml and *.rels files."""
    def repl(m):
        low = m.group(0).lower()
        if b"vbaproject" in low or b"vbadata" in low:
            return b""
        return m.group(0)
    return _VBA_REF_RE.sub(repl, data)


def _strip_customxml_refs(data: bytes) -> bytes:
    """Strip customXml references from [Content_Types].xml and *.rels files.

    Removes Override/Relationship entries that reference customXml parts,
    preventing dangling references after the customXml directory is dropped.
    """
    def repl(m):
        low = m.group(0).lower()
        if b"customxml" in low or b"customxml" in low:
            return b""
        return m.group(0)
    return _VBA_REF_RE.sub(repl, data)


def _scrub_media_bytes(data: bytes, name: str, opts: Options):
    ext = os.path.splitext(name)[1].lower()
    out, removed = data, []
    if ext in JPEG_EXTS:
        out, removed = strip_jpeg_bytes(data, keep_icc=not opts.strip_icc)
    elif ext == ".png":
        out, removed = strip_png_bytes(data, keep_icc=not opts.strip_icc)
    elif ext == ".webp":
        out, removed = strip_webp_bytes(data, keep_icc=not opts.strip_icc)
    else:
        return data, removed
    return out, removed


def sanitize_office(src: str, dst: str, opts: Options) -> Report:
    rep = Report(src=src, dst=dst)
    try:
        contents, infos = _read_zip_safely(src)
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception:
        rep.status = "error"
        rep.error = "cannot read document"
        return rep

    removed: list = []
    out: dict = {}
    drop: set = set()
    media_count = 0
    macro_count = 0
    rsid_count = 0
    custom_xml_count = 0
    thumb_drop_count = 0
    track_change_count = 0
    comment_ref_count = 0
    sig_count = 0
    pptx_comments_count = 0
    pptx_notes_count = 0
    xlsx_extlinks_count = 0
    xlsx_comments_count = 0

    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        data = contents[name]
        low = name.lower()

        if low == "docprops/core.xml":
            fields = _docprop_fields(data)
            if fields:
                removed.append("document properties (" + ", ".join(fields) + ")")
            data = CORE_XML.encode("utf-8")
        elif low == "docprops/app.xml":
            fields = _appprop_fields(data)
            if fields:
                removed.append("app properties (" + ", ".join(fields) + ")")
            data = APP_XML.encode("utf-8")
        elif low == "docprops/custom.xml":
            removed.append("custom properties")
            data = CUSTOM_XML.encode("utf-8")
        elif low == "word/comments.xml":
            # Word comments carry reviewer names, dates, and comment text
            removed.append("document comments")
            drop.add(name)
        elif low == "word/commentauthors.xml":
            # Comment author list carries reviewer names
            if "comment author list" not in " ".join(removed):
                removed.append("comment author list")
            drop.add(name)
        elif low == "word/commentsextended.xml":
            # Extended comment metadata (OOXML 2013+) — companion to comments.xml
            if "extended comment metadata" not in " ".join(removed):
                removed.append("extended comment metadata")
            drop.add(name)
        elif low == "word/commentsids.xml":
            # Comment-to-paragraph mapping (OOXML 2013+) — companion to comments.xml
            if "comment-to-paragraph mapping" not in " ".join(removed):
                removed.append("comment-to-paragraph mapping")
            drop.add(name)
        elif low == "ppt/commentsauthors.xml":
            # PPTX comment author list carries reviewer names and email addresses
            if "comment author list" not in " ".join(removed):
                removed.append("comment author list")
            drop.add(name)
        elif low.startswith("ppt/comments/"):
            # PPTX comments carry reviewer names, dates, and comment text
            pptx_comments_count += 1
            drop.add(name)
        elif low.startswith("ppt/notesslides/"):
            # PPTX speaker notes often carry confidential content, presenter
            # scripts, internal references, and unreleased information
            pptx_notes_count += 1
            drop.add(name)
        elif low.startswith("xl/externallinks/"):
            # XLSX external links can leak network paths, SharePoint URLs,
            # server names, and file locations
            xlsx_extlinks_count += 1
            drop.add(name)
        elif (low.startswith("xl/comments") and low.endswith(".xml")):
            # XLSX per-sheet comments carry reviewer names and dates
            xlsx_comments_count += 1
            drop.add(name)
        elif low == "xl/authors.xml":
            # XLSX comment author list carries reviewer names
            if "comment author list" not in " ".join(removed):
                removed.append("comment author list")
            drop.add(name)
        elif low.startswith("_xmlsignatures/"):
            # Digital signatures carry signer identity, timestamps, certificates
            drop.add(name)
            sig_count += 1
        elif opts.remove_scripts and _is_macro_part(name):
            drop.add(name)
            macro_count += 1
        elif low.startswith("customxml/"):
            # customXml/ carries arbitrary metadata (author, company, document IDs,
            # even SSNs).  Drop all parts and their references.
            drop.add(name)
            custom_xml_count += 1
        elif low.endswith((".wmf", ".emf")) and \
                (low.startswith("docprops/") or low.startswith("word/") or
                 low.startswith("xl/") or low.startswith("ppt/")):
            # WMF/EMF thumbnails can carry metadata we can't reliably scrub.
            # Drop them — they're thumbnails, not content.
            drop.add(name)
            thumb_drop_count += 1
        elif low.startswith(_MEDIA_DIRS) and \
                low.endswith((".jpg", ".jpeg", ".jfif", ".jpe", ".png", ".webp")):
            new_data, r = _scrub_media_bytes(data, name, opts)
            if r:
                data = new_data
                media_count += 1
        else:
            # Privacy scrub for all other XML parts:
            #   * w:rsid edit-session IDs (docx) — .xml parts
            #   * track change author info (w:author, w:date on w:ins/w:del)
            #   * comment range markers (w:commentRangeStart/End/Reference)
            #   * dangling VBA references when macros are being removed —
            #     [Content_Types].xml and *.rels parts
            #   * dangling customXml references — [Content_Types].xml and *.rels
            if low.endswith(".xml"):
                rsid_count += _count_rsids(data)
                data = _strip_rsids(data)
                # Strip track change author attributes (keep the elements)
                n_author = len(_TRACK_AUTHOR_RE.findall(data))
                n_date = len(_TRACK_DATE_RE.findall(data))
                if n_author or n_date:
                    track_change_count += n_author + n_date
                    data = _TRACK_AUTHOR_RE.sub(b"", data)
                    data = _TRACK_DATE_RE.sub(b"", data)
                # Strip comment range markers
                n_comment = len(_COMMENT_RANGE_RE.findall(data))
                if n_comment:
                    comment_ref_count += n_comment
                    data = _COMMENT_RANGE_RE.sub(b"", data)
            if opts.remove_scripts and \
                    (low == "[content_types].xml" or low.endswith(".rels")):
                data = _strip_vba_refs(data)
            # Always strip customXml refs — we may encounter [Content_Types].xml
            # before the customXml parts themselves (zip entry order varies).
            if low == "[content_types].xml" or low.endswith(".rels"):
                data = _strip_customxml_refs(data)
            # Strip comment references from .rels
            if low.endswith(".rels"):
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*comments[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip PPTX notesSlide and commentAuthors references from .rels
            if low.endswith(".rels"):
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*notesSlide[^>]*>',
                    b"", data, flags=re.IGNORECASE)
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*commentAuthors[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip XLSX externalLink references from .rels
            if low.endswith(".rels"):
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*externalLink[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip digital-signature references from .rels
            if low.endswith(".rels"):
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*digital-signature[^>]*>',
                    b"", data, flags=re.IGNORECASE)
                data = re.sub(
                    rb'<\s*Relationship\b[^>]*_xmlsignatures[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip signature content-type overrides from [Content_Types].xml
            if low == "[content_types].xml":
                data = re.sub(
                    rb'<\s*Override\b[^>]*digsig[^>]*>',
                    b"", data, flags=re.IGNORECASE)
                data = re.sub(
                    rb'<\s*Override\b[^>]*xml-signature[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip PPTX notesSlide and comment content-type overrides
            if low == "[content_types].xml":
                data = re.sub(
                    rb'<\s*Override\b[^>]*notesSlide[^>]*>',
                    b"", data, flags=re.IGNORECASE)
                data = re.sub(
                    rb'<\s*Override\b[^>]*comment[^>]*>',
                    b"", data, flags=re.IGNORECASE)
            # Strip XLSX externalLink content-type overrides
            if low == "[content_types].xml":
                data = re.sub(
                    rb'<\s*Override\b[^>]*externalLink[^>]*>',
                    b"", data, flags=re.IGNORECASE)
        out[name] = data

    if macro_count:
        removed.append("VBA macro project removed" if macro_count == 1
                       else f"{macro_count} VBA macro parts removed")
    if rsid_count:
        removed.append(f"{rsid_count} edit-session ID(s) removed (rsid)")
    if media_count:
        removed.append(f"metadata in {media_count} embedded image(s)")
    if custom_xml_count:
        removed.append(f"{custom_xml_count} custom XML metadata part(s) removed")
    if thumb_drop_count:
        removed.append(f"{thumb_drop_count} thumbnail(s) removed (unsanitized format)")
    if track_change_count:
        removed.append(f"{track_change_count} track-change author attribution(s) removed")
    if comment_ref_count:
        removed.append(f"{comment_ref_count} comment reference(s) removed from document")
    if sig_count:
        removed.append(f"{sig_count} digital signature part(s) removed")
    if pptx_comments_count:
        removed.append(f"{pptx_comments_count} PPTX comment(s) removed")
    if pptx_notes_count:
        removed.append(f"{pptx_notes_count} PPTX speaker note(s) removed")
    if xlsx_extlinks_count:
        removed.append(f"{xlsx_extlinks_count} XLSX external link(s) removed")
    if xlsx_comments_count:
        removed.append(f"{xlsx_comments_count} XLSX sheet comment(s) removed")

    def _write_zip_to(path: str) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in infos:
                name = info.filename
                if name in drop or info.is_dir():
                    continue
                zinfo = zipfile.ZipInfo(name)
                # Zero timestamps (no edit history) and neutralize permission
                # / system attributes so extraction uses safe defaults.
                zinfo.date_time = (1980, 1, 1, 0, 0, 0)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.create_system = 0
                zinfo.external_attr = 0
                zout.writestr(zinfo, out[name])

    try:
        _atomic_write(dst, _write_zip_to)
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception:
        rep.status = "error"
        rep.error = "could not write document"
        return rep

    rep.status = "ok" if removed else "clean"
    rep.removed = removed
    if not removed:
        rep.notes.append("no metadata found")
    return rep



# --------------------------------------------------------------------------
# OpenDocument (ODF: odt / ods / odp)
# --------------------------------------------------------------------------

# ODF meta.xml template — replace the full <office:meta> block with an empty
# one.  This is the ODF equivalent of OOXML's docProps/core.xml.
_ODF_META_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<office:document-meta\n'
    '  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"\n'
    '  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"\n'
    '  xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
    '  <office:meta>\n'
    '    <dc:creator></dc:creator>\n'
    '    <meta:initial-creator></meta:initial-creator>\n'
    '    <dc:date></dc:date>\n'
    '    <meta:creation-date></meta:creation-date>\n'
    '    <meta:editing-cycles>1</meta:editing-cycles>\n'
    '    <meta:editing-duration>PT0S</meta:editing-duration>\n'
    '  </office:meta>\n'
    '</office:document-meta>'
)

# Regex patterns for ODF content.xml sanitization
# Track changes carry author names and timestamps
_ODF_CHANGED_REGION_RE = re.compile(rb'<text:changed-region[^>]*>.*?</text:changed-region>', re.DOTALL)
_ODF_CHANGE_START_RE = re.compile(rb'<text:change-start[^>]*\s+dc:creator="[^"]*"[^>]*/?>')
_ODF_CHANGE_START_DATE_RE = re.compile(rb'<text:change-start[^>]*\s+dc:date="[^"]*"[^>]*/?>')
_ODF_CHANGE_RE = re.compile(rb'<text:change[^>]*\s+dc:creator="[^"]*"[^>]*/?>')
_ODF_CHANGE_DATE_RE = re.compile(rb'<text:change[^>]*\s+dc:date="[^"]*"[^>]*/?>')
_ODF_CHANGE_END_RE = re.compile(rb'<text:change-end[^>]*/?>')
# Annotations (comments) carry author names, timestamps, and comment text
_ODF_ANNOTATION_RE = re.compile(rb'<text:annotation[^>]*>.*?</text:annotation>', re.DOTALL)

# ODF macro part names (LibreOffice/OpenOffice Basic macros)
_ODF_MACRO_DIRS = ("basic/", "scripts/")


def _is_odf_macro_part(name: str) -> bool:
    """Check if a zip entry is an ODF macro."""
    low = name.lower()
    return low.startswith(_ODF_MACRO_DIRS)


def _odf_meta_fields(data: bytes) -> list:
    """Extract metadata field names from ODF meta.xml for reporting."""
    fields = set()
    text = data.decode("utf-8", "ignore")
    # Look for common meta fields
    patterns = [
        (r'<dc:creator[^>]*>([^<]+)', 'creator'),
        (r'<meta:initial-creator[^>]*>([^<]+)', 'initial-creator'),
        (r'<dc:date[^>]*>([^<]+)', 'date'),
        (r'<meta:creation-date[^>]*>([^<]+)', 'creation-date'),
        (r'<dc:title[^>]*>([^<]+)', 'title'),
        (r'<dc:description[^>]*>([^<]+)', 'description'),
        (r'<dc:subject[^>]*>([^<]+)', 'subject'),
        (r'<meta:keyword[^>]*>([^<]+)', 'keyword'),
        (r'<meta:document-statistic[^>]*>', 'document-statistic'),
        (r'<meta:generator[^>]*>([^<]+)', 'generator'),
    ]
    for pattern, name in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            fields.add(name)
    return sorted(fields)


# Regex for settings.xml config items that carry author/company info
_ODF_SETTINGS_AUTHOR_RE = re.compile(rb'<config:config-item[^>]*config:name="(Author|Company|User)[^>]*>[^<]*</config:config-item>')


def sanitize_opendocument(src: str, dst: str, opts: Options) -> Report:
    """Sanitize an OpenDocument file (ODT/ODS/ODP).

    ODF uses ZIP+XML structure similar to OOXML but with different entry names:
      - meta.xml (instead of docProps/core.xml)
      - content.xml (instead of word/document.xml)
      - styles.xml (instead of word/styles.xml)
      - settings.xml (instead of word/settings.xml)
      - Basic/ directory (macros)
      - Thumbnails/ directory
    """
    rep = Report(src=src, dst=dst)
    try:
        contents, infos = _read_zip_safely(src)
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception:
        rep.status = "error"
        rep.error = "cannot read document"
        return rep

    removed: list = []
    out: dict = {}
    drop: set = set()
    macro_count = 0
    track_change_count = 0
    annotation_count = 0
    settings_author_count = 0
    custom_ui_count = 0

    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        data = contents[name]
        low = name.lower()

        # meta.xml carries all the identity metadata
        if low == "meta.xml":
            fields = _odf_meta_fields(data)
            if fields:
                removed.append("document metadata (" + ", ".join(fields) + ")")
            data = _ODF_META_XML.encode("utf-8")
        elif low == "content.xml":
            # Strip track changes (carry author names and timestamps)
            n_changed = len(_ODF_CHANGED_REGION_RE.findall(data))
            if n_changed:
                track_change_count += n_changed
                data = _ODF_CHANGED_REGION_RE.sub(b"", data)
            n_change_start = len(_ODF_CHANGE_START_RE.findall(data))
            if n_change_start:
                track_change_count += n_change_start
                data = _ODF_CHANGE_START_RE.sub(b"", data)
            n_change_start_date = len(_ODF_CHANGE_START_DATE_RE.findall(data))
            if n_change_start_date:
                track_change_count += n_change_start_date
                data = _ODF_CHANGE_START_DATE_RE.sub(b"", data)
            n_change = len(_ODF_CHANGE_RE.findall(data))
            if n_change:
                track_change_count += n_change
                data = _ODF_CHANGE_RE.sub(b"", data)
            n_change_date = len(_ODF_CHANGE_DATE_RE.findall(data))
            if n_change_date:
                track_change_count += n_change_date
                data = _ODF_CHANGE_DATE_RE.sub(b"", data)
            n_change_end = len(_ODF_CHANGE_END_RE.findall(data))
            if n_change_end:
                track_change_count += n_change_end
                data = _ODF_CHANGE_END_RE.sub(b"", data)
            # Strip annotations/comments (carry author names, timestamps, comment text)
            n_annotation = len(_ODF_ANNOTATION_RE.findall(data))
            if n_annotation:
                annotation_count += n_annotation
                data = _ODF_ANNOTATION_RE.sub(b"", data)
        elif low == "settings.xml":
            # Strip author/company config items
            n_settings = len(_ODF_SETTINGS_AUTHOR_RE.findall(data))
            if n_settings:
                settings_author_count += n_settings
                data = _ODF_SETTINGS_AUTHOR_RE.sub(b"", data)
        elif low == "mimetype":
            # Keep mimetype as-is (required for ODF)
            pass
        elif _is_odf_macro_part(name) and opts.remove_scripts:
            # ODF macros (LibreOffice Basic)
            drop.add(name)
            macro_count += 1
        elif low.startswith("thumbnails/"):
            # Drop thumbnail directory
            drop.add(name)
        elif low.startswith("customui/"):
            # Drop custom UI folder (ribbon customization, can carry author IDs)
            drop.add(name)
            custom_ui_count += 1
        
        out[name] = data

    if macro_count:
        removed.append(f"{macro_count} macro part(s) removed")
    if track_change_count:
        removed.append(f"{track_change_count} track-change field(s) removed")
    if annotation_count:
        removed.append(f"{annotation_count} annotation(s) removed")
    if settings_author_count:
        removed.append(f"{settings_author_count} settings author field(s) removed")
    if custom_ui_count:
        removed.append(f"{custom_ui_count} custom UI part(s) removed")

    def _write_odf(path: str) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in infos:
                name = info.filename
                if name in drop or info.is_dir():
                    continue
                zinfo = zipfile.ZipInfo(name)
                zinfo.date_time = (1980, 1, 1, 0, 0, 0)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.create_system = 0
                zinfo.external_attr = 0
                zout.writestr(zinfo, out[name])

    try:
        _atomic_write(dst, _write_odf)
    except ScrubError as e:
        rep.status = "error"
        rep.error = str(e)
        return rep
    except Exception:
        rep.status = "error"
        rep.error = "could not write document"
        return rep

    rep.status = "ok" if removed else "clean"
    rep.removed = removed
    if not removed:
        rep.notes.append("no metadata found")
    return rep


# --------------------------------------------------------------------------
# Top-level dispatcher
# --------------------------------------------------------------------------

def sanitize_file(src: str, dst: str, opts: Options) -> Report:
    if not os.path.isfile(src):
        return Report(src=src, dst=dst, status="error",
                      error="file not found")
    
    # Resolve symlinks in source path for security
    try:
        real_src = os.path.realpath(src)
        if not os.path.isfile(real_src):
            return Report(src=src, dst=dst, status="error",
                          error="file not found")
    except (OSError, ValueError):
        return Report(src=src, dst=dst, status="error",
                      error="invalid file path")
    
    ext = os.path.splitext(src)[1].lower()
    if ext in IMAGE_EXTS:
        return sanitize_image(real_src, dst, opts)
    if ext == ".pdf":
        return sanitize_pdf(real_src, dst, opts)
    if ext in (".docx", ".xlsx", ".pptx"):
        return sanitize_office(real_src, dst, opts)
    if ext in (".odt", ".ods", ".odp"):
        return sanitize_opendocument(real_src, dst, opts)
    return Report(src=src, dst=dst, status="skipped",
                  error=f"unsupported file type: {ext or '(none)'}")


def default_output_path(src: str, out_dir: str | None, suffix: str,
                        subfolder: bool = False) -> str:
    """Compute the path for the sanitized copy of ``src``."""
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    if out_dir:
        d = out_dir
        if subfolder:
            d = os.path.join(out_dir, "Clean")
    else:
        d = os.path.dirname(src)
        if subfolder:
            d = os.path.join(d, "Clean")
    
    # Resolve symlinks in output directory for security
    try:
        d = os.path.realpath(d)
    except (OSError, ValueError):
        raise ScrubError(f"invalid output directory: {d}")
    
    candidate = os.path.join(d, f"{stem}{suffix}{ext}")
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(d, f"{stem}{suffix}_{n}{ext}")
        n += 1
    return candidate


# --------------------------------------------------------------------------
# CLI (also handy for scripts and for automated testing)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(
        description="PrivacyDrop — strip hidden metadata from images & documents.")
    p.add_argument("files", nargs="+", help="files or folders to sanitize")
    p.add_argument("--out", "-o", default=None, help="output directory")
    p.add_argument("--suffix", default="_clean", help="output file name suffix")
    p.add_argument("--strip-icc", action="store_true",
                   help="also remove color profiles")
    p.add_argument("--keep-attachments", action="store_true",
                   help="keep files embedded inside PDFs")
    p.add_argument("--keep-scripts", action="store_true",
                   help="keep macros and PDF JavaScript (not recommended)")
    args = p.parse_args()

    opts = Options(strip_icc=args.strip_icc,
                   remove_pdf_attachments=not args.keep_attachments,
                   remove_scripts=not args.keep_scripts,
                   suffix=args.suffix)

    jobs = []
    missing = 0
    for path in args.files:
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    full = os.path.join(root, f)
                    if supported(full):
                        jobs.append(full)
        elif os.path.isfile(path):
            jobs.append(path)
        else:
            print(f"! not found: {path}", file=sys.stderr)
            missing += 1

    ok = clean = err = skip = 0
    for src in jobs:
        dst = default_output_path(src, args.out, args.suffix)
        rep = sanitize_file(src, dst, opts)
        mark = {"ok": "+", "clean": "=", "skipped": "-", "error": "!"}[rep.status]
        print(f"{mark} {os.path.basename(src)} -> {rep.summary()}")
        if rep.status == "ok":
            ok += 1
        elif rep.status == "clean":
            clean += 1
        elif rep.status == "error":
            err += 1
        else:
            skip += 1

    print(f"\nDone: {ok} cleaned, {clean} already clean, {err} failed, "
          f"{skip} skipped.")
    sys.exit(1 if (err or missing) else 0)
