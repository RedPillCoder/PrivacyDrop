"""Tests for round 7 privacy improvements: digital signatures,
commentsExtended/commentsIds, PDF AcroForm /TU /TM, PDF outline /NM."""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pikepdf
    from pikepdf import Pdf, Name, Dictionary, Array
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

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


def test_ooxml_comments_extended_dropped():
    """commentsExtended.xml and commentsIds.xml are dropped with comments.xml."""
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 't.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                '<Override PartName="/word/commentsExtended.xml" ContentType="application/vnd.ms-word.commentsExtended+xml"/>'
                '<Override PartName="/word/commentsIds.xml" ContentType="application/vnd.ms-word.commentsIds+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            z.writestr('word/_rels/document.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.microsoft.com/office/word/2010/wordprocessingml/commentsExtended" Target="commentsExtended.xml"/>'
                '<Relationship Id="rId4" Type="http://schemas.microsoft.com/office/word/2010/wordprocessingml/commentsIds" Target="commentsIds.xml"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('word/comments.xml',
                '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:comment w:id="0" w:author="John Smith">'
                '<w:p><w:r><w:t>Hi</w:t></w:r></w:p></w:comment></w:comments>')
            z.writestr('word/commentsExtended.xml',
                '<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
                '<w15:commentEx w15:done="0" w15:paraId="abc"/></w15:commentsEx>')
            z.writestr('word/commentsIds.xml',
                '<w14:commentRangeStart w14:paraId="abc" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"/>')

        dst = os.path.join(td, 'clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("commentsExtended docx cleaned", rep.ok)
        check("extended comment metadata reported",
              any("extended comment" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_ce = any('commentsExtended' in n.lower() for n in names)
            has_ci = any('commentsIds' in n.lower() for n in names)
            check("no commentsExtended in output", not has_ce)
            check("no commentsIds in output", not has_ci)

            rels = z.read('word/_rels/document.xml.rels').decode('utf-8', errors='ignore')
            check("no comments ref in .rels",
                  'commentsExtended' not in rels and 'commentsIds' not in rels)


def test_office_digital_signatures_dropped():
    """_xmlsignatures/ directory and references are dropped."""
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, 'signed.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('[Content_Types].xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '<Override PartName="/_xmlsignatures/sig1.xml" ContentType="application/vnd.openxmlformats.package.digital-signature-xmlsignature+xml"/>'
                '</Types>')
            z.writestr('_rels/.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/digital-signature/origin" Target="_xmlsignatures/origin.sigs"/>'
                '</Relationships>')
            z.writestr('word/document.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>')
            z.writestr('_xmlsignatures/sig1.xml',
                '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">'
                '<KeyInfo><X509Data><X509IssuerName>CN=John Smith</X509IssuerName></X509Data></KeyInfo></Signature>')

        dst = os.path.join(td, 'clean.docx')
        rep = sanitize_file(docx, dst, Options())

        check("signed docx cleaned", rep.ok)
        check("digital signatures reported as removed",
              any("signature" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        with zipfile.ZipFile(dst, 'r') as z:
            names = z.namelist()
            has_sigs = any('_xmlsignatures' in n.lower() for n in names)
            check("no _xmlsignatures in output", not has_sigs)

            rels = z.read('_rels/.rels').decode('utf-8', errors='ignore')
            check("no sig ref in .rels",
                  'digital-signature' not in rels.lower())


def test_pdf_acroform_tu_tm_stripped():
    """PDF AcroForm /TU (tooltip) and /TM (mapping name) are stripped."""
    if not HAS_PIKEPDF:
        print("  SKIP  pikepdf not available")
        return

    with tempfile.TemporaryDirectory() as td:
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        pdf.Root[Name('/AcroForm')] = Dictionary(Fields=Array([
            Dictionary(Type=Name('/Annot'), Subtype=Name('/Widget'),
                       FT=Name('/Tx'), T='Name',
                       V='John Smith', TU='Full legal name', TM='field_name'),
        ]))

        src = os.path.join(td, 'form.pdf')
        pdf.save(src)

        dst = os.path.join(td, 'clean.pdf')
        rep = sanitize_file(src, dst, Options())

        check("form with /TU /TM cleaned", rep.ok)
        check("/TU /TM reported as cleared",
              any("form field" in r.lower() for r in rep.removed),
              f"removed: {rep.removed}")

        with Pdf.open(dst) as p:
            af = p.Root.get(Name('/AcroForm'))
            if af:
                for field in af[Name('/Fields')]:
                    check("no /TU in output", Name('/TU') not in field)
                    check("no /TM in output", Name('/TM') not in field)
                    check("no /V in output", Name('/V') not in field)


def test_pdf_outline_nm_stripped():
    """PDF outline/bookmark /NM fields are stripped; /Title preserved."""
    if not HAS_PIKEPDF:
        print("  SKIP  pikepdf not available")
        return

    with tempfile.TemporaryDirectory() as td:
        pdf = Pdf.new()
        page = pdf.add_blank_page(page_size=(100, 100))
        child = Dictionary(Title='Section 1', NM='bm-id-2',
                           Dest=Array([page.obj, Name('/Fit')]))
        root = Dictionary(Type=Name('/Outlines'), Title='Chapter 1',
                          NM='bm-id-1', First=child,
                          Dest=Array([page.obj, Name('/Fit')]))
        pdf.Root[Name('/Outlines')] = root

        src = os.path.join(td, 'bookmarked.pdf')
        pdf.save(src)

        dst = os.path.join(td, 'clean.pdf')
        rep = sanitize_file(src, dst, Options())

        check("bookmarked PDF cleaned", rep.ok)
        check("outline fields reported as removed",
              any("bookmark" in r.lower() or "outline" in r.lower()
                  for r in rep.removed),
              f"removed: {rep.removed}")

        with Pdf.open(dst) as p:
            outlines = p.Root.get(Name('/Outlines'))
            if outlines:
                check("no /NM on outline root", Name('/NM') not in outlines)
                check("/Title preserved on root", Name('/Title') in outlines)
                first = outlines.get(Name('/First'))
                if first:
                    check("no /NM on first child", Name('/NM') not in first)
                    check("/Title preserved on child", Name('/Title') in first)


if __name__ == "__main__":
    test_ooxml_comments_extended_dropped()
    test_office_digital_signatures_dropped()
    test_pdf_acroform_tu_tm_stripped()
    test_pdf_outline_nm_stripped()

    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
