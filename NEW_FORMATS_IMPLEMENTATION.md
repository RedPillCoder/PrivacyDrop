# PrivacyDrop New Formats Implementation

## Summary
Added support for **SVG**, **AVIF**, and **ODF** (ODT/ODS/ODP) formats to PrivacyDrop's metadata sanitization engine.

## Formats Added

### 1. SVG (Scalable Vector Graphics)
- **Extensions**: `.svg`
- **Method**: Text-level regex-based sanitization (lossless)
- **What's removed**:
  - `<metadata>` blocks (Dublin Core, RDF, etc.)
  - XML comments (can contain sensitive info)
  - `<script>` blocks (JavaScript/XSS vectors)
  - Editor-specific metadata (Inkscape, Illustrator, Adobe)
- **Preserved**: Visual content, structure, styling

### 2. AVIF (AV1 Image File Format)
- **Extensions**: `.avif`
- **Method**: Re-encoding via Pillow (requires Pillow 10+)
- **What's removed**: EXIF, XMP, ICC profiles (via re-encode)
- **Notes**: Next-gen image format, growing adoption

### 3. ODF (OpenDocument Format)
- **Extensions**: `.odt` (text), `.ods` (spreadsheet), `.odp` (presentation)
- **Method**: ZIP/XML sanitization (same pattern as OOXML)
- **What's removed**:
  - `meta.xml` identity metadata (creator, dates, title, description)
  - Thumbnails directory
  - Basic/ scripts directory (LibreOffice macros)
- **Preserved**: Document content, styles, settings

## Implementation Details

### Code Changes

**scrubber.py**:
1. Added `.svg` and `.avif` to `IMAGE_EXTS`
2. Added `.odt`, `.ods`, `.odp` to `DOC_EXTS`
3. Added `strip_svg_bytes()` function with regex patterns for:
   - Metadata blocks
   - Comments
   - Scripts
   - Editor-specific metadata
4. Added SVG handling to `sanitize_image()` dispatcher
5. Added AVIF to re-encode format map
6. Added `sanitize_opendocument()` function for ODF files
7. Updated `sanitize_file()` dispatcher to handle ODF extensions

### Testing

**New test file**: `tests/test_new_formats.py` (21 tests, all passing)

**Test coverage**:
- SVG metadata removal (9 tests)
- SVG invalid file handling (1 test)
- AVIF cleaning (1 test)
- ODF metadata removal (8 tests)
- Format support verification (3 tests)

**Existing test suites**: All pass without modification
- test_engine.py: 29 tests ✓
- test_full.py: 84 tests ✓
- test_security.py: 49 tests ✓
- test_privacy.py: 58 tests ✓
- test_app_features.py: 47 tests ✓
- test_new_formats.py: 21 tests ✓ (NEW)

**Total**: 288 tests passing

## Usage Examples

### SVG
```bash
python scrubber.py diagram.svg --out cleaned/
# Output: cleaned/diagram_clean.svg (metadata/comments/scripts removed)
```

### AVIF
```bash
python scrubber.py photo.avif --out cleaned/
# Output: cleaned/photo_clean.avif (EXIF/XMP removed via re-encode)
```

### ODF
```bash
python scrubber.py document.odt --out cleaned/
# Output: cleaned/document_clean.odt (meta.xml sanitized)

python scrubber.py spreadsheet.ods --out cleaned/
python scrubber.py presentation.odp --out cleaned/
```

## Privacy Impact

These formats commonly leak:
- **SVG**: Author names, project metadata, editor info, creation dates
- **AVIF**: GPS coordinates, camera/device info, timestamps (same as JPEG/HEIC)
- **ODF**: Author names, editing history, document statistics, macro code

## Compatibility Notes

- **SVG**: Works on all systems (text-based processing)
- **AVIF**: Requires Pillow 10+ with AVIF support (libavif)
- **ODF**: Works on all systems (ZIP/XML processing)

## Future Enhancements

Potential improvements:
1. SVG embedded image metadata scrubbing (data: URIs with EXIF)
2. ODF track changes and comments removal (similar to OOXML)
3. AVIF lossless cleaning (if AVIF spec allows metadata stripping without re-encode)

## Files Modified

- `scrubber.py` - Core sanitization engine
- `tests/test_new_formats.py` - New test suite (21 tests)

## Files Created

- `NEW_FORMATS_IMPLEMENTATION.md` - This document
