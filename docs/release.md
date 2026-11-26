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
   - on `macos-15`, runs the full test suite in release (arm64) and builds a universal (arm64
     and x86_64) CLI and library; this job has no environment and no secrets, and it hands
     the unsigned files to the next job with a SHA-256 manifest;
   - in `macos-sign`, checks those files against the manifest, signs and notarises them and
     packages a `.zip`, with no checkout and no build; without its signing secrets the job
     fails rather than ship an unsigned macOS binary;
   - on `windows-2025`, runs the full test suite in release and builds the x86_64 CLI and
     library, again with no environment and no secrets. With the repository variable
     `WINDOWS_SIGNING` set to `off`, it packages the unsigned `.zip`, named `-unsigned`
     (`dsd-upsample-vX.Y.Z-unsigned-x86_64-pc-windows-msvc.zip`). With `required` (the
     default), `windows-sign` takes the files with their manifest, signs them with SSL.com
     eSigner (cloud signing; the `ES_*` secrets; missing secrets fail the job), checks each
     signature, its timestamp and the signer against the repository variable
     `WINDOWS_SIGNER_THUMBPRINT`, and packages the `.zip`. Windows on ARM is not built;
   - in the `publish` job (environment `release`, tag pushes only, after the build and
     signing jobs), checks the sums, adds
     build provenance attestations and creates a draft release with the notes from that
     section; it stops if the section is missing, empty or undated.
3. Check the draft and publish it, then `cargo publish -p dsd-upsample` and
   `cargo publish -p dsd-upsample-cli`.

A manual run of the workflow (workflow_dispatch) is a dry run: it builds and tests every
platform and keeps the archives as workflow artifacts, the macOS and Windows ones unsigned and
named `-UNSIGNED`; it never creates a release. It accepts
`LAUNCH-DATE` in the `CHANGELOG.md` section; a tag does not. CI checks on pushes to main and on
pull requests that the section for the workspace version exists and is not empty.

Actions are pinned to commit SHAs, and the Rust toolchain comes from rustup at the version in
`RUST_STABLE`. Signing secrets live in the GitHub environment `release` (required reviewers).
Only the signing jobs and `publish` enter it, and only on a tag push, so a dry run reads no
environment secret; the names are at the top of `release.yml`.

## Distribution

- **Linux:** the release archive for x86_64 (glibc 2.34 or later) and
  `cargo install dsd-upsample-cli`.
- **macOS:** the universal release archive, signed and notarised, and `cargo install`. Never
  an unsigned macOS binary: Gatekeeper holds a quarantined unsigned binary behind a dialog.
- **Windows:** the x64 release zip (not code-signed yet, so no `.exe` installer for browser
  download) and `cargo install`. Until the project's code-signing certificate is in place,
  releases are made with the repository variable `WINDOWS_SIGNING` set to `off`: the zips are
  named `-unsigned`, and the install guide leads with the SHA-256 check.

## See also

- [Install guides](install/README.md)
- [Measurements](measurements.md): refreshed before each release
- [Releases](https://github.com/dsd-toolbox/dsd-upsample-rs/releases)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
