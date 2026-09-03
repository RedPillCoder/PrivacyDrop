#!/usr/bin/env bash
# =========================================================================
# PrivacyDrop — release build orchestrator (Linux / macOS / WSL)
#
# Usage:
#   ./build_release.sh            # full release (tests + exe + zips + sums)
#   ./build_release.sh --skip-exe # skip the Wine/PyInstaller stage
#   ./build_release.sh --version  # print version and exit
#
# Produces (under release/):
#   PrivacyDrop-<ver>-Setup.exe       (NSIS installer, if makensis available)
#   PrivacyDrop-<ver>-portable.zip    (portable app, no install needed)
#   PrivacyDrop-<ver>-source.zip      (full source + tests + docs)
#   SHA256SUMS                        (checksums for every artifact)
#   manifest.json                     (machine-readable release metadata)
# =========================================================================
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(cat VERSION | tr -d '[:space:]')"
RELEASE_DIR="release/${VERSION}"
PROJECT="PrivacyDrop"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[info]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

if [[ "${1:-}" == "--version" ]]; then
    echo "$VERSION"; exit 0
fi

# ---- 0. sanity checks ---------------------------------------------------
info "Building ${PROJECT} v${VERSION}"
[[ -f app.py       ]] || fail "app.py not found — run from project root"
[[ -f scrubber.py  ]] || fail "scrubber.py not found"
[[ -f version.py   ]] || fail "version.py not found"
[[ -f VERSION      ]] || fail "VERSION not found"

# Verify version consistency across files
PY_VER="$(python3 -c 'from version import APP_VERSION; print(APP_VERSION)')"
[[ "$PY_VER" == "$VERSION" ]] || fail "version.py (${PY_VER}) != VERSION (${VERSION})"
grep -q "\"${VERSION}\"" app.py && warn "app.py still hardcodes version ${VERSION} — should import from version.py"

# ---- 1. tests -----------------------------------------------------------
info "Step 1/5 — running test suite..."
python3 -m pip install -q -r requirements-dev.txt 2>/dev/null

# Detect whether we can run GUI tests (need Xvfb on headless systems).
RUN_GUI=0
if [ -n "${DISPLAY:-}" ] || command -v xvfb-run &>/dev/null; then
    RUN_GUI=1
fi
[[ $RUN_GUI -eq 1 ]] && info "  GUI tests enabled" || warn "  No display found — GUI tests will be skipped"

FAILED=0
for t in tests/test_engine.py tests/test_full.py tests/test_security.py \
         tests/test_privacy.py; do
    if python3 "$t" >/dev/null 2>&1; then
        echo "  ✓  $(basename "$t")"
    else
        echo "  ✗  $(basename "$t")  ← FAIL"
        FAILED=1
    fi
done

# GUI test — only if we have a display or xvfb-run
if [[ $RUN_GUI -eq 1 ]]; then
    if python3 tests/test_app_features.py >/dev/null 2>&1; then
        echo "  ✓  test_app_features.py"
    else
        # Retry under xvfb-run if direct run failed (common on CI)
        if command -v xvfb-run &>/dev/null && xvfb-run -a python3 tests/test_app_features.py >/dev/null 2>&1; then
            echo "  ✓  test_app_features.py (xvfb)"
        else
            echo "  ✗  test_app_features.py  ← FAIL"
            FAILED=1
        fi
    fi
else
    echo "    test_app_features.py  (skipped — no display)"
fi
[[ $FAILED -eq 0 ]] || fail "Tests failed — aborting release build"
info "All tests passed."

# ---- 2. build Windows exe (requires Wine + PyInstaller) -----------------
SKIP_EXE=0
[[ "${1:-}" == "--skip-exe" ]] && SKIP_EXE=1

