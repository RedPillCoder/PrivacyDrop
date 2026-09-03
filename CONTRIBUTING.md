# Contributing to PrivacyDrop

Thanks for your interest!  PrivacyDrop is a privacy tool, so contributions
that improve security, reliability or transparency are especially welcome.

## Before you start

- Read the [Privacy guarantees](README.md#-privacy-guarantees) section.
  Any change that weakens them will not be accepted.
- Check existing [issues](https://github.com/privacypdrop/privacypdrop/issues)
  and [pull requests](https://github.com/privacypdrop/privacypdrop/pulls)
  to avoid duplicating work.

## How to contribute

### Bug reports

Use the issue template (if one exists) or include:

1. **PrivacyDrop version** (`About` dialog or `python -c "from version import APP_VERSION; print(APP_VERSION)"`)
2. **Windows version** (run `winver`)
3. **Steps to reproduce** — ideally a small sample file that triggers the bug
4. **Expected vs. actual behaviour**
5. Whether the original file was modified (it never should be)

### Feature requests

Describe *what* you want and *why*.  For privacy-related features, explain
the threat model.  Keep scope small — PrivacyDrop's value is in doing one
thing well.

### Code changes

1. **Fork** the repo and create a branch from `main` (`fix/exif-crash`,
   `feature/heic-drag`, etc.).
2. **Add or update tests** — every new behaviour must be covered.  The CI
   runs on Python 3.10–3.13; your code must work on all of them.
3. **Run the full suite locally** before pushing:
   ```bash
   pip install -r requirements-dev.txt
   python -m tests.test_engine
   python -m tests.test_full
   python -m tests.test_security
   python -m tests.test_privacy
   python -m tests.test_app_features
   ```
4. **Open a PR** with a clear description.  Link any related issue.

## Coding style

- **Plain Python** — no external linters or formatters required.  Follow
  what's already in `scrubber.py` and `app.py` (4-space indent, explicit
  is better than implicit, defensive by default).
- **Type hints** on public functions and dataclasses.
- **Docstrings** on every public function, class and module.
- **No `eval`, `exec`, or dynamic import** of untrusted data — ever.
- **Never parse untrusted XML** — use regex scan + template replacement
  (see the Office sanitisation code for the pattern).

## Security contributions

If you find a vulnerability, **do not open a public issue**.  Email
`security@privacypdrop.example` (replace with the real address once the
project has one) with:

- A description of the issue
- Steps / sample file to reproduce
- Suggested fix (optional)

You'll get a response within 72 hours.

## Versioning & releases

See the "Releases" section of the [README](README.md#-releases).  In short:

1. Bump `VERSION` and `version.py`
2. Update `CHANGELOG.md`
3. Tag `vX.Y.Z` and push
4. CI drafts the GitHub Release — review and publish

## Code of conduct

Be kind, be constructive, respect people's time.  This is a small project
maintained in free time.
