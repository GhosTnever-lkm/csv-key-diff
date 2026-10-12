## 0.1.4 - 2026-10-12

- Synchronize package, CLI, and `VERSION` metadata after detecting that `--version` lagged behind the published release.
- Add metadata regression tests and make the release workflow reject a tag that does not match the package version.
- Pin GitHub Actions dependencies and publish release assets with the GitHub CLI.

## 0.1.3 - 2026-10-11

- Fix tests on Windows: fixture CSVs are now written with `newline=""`, so quoted LF line breaks inside fields are not translated to CRLF.


## 0.1.2 - 2026-10-11

- CI now also runs the test suite on Windows (windows-latest), not only Ubuntu.


## 0.1.1 - 2026-10-11

- Add build, release, and license badges to the README; publish package version through `--version`.

# Changelog

## 0.1.0 - 2026-10-11

- Initial release: compare CSV rows by a unique key and report added, removed, changed, and unchanged records.
- Support deterministic JSON/Markdown, bounded local inputs, duplicate-key/schema validation, and CI-friendly exit codes.
