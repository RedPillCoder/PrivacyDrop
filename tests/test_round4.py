"""Tests for round 4 privacy improvements: Office customXml drop, Photoshop IRB
identification in JPEG, and WMF/EMF thumbnail drop from Office files.
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
# Office customXml drop
# ---------------------------------------------------------------------------

def test_office_customxml_dropped():
    """customXml/ directory files are removed from Office packages."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'test.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/customXml/item1.xml" ContentType="application/xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('customXml/item1.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<author>John Smith</author><ssn>123-45-6789</ssn>')

        dst = os.path.join(td, 'test_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("customXml docx cleaned", rep.ok)
        check("customXml reported as removed",
              any("custom xml" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        # Verify customXml files are gone from output
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_customxml = any(n.lower().startswith('customxml/') for n in names)
            check("no customXml files in output", not has_customxml)

            # Verify references are stripped from [Content_Types].xml
            ct = z.read('[Content_Types].xml').decode('utf-8', errors='ignore')
            check("customXml ref stripped from [Content_Types].xml",
                  'customXml' not in ct and 'customxml' not in ct.lower(),
                  f"found in: {ct[:200]}")

            # Verify references are stripped from .rels
            rels = z.read('_rels/.rels').decode('utf-8', errors='ignore')
            check("customXml ref stripped from .rels",
                  'customXml' not in rels and 'customxml' not in rels.lower(),
                  f"found in: {rels[:200]}")


def test_office_customxml_with_pii():
    """PII in customXml is not present in the cleaned output."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'pii.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('customXml/item1.xml',
                '<data><name>John Smith</name><email>john@example.com</email></data>')

        dst = os.path.join(td, 'pii_clean.docx')
        sanitize_file(docx, dst, Options())

        # Search for PII in the output file
        with open(dst, 'rb') as f:
            data = f.read()
        check("no PII in cleaned output",
              b'John Smith' not in data and b'john@example.com' not in data)


# ---------------------------------------------------------------------------
# Photoshop IRB (APP13) identification in JPEG
# ---------------------------------------------------------------------------

def test_jpeg_photoshop_irb_identified():
    """JPEG APP13 (Photoshop IRB) is specifically identified in reports."""
    from scrubber import strip_jpeg_bytes

    # Create a minimal JPEG with APP13 (Photoshop IRB)
    # APP13 marker = 0xED, followed by length and payload starting with "Photoshop 3.0\x00"
    jpeg = b'\xff\xd8'  # SOI
    jpeg += b'\xff\xed\x00\x10Photoshop 3.0\x00'  # APP13 with minimal payload
    jpeg += b'\xff\xd9'  # EOI

    out, removed = strip_jpeg_bytes(jpeg, keep_icc=True)
    check("APP13 stripped", b'\xff\xed' not in out)
    check("Photoshop metadata reported",
          any("photoshop" in r.lower() for r in removed),
          f"removed: {removed}")


def test_jpeg_no_app13_no_photoshop_report():
    """JPEG without APP13 does not report Photoshop metadata."""
    from scrubber import strip_jpeg_bytes

    # Minimal JPEG with only EXIF
    jpeg = b'\xff\xd8'
    jpeg += b'\xff\xe1\x00\x08Exif\x00\x00'  # APP1 with EXIF header
    jpeg += b'\xff\xd9'

    out, removed = strip_jpeg_bytes(jpeg, keep_icc=True)
    check("no Photoshop report when no APP13",
          not any("photoshop" in r.lower() for r in removed),
          f"removed: {removed}")


# ---------------------------------------------------------------------------
# WMF/EMF thumbnail drop from Office
# ---------------------------------------------------------------------------

def test_office_wmf_thumbnail_dropped():
    """WMF thumbnails in Office files are dropped."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'thumb.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="wmf" ContentType="image/x-wmf"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            # WMF thumbnail at word/thumbnail.wmf
            z.writestr('word/thumbnail.wmf', b'\xd7\xcd\xc6\x9a' + b'\x00' * 100)

        dst = os.path.join(td, 'thumb_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("WMF thumbnail docx cleaned", rep.ok)
        check("thumbnail reported as removed",
              any("thumbnail" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        # Verify WMF is gone
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_wmf = any(n.lower().endswith('.wmf') for n in names)
            check("no WMF files in output", not has_wmf)


def test_office_emf_thumbnail_dropped():
    """EMF thumbnails in Office files are dropped."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'emf.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="emf" ContentType="image/x-emf"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('docprops/thumbnail.emf', b'\x01\x00\x00\x00' + b'\x00' * 100)

        dst = os.path.join(td, 'emf_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("EMF thumbnail docx cleaned", rep.ok)
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_emf = any(n.lower().endswith('.emf') for n in names)
            check("no EMF files in output", not has_emf)


def test_office_jpeg_thumbnail_kept_and_scrubbed():
    """JPEG thumbnails are kept and scrubbed (not dropped)."""
    from scrubber import sanitize_file, Options
    from PIL import Image
    import io

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'jpeg_thumb.docx')
        
        # Create a JPEG thumbnail with EXIF
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=b"Exif\x00\x00" + b"\x00" * 20)
        jpeg_data = buf.getvalue()
        
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="jpeg" ContentType="image/jpeg"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('word/thumbnail.jpeg', jpeg_data)

        dst = os.path.join(td, 'jpeg_thumb_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("JPEG thumbnail docx cleaned", rep.ok)
        # JPEG thumbnail should be kept (not dropped)
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_jpeg = any(n.lower().endswith('.jpeg') for n in names)
            check("JPEG thumbnail kept in output", has_jpeg)
            
            # Verify EXIF is stripped
            if has_jpeg:
                thumb_data = z.read('word/thumbnail.jpeg')
                check("EXIF stripped from JPEG thumbnail",
                      b"Exif\x00\x00" not in thumb_data)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_office_customxml_dropped()
    test_office_customxml_with_pii()
    test_jpeg_photoshop_irb_identified()
    test_jpeg_no_app13_no_photoshop_report()
    test_office_wmf_thumbnail_dropped()
    test_office_emf_thumbnail_dropped()
    test_office_jpeg_thumbnail_kept_and_scrubbed()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
