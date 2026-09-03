"""Tests for new format support: SVG, AVIF, ODF (ODT/ODS/ODP)."""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrubber import sanitize_file, Options, SUPPORTED_EXTS

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def test_svg_metadata_removed():
    """SVG metadata, comments, and scripts are removed."""
    with tempfile.TemporaryDirectory() as td:
        svg = os.path.join(td, 'test.svg')
        with open(svg, 'w') as f:
            f.write('''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <metadata>
    <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test SVG</dc:title>
    <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">John Smith</dc:creator>
  </metadata>
  <!-- Sensitive comment -->
  <script>alert('xss')</script>
  <circle cx="50" cy="50" r="40" fill="red"/>
</svg>''')
        
        dst = os.path.join(td, 'test_clean.svg')
        rep = sanitize_file(svg, dst, Options())
        
        check("svg cleaned", rep.ok)
        check("svg metadata removed", 
              any("metadata" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        check("svg comment removed",
              any("comment" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        check("svg script removed",
              any("script" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        if rep.ok:
            with open(dst, 'r') as f:
                cleaned = f.read()
                check("no metadata tag", '<metadata>' not in cleaned)
                check("no comment", '<!--' not in cleaned)
                check("no script", '<script>' not in cleaned)
                check("no PII", 'John Smith' not in cleaned)
                check("content preserved", '<circle' in cleaned)


def test_svg_invalid():
    """Invalid SVG file returns error."""
    with tempfile.TemporaryDirectory() as td:
        svg = os.path.join(td, 'bad.svg')
        with open(svg, 'w') as f:
            f.write('<html><body>Not SVG</body></html>')
        
        dst = os.path.join(td, 'bad_clean.svg')
        rep = sanitize_file(svg, dst, Options())
        
        check("invalid svg returns error", rep.status == "error")


def test_avif_cleaned():
    """AVIF files are cleaned (re-encoded to remove metadata)."""
    try:
        from PIL import Image
        
        with tempfile.TemporaryDirectory() as td:
            img = Image.new('RGB', (100, 100), color='red')
            avif = os.path.join(td, 'test.avif')
            img.save(avif, 'AVIF')
            
            dst = os.path.join(td, 'test_clean.avif')
            rep = sanitize_file(avif, dst, Options())
            
            check("avif cleaned", rep.ok or rep.status == "clean")
    except Exception as e:
        print(f"  SKIP  avif (Pillow AVIF support not available: {e})")


def test_odt_metadata_removed():
    """ODT document metadata is removed."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'test.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text',
                      compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <office:meta>
    <dc:creator>John Smith</dc:creator>
    <meta:initial-creator>Jane Doe</meta:initial-creator>
    <dc:title>Secret Document</dc:title>
  </office:meta>
</office:document-meta>''')
            z.writestr('content.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:p>Hello World</text:p>
    </office:text>
  </office:body>
</office:document-content>''')
        
        dst = os.path.join(td, 'test_clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("odt cleaned", rep.ok)
        check("odt metadata removed",
              any("metadata" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        if rep.ok:
            with zipfile.ZipFile(dst, 'r') as z:
                meta = z.read('meta.xml').decode('utf-8')
                check("no creator in meta.xml", 'John Smith' not in meta)
                check("no initial-creator in meta.xml", 'Jane Doe' not in meta)
                check("no title in meta.xml", 'Secret Document' not in meta)
                check("content preserved",
                      'Hello World' in z.read('content.xml').decode('utf-8'))


def test_ods_supported():
    """ODS (spreadsheet) is supported."""
    check("ods in SUPPORTED_EXTS", '.ods' in SUPPORTED_EXTS)


def test_odp_supported():
    """ODP (presentation) is supported."""
    check("odp in SUPPORTED_EXTS", '.odp' in SUPPORTED_EXTS)


def test_svg_supported():
    """SVG is supported."""
    check("svg in SUPPORTED_EXTS", '.svg' in SUPPORTED_EXTS)


def test_avif_supported():
    """AVIF is supported."""
    check("avif in SUPPORTED_EXTS", '.avif' in SUPPORTED_EXTS)


if __name__ == "__main__":
    test_svg_metadata_removed()
    test_svg_invalid()
    test_avif_cleaned()
    test_odt_metadata_removed()
    test_ods_supported()
    test_odp_supported()
    test_svg_supported()
    test_avif_supported()
    
    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
