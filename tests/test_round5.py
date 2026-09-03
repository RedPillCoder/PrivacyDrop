"""Tests for round 5 privacy improvements: DOCX comments and track changes."""

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
# DOCX comments and track changes
# ---------------------------------------------------------------------------

def test_docx_comments_dropped():
    """Word comments.xml and commentAuthors.xml are dropped."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'review.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                '<Override PartName="/word/commentAuthors.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.commentAuthors+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/_rels/document.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('word/comments.xml',
                '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:comment w:id="0" w:author="John Smith" w:date="2024-08-15T10:30:00Z">'
                '<w:p><w:r><w:t>Review comment</w:t></w:r></w:p></w:comment></w:comments>')
            z.writestr('word/commentAuthors.xml',
                '<w:commentAuthors xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:author>John Smith</w:author></w:commentAuthors>')

        dst = os.path.join(td, 'review_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("comments docx cleaned", rep.ok)
        check("comments reported as removed",
              any("comment" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        # Verify comments.xml and commentAuthors.xml are gone
        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_comments = any('comments.xml' in n.lower() for n in names)
            has_authors = any('commentauthors' in n.lower() for n in names)
            check("no comments.xml in output", not has_comments)
            check("no commentAuthors.xml in output", not has_authors)

        # Verify PII is gone
        with open(dst, 'rb') as f:
            data = f.read()
        check("no PII in cleaned output",
              b'John Smith' not in data and b'Review comment' not in data)


def test_docx_track_changes_stripped():
    """Track change author attributes (w:author, w:date) are stripped."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'tracked.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>'
                '<w:p><w:del w:id="1" w:author="John Smith" w:date="2024-08-15T10:30:00Z">'
                '<w:r><w:t>deleted text</w:t></w:r></w:del>'
                '<w:ins w:id="2" w:author="Jane Doe" w:date="2024-08-15T11:00:00Z">'
                '<w:r><w:t>inserted text</w:t></w:r></w:ins></w:p>'
                '</w:body></w:document>')

        dst = os.path.join(td, 'tracked_clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("track changes docx cleaned", rep.ok)
        check("track changes reported as removed",
              any("track-change" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        # Verify author attributes are stripped
        with zipfile.ZipFile(dst, 'r') as z:
            doc_data = z.read('word/document.xml').decode('utf-8', errors='ignore')
            check("no w:author in document.xml",
                  'w:author' not in doc_data,
                  f"found in: {doc_data[:300]}")
            check("no w:date in document.xml",
                  'w:date' not in doc_data,
                  f"found in: {doc_data[:300]}")
            # Content should still be present
            check("deleted text content preserved",
                  'deleted text' in doc_data)
            check("inserted text content preserved",
                  'inserted text' in doc_data)

        # Verify PII is gone
        with open(dst, 'rb') as f:
            data = f.read()
        check("no author names in output",
              b'John Smith' not in data and b'Jane Doe' not in data)


def test_docx_comment_ranges_stripped():
    """Comment range markers (w:commentRangeStart/End/Reference) are stripped."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'ranges.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>'
                '<w:p><w:commentRangeStart w:id="0"/>'
                '<w:r><w:t>commented text</w:t></w:r>'
                '<w:commentRangeEnd w:id="0"/>'
                '<w:commentReference w:id="0"/>'
                '</w:p></w:body></w:document>')

        dst = os.path.join(td, 'ranges_clean.docx')
        sanitize_file(docx, dst, Options())

        # Verify comment range markers are stripped
        with zipfile.ZipFile(dst, 'r') as z:
            doc_data = z.read('word/document.xml').decode('utf-8', errors='ignore')
            check("no commentRangeStart in output",
                  'commentRangeStart' not in doc_data)
            check("no commentRangeEnd in output",
                  'commentRangeEnd' not in doc_data)
            check("no commentReference in output",
                  'commentReference' not in doc_data)
            # Content should still be present
            check("commented text content preserved",
                  'commented text' in doc_data)


def test_docx_comment_refs_stripped_from_rels():
    """Comment references are stripped from .rels files."""
    from scrubber import sanitize_file, Options

    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'rels.docx')
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
            z.writestr('word/_rels/document.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')

        dst = os.path.join(td, 'rels_clean.docx')
        sanitize_file(docx, dst, Options())

        # Verify comment reference is stripped from .rels
        with zipfile.ZipFile(dst, 'r') as z:
            rels_data = z.read('word/_rels/document.xml.rels').decode('utf-8', errors='ignore')
            check("no comments reference in .rels",
                  'comments' not in rels_data.lower(),
                  f"found in: {rels_data[:300]}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_docx_comments_dropped()
    test_docx_track_changes_stripped()
    test_docx_comment_ranges_stripped()
    test_docx_comment_refs_stripped_from_rels()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