if [[ $SKIP_EXE -eq 0 ]]; then
    info "Step 2/5 — building Windows exe..."

    if command -v wine &>/dev/null && command -v pyinstaller &>/dev/null; then
        # Native PyInstaller (Linux build — produces Linux binary, not useful here)
        warn "Native pyinstaller found — this builds a Linux binary, not Windows."
        warn "For a Windows exe, run build_windows.bat on Windows, or set up Wine."
        SKIP_EXE=1
    fi

    if [[ $SKIP_EXE -eq 1 ]]; then
        if command -v wine &>/dev/null; then
            info "Building under Wine..."
            wine cmd /c "build_windows.bat" 2>/dev/null || warn "Wine build failed — portable zip will still be created"
        else
            warn "Wine not found — skipping exe build. Install Wine for cross-build."
        fi
    fi
else
    info "Step 2/5 — skipping exe build (--skip-exe)"
fi

# ---- 3. assemble artifacts ----------------------------------------------
info "Step 3/5 — assembling artifacts..."
mkdir -p "$RELEASE_DIR"

# Portable zip (exe + licence + readme + changelog)
if [[ -f dist/PrivacyDrop.exe ]]; then
    (cd dist && zip -9 -j "../${RELEASE_DIR}/${PROJECT}-${VERSION}-portable.zip" \
        PrivacyDrop.exe ../LICENSE ../README.md ../CHANGELOG.md)
    info "  Created portable zip ($(du -h "${RELEASE_DIR}/${PROJECT}-${VERSION}-portable.zip" | cut -f1))"
else
    warn "  dist/PrivacyDrop.exe not found — portable zip will contain source only"
    (zip -9 -j "${RELEASE_DIR}/${PROJECT}-${VERSION}-portable.zip" \
        LICENSE README.md CHANGELOG.md)
fi

# Source zip (everything except .venv, __pycache__, dist, release, test tmp dirs)
(zip -9 -r "${RELEASE_DIR}/${PROJECT}-${VERSION}-source.zip" . \
    -x ".venv/*" "__pycache__/*" "dist/*" "release/*" \
       "tests/tmp*" ".git/*" ".gitignore" \
       "*.pyc" "*.pyo" \
       "assets/icon_src.png"  # keep only the final icon
)
info "  Created source zip ($(du -h "${RELEASE_DIR}/${PROJECT}-${VERSION}-source.zip" | cut -f1))"

# ---- 4. NSIS installer (if makensis available) --------------------------
info "Step 4/5 — building installer..."
if command -v makensis &>/dev/null && [[ -f dist/PrivacyDrop.exe ]]; then
    makensis installer.nsi 2>/dev/null
    if [[ -f "dist/${PROJECT}-${VERSION}-Setup.exe" ]]; then
        cp "dist/${PROJECT}-${VERSION}-Setup.exe" "${RELEASE_DIR}/"
        info "  Created installer ($(du -h "${RELEASE_DIR}/${PROJECT}-${VERSION}-Setup.exe" | cut -f1))"
    else
        warn "  makensis ran but exe not produced"
    fi
else
    warn "  makensis not found or no exe — installer.nsi is ready to build on Windows"
fi

# ---- 5. checksums + manifest --------------------------------------------
info "Step 5/5 — checksums & manifest..."
(cd "$RELEASE_DIR" && sha256sum * 2>/dev/null | tee ../SHA256SUMS)

cat > "${RELEASE_DIR}/manifest.json" <<EOF
{
  "product": "${PROJECT}",
  "version": "${VERSION}",
  "date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "artifacts": [
$(cd "$RELEASE_DIR" && for f in *.zip *.exe; do
    [[ -f "$f" ]] || continue
    HASH=$(sha256sum "$f" | cut -d' ' -f1)
    SIZE=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
    echo "    {\"file\": \"$f\", \"sha256\": \"$HASH\", \"size\": $SIZE},"
done | sed '$ s/,$//')
  ],
  "python_version": "$(python3 --version 2>&1)",
  "tests_passing": true
}
EOF
info "  Created manifest.json"

# ---- done ---------------------------------------------------------------
echo
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ${PROJECT} v${VERSION} — release artifacts              ║"
echo "══════════════════════════════════════════════════════════╣"
echo "║  $(ls -1 "$RELEASE_DIR" | sed 's/^/║  /' | sed 's/$/          /' | cut -c1-56)"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  SHA256SUMS:  release/SHA256SUMS                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo
info "Done. Upload contents of ${RELEASE_DIR}/ to GitHub Releases."
