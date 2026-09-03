"""Tests for PPTX and XLSX privacy improvements: speaker notes, comments,
external links, and sheet comments."""

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


def test_pptx_speaker_notes_dropped():
    """PPTX ppt/notesSlides/ folder is dropped with references stripped."""
    with tempfile.TemporaryDirectory() as td:
        pptx = os.path.join(td, 'notes.pptx')
        with zipfile.ZipFile(pptx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                '<Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr('ppt/_rels/presentation.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="notesSlides/notesSlide1.xml"/>'
                '</Relationships>')
            z.writestr('ppt/presentation.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
            z.writestr('ppt/notesSlides/notesSlide1.xml',
                '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree><p:sp><p:txBody><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:r><a:t>CONFIDENTIAL: John Smith john@acme.com</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>')
        
        dst = os.path.join(td, 'clean.pptx')
        rep = sanitize_file(pptx, dst, Options())
        
        check("PPTX speaker notes cleaned", rep.ok)
        check("speaker notes reported as removed",
              any("speaker note" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_notes = any('notesslide' in n.lower() for n in names)
            check("no notesSlides in output", not has_notes)
            
            rels = z.read('ppt/_rels/presentation.xml.rels').decode('utf-8', errors='ignore')
            check("no notesSlide ref in .rels", 'notesSlide' not in rels)
            
            ct = z.read('[Content_Types].xml').decode('utf-8', errors='ignore')
            check("no notesSlide in [Content_Types].xml", 'notesSlide' not in ct)
            
            raw = b''
            for n in names:
                raw += z.read(n)
            check("no PII in output", b'John Smith' not in raw and b'john@acme.com' not in raw)


def test_pptx_comments_dropped():
    """PPTX ppt/comments/ folder and commentsAuthors.xml are dropped."""
    with tempfile.TemporaryDirectory() as td:
        pptx = os.path.join(td, 'comments.pptx')
        with zipfile.ZipFile(pptx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
                '<Override PartName="/ppt/comments/comment1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.comment+xml"/>'
                '<Override PartName="/ppt/commentsAuthors.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr('ppt/_rels/presentation.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments/comment1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/commentAuthors" Target="commentsAuthors.xml"/>'
                '</Relationships>')
            z.writestr('ppt/presentation.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
            z.writestr('ppt/comments/comment1.xml',
                '<p:cm xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cmLst><p:cm authorId="0" dt="2024-08-15T10:00:00">'
                '<a:txBody xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:p><a:r><a:t>Needs revision</a:t></a:r></a:p></a:txBody></p:cm></p:cmLst></p:cm>')
            z.writestr('ppt/commentsAuthors.xml',
                '<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cmAuthor id="0" name="Jane Doe" userId="jane@acme.com"/>'
                '</p:cmAuthorLst>')
        
        dst = os.path.join(td, 'clean.pptx')
        rep = sanitize_file(pptx, dst, Options())
        
        check("PPTX comments cleaned", rep.ok)
        check("PPTX comments reported as removed",
              any("pptx comment" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_comments = any('comment' in n.lower() for n in names)
            check("no comments in output", not has_comments)
            
            rels = z.read('ppt/_rels/presentation.xml.rels').decode('utf-8', errors='ignore')
            check("no comment ref in .rels", 'comment' not in rels.lower())


def test_xlsx_external_links_dropped():
    """XLSX xl/externalLinks/ folder is dropped with references stripped."""
    with tempfile.TemporaryDirectory() as td:
        xlsx = os.path.join(td, 'external.xlsx')
        with zipfile.ZipFile(xlsx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/externalLinks/externalLink1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr('xl/_rels/workbook.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink1.xml"/>'
                '</Relationships>')
            z.writestr('xl/workbook.xml',
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
            z.writestr('xl/externalLinks/externalLink1.xml',
                '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<externalReference file="\\\\fileserver.acme.corp\\Finance\\Q3_2024\\Budget.xlsx"/>'
                '</externalLink>')
        
        dst = os.path.join(td, 'clean.xlsx')
        rep = sanitize_file(xlsx, dst, Options())
        
        check("XLSX external links cleaned", rep.ok)
        check("external links reported as removed",
              any("external link" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_ext = any('externallink' in n.lower() for n in names)
            check("no externalLinks in output", not has_ext)
            
            rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8', errors='ignore')
            check("no externalLink ref in .rels", 'externalLink' not in rels)
            
            ct = z.read('[Content_Types].xml').decode('utf-8', errors='ignore')
            check("no externalLink in [Content_Types].xml", 'externalLink' not in ct)


def test_xlsx_sheet_comments_dropped():
    """XLSX xl/comments*.xml and xl/authors.xml are dropped."""
    with tempfile.TemporaryDirectory() as td:
        xlsx = os.path.join(td, 'comments.xlsx')
        with zipfile.ZipFile(xlsx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>'
                '<Override PartName="/xl/authors.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.commentsAuthors+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr('xl/_rels/workbook.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/commentAuthors" Target="authors.xml"/>'
                '</Relationships>')
            z.writestr('xl/workbook.xml',
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
            z.writestr('xl/comments1.xml',
                '<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<commentList><comment ref="A1" authorId="0"><text><t>Secret note</t></text></comment></commentList></comments>')
            z.writestr('xl/authors.xml',
                '<authors xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><author>John Smith</author></authors>')
        
        dst = os.path.join(td, 'clean.xlsx')
        rep = sanitize_file(xlsx, dst, Options())
        
        check("XLSX sheet comments cleaned", rep.ok)
        check("XLSX sheet comments reported as removed",
              any("xlsx sheet comment" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")
        
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_comments = any('comment' in n.lower() or 'author' in n.lower() for n in names)
            check("no comments/authors in output", not has_comments)
            
            rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8', errors='ignore')
            check("no comment ref in .rels", 'comment' not in rels.lower())


if __name__ == "__main__":
    test_pptx_speaker_notes_dropped()
    test_pptx_comments_dropped()
    test_xlsx_external_links_dropped()
    test_xlsx_sheet_comments_dropped()
    
    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
