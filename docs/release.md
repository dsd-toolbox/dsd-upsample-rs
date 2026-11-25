[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Release process

# Release process

The maintainer's steps to publish a release, and where its builds go. The
process shared by all DSD Toolbox projects is in
[dsd-toolbox: CI/CD](https://github.com/dsd-toolbox/dsd-toolbox/blob/main/docs/ci-cd.md).

## Making a release

1. CI green on main; `docs/measurements.md` current (`python tools/measure_suite.py`).
2. Bump the workspace version, update `CHANGELOG.md` (the release notes come from it: the
   `## X.Y.Z - YYYY-MM-DD` section, dated, not `LAUNCH-DATE`), tag `vX.Y.Z` and push the
   tag. `.github/workflows/release.yml` then:
   - on `ubuntu-24.04` (x86_64), checks that `CHANGELOG.md` has that section
     (`.github/scripts/release-notes.sh`), runs the full test suite
     in release natively, golden hashes included, then builds the CLI and the C library,
     checks the glibc floor (2.34) and packages a `.tar.gz` with its `.sha256`;
   - in the `publish` job (environment `release`, tag pushes only), checks the sums, adds
     build provenance attestations and creates a draft release with the notes from that
     section; it stops if the section is missing, empty or undated.
3. Check the draft and publish it, then `cargo publish -p dsd-upsample` and
   `cargo publish -p dsd-upsample-cli`.

A manual run of the workflow (workflow_dispatch) is a dry run: it builds and tests the
archive and keeps it as a workflow artifact; it never creates a release. It accepts
`LAUNCH-DATE` in the `CHANGELOG.md` section; a tag does not. CI checks on pushes to main and on
pull requests that the section for the workspace version exists and is not empty.

Actions are pinned to commit SHAs, and the Rust toolchain comes from rustup at the version in
`RUST_STABLE`. The workflow reads no signing secrets; the `release` environment has required
reviewers.

## Distribution

- **Linux (0.1.0):** the release archive for x86_64 (glibc 2.34 or later) and
  `cargo install dsd-upsample-cli`.
- Windows and macOS follow in a later release.

## See also

- [Install guides](install/README.md)
- [Measurements](measurements.md): refreshed before each release
- [Releases](https://github.com/dsd-toolbox/dsd-upsample-rs/releases)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
