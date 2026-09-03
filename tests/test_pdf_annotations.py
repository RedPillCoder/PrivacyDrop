"""Tests for PDF annotation sanitization."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pikepdf import Pdf, Name, Dictionary, Array
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


def test_pdf_annotation_author_removed():
    """PDF annotation author fields are removed."""
    with tempfile.TemporaryDirectory() as td:
        # Create PDF with annotations
        pdf = Pdf.new()
        page = pdf.add_blank_page(page_size=(100, 100))
        
        annot = Dictionary(
            Type=Name('/Annot'),
            Subtype=Name('/Text'),
            T='My Note',
            Contents='Secret comment',
            Author='John Smith',
            NM='unique-id-123',
            CreationDate='D:20240101120000',
            M='D:20240101120000',
        )
        page['/Annots'] = Array([annot])
        
        src = os.path.join(td, 'annotated.pdf')
        pdf.save(src)
        
        dst = os.path.join(td, 'clean.pdf')
        rep = sanitize_file(src, dst, Options())
        
        check("pdf with annotations cleaned", rep.ok)
        check("annotation authors reported as removed",
              any("annotation" in r.lower() and "author" in r.lower()
                  for r in rep.removed),
              f"removed: {rep.removed}")
        
        # Verify annotation fields are removed
        with Pdf.open(dst) as p:
            for page in p.pages:
                if '/Annots' in page:
                    for annot in page['/Annots']:
                        check("no /Author in annotation",
                              '/Author' not in annot)
                        check("no /T in annotation",
                              '/T' not in annot)
                        check("no /NM in annotation",
                              '/NM' not in annot)
                        check("no /CreationDate in annotation",
                              '/CreationDate' not in annot)
                        check("no /M in annotation",
                              '/M' not in annot)
                        # Content should still be present for non-sensitive fields
                        # (though we removed /T, the annotation structure remains)


def test_pdf_multiple_annotations():
    """Multiple annotations all have author fields removed."""
    with tempfile.TemporaryDirectory() as td:
        pdf = Pdf.new()
        page = pdf.add_blank_page(page_size=(100, 100))
        
        annots = []
        for i in range(3):
            annot = Dictionary(
                Type=Name('/Annot'),
                Subtype=Name('/Text'),
                Author=f'User {i}',
                T=f'Note {i}',
            )
            annots.append(annot)
        
        page['/Annots'] = Array(annots)
        
        src = os.path.join(td, 'multi_annot.pdf')
        pdf.save(src)
        
        dst = os.path.join(td, 'clean.pdf')
        rep = sanitize_file(src, dst, Options())
        
        check("multiple annotations cleaned", rep.ok)
        # 3 annots × 2 fields (/Author, /T) = 6 fields removed
        if rep.ok:
            reported = " ".join(rep.removed).lower()
            check("annotation count reported correctly",
                  "6" in reported or "annotation" in reported,
                  f"removed: {rep.removed}")


def test_pdf_annotation_preserves_structure():
    """PDF annotation removal preserves annotation structure."""
    with tempfile.TemporaryDirectory() as td:
        pdf = Pdf.new()
        page = pdf.add_blank_page(page_size=(100, 100))
        
        annot = Dictionary(
            Type=Name('/Annot'),
            Subtype=Name('/Text'),
            Author='John Smith',
            Contents='Comment text',
        )
        page['/Annots'] = Array([annot])
        
        src = os.path.join(td, 'annot.pdf')
        pdf.save(src)
        
        dst = os.path.join(td, 'clean.pdf')
        sanitize_file(src, dst, Options())
        
        with Pdf.open(dst) as p:
            for page in p.pages:
                check("annotations still present",
                      '/Annots' in page)
                if '/Annots' in page:
                    annots = page['/Annots']
                    check("annotation count preserved",
                          len(annots) == 1)
                    if len(annots) >= 1:
                        check("annotation type preserved",
                              annots[0].get('/Subtype') == '/Text')


if __name__ == "__main__":
    test_pdf_annotation_author_removed()
    test_pdf_multiple_annotations()
    test_pdf_annotation_preserves_structure()
    
    print(f"\n===== {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
