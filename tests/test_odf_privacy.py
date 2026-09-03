"""Tests for ODF privacy improvements: track changes, annotations, settings, generator."""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrubber import sanitize_file, Options

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


def test_odf_generator_stripped():
    """ODF meta.xml generator field is stripped."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'gen.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
                '  <office:meta>\n'
                '    <dc:creator>John Smith</dc:creator>\n'
                '    <meta:generator>LibreOffice/7.5.4.2$Linux_X86_64</meta:generator>\n'
                '  </office:meta>\n'
                '</office:document-meta>')
            z.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:body><office:text><text:p>Test</text:p></office:text></office:body></office:document-content>')
            z.writestr('settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
            z.writestr('styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
        
        dst = os.path.join(td, 'clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("generator ODT cleaned", rep.ok)
        check("generator reported as removed",
              any("generator" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            meta = z.read('meta.xml').decode('utf-8', errors='ignore')
            check("no generator in meta.xml", 'generator' not in meta.lower())
            check("no John Smith in meta.xml", 'John Smith' not in meta)


def test_odf_track_changes_stripped():
    """ODF content.xml track changes are stripped."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'tracked.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:meta><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">John</dc:creator></office:meta></office:document-meta>')
            z.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
                '  <office:meta><text:changed-region text:id="ct0"><text:deletion><dc:creator>Jane Doe</dc:creator><dc:date>2024-08-15T10:00:00</dc:date></text:deletion></text:changed-region></office:meta>\n'
                '  <office:body><office:text>\n'
                '    <text:p><text:change-start text:change-id="ct0" dc:creator="Jane Doe" dc:date="2024-08-15T10:00:00"/><text:change-end text:change-id="ct0"/>Hello World</text:p>\n'
                '  </office:text></office:body>\n'
                '</office:document-content>')
            z.writestr('settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
            z.writestr('styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
        
        dst = os.path.join(td, 'clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("track changes ODT cleaned", rep.ok)
        check("track changes reported as removed",
              any("track-change" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            content = z.read('content.xml').decode('utf-8', errors='ignore')
            check("no changed-region in content.xml", 'changed-region' not in content)
            check("no Jane Doe in content.xml", 'Jane Doe' not in content)
            check("no change-start in content.xml", 'change-start' not in content)
            check("no change-end in content.xml", 'change-end' not in content)
            check("content preserved", 'Hello World' in content)


def test_odf_annotations_stripped():
    """ODF content.xml annotations are stripped."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'annotated.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:meta><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">John</dc:creator></office:meta></office:document-meta>')
            z.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
                '  <office:body><office:text>\n'
                '    <text:p>Hello <text:annotation><dc:creator>John Smith</dc:creator><dc:date>2024-08-15T11:00:00</dc:date><text:p>Needs revision</text:p></text:annotation> World</text:p>\n'
                '  </office:text></office:body>\n'
                '</office:document-content>')
            z.writestr('settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
            z.writestr('styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
        
        dst = os.path.join(td, 'clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("annotations ODT cleaned", rep.ok)
        check("annotations reported as removed",
              any("annotation" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            content = z.read('content.xml').decode('utf-8', errors='ignore')
            check("no annotation in content.xml", 'annotation' not in content)
            check("no John Smith in content.xml", 'John Smith' not in content)
            check("no Needs revision in content.xml", 'Needs revision' not in content)
            check("content preserved", 'Hello' in content and 'World' in content)


def test_odf_settings_author_stripped():
    """ODF settings.xml author/company fields are stripped."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'settings.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:meta><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">John</dc:creator></office:meta></office:document-meta>')
            z.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:body><office:text><text:p>Test</text:p></office:text></office:body></office:document-content>')
            z.writestr('settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">\n'
                '  <office:settings>\n'
                '    <config:config-item-set config:name="ooo-settings">\n'
                '      <config:config-item config:name="Author">John Smith</config:config-item>\n'
                '      <config:config-item config:name="Company">Acme Corp</config:config-item>\n'
                '    </config:config-item-set>\n'
                '  </office:settings>\n'
                '</office:document-settings>')
            z.writestr('styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
        
        dst = os.path.join(td, 'clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("settings ODT cleaned", rep.ok)
        check("settings author reported as removed",
              any("settings" in r.lower() and "author" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            settings = z.read('settings.xml').decode('utf-8', errors='ignore')
            check("no John Smith in settings.xml", 'John Smith' not in settings)
            check("no Acme Corp in settings.xml", 'Acme Corp' not in settings)


def test_odf_customui_dropped():
    """ODF customUI/ folder is dropped."""
    with tempfile.TemporaryDirectory() as td:
        odt = os.path.join(td, 'customui.odt')
        with zipfile.ZipFile(odt, 'w') as z:
            z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', compress_type=zipfile.ZIP_STORED)
            z.writestr('meta.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:meta><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">John</dc:creator></office:meta></office:document-meta>')
            z.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"><office:body><office:text><text:p>Test</text:p></office:text></office:body></office:document-content>')
            z.writestr('settings.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-settings xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
            z.writestr('styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"/>')
            z.writestr('customui/ribbon.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<customUI xmlns="http://schemas.openxmlformats.org/2006/relationships/ui/extensibility"><ribbon><tabs><tab id="customTab" label="Custom"><group id="customGroup" label="Custom Group"><button id="customButton" label="Custom Button" onAction="OnCustomAction"/></group></tab></tabs></ribbon></customUI>')
        
        dst = os.path.join(td, 'clean.odt')
        rep = sanitize_file(odt, dst, Options())
        
        check("customUI ODT cleaned", rep.ok)
        check("customUI reported as removed",
              any("custom ui" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_customui = any('customui' in n.lower() for n in names)
            check("no customUI in output", not has_customui)


if __name__ == "__main__":
    test_odf_generator_stripped()
    test_odf_track_changes_stripped()
    test_odf_annotations_stripped()
    test_odf_settings_author_stripped()
    test_odf_customui_dropped()
    
    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
