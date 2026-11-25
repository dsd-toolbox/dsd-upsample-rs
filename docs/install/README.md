[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › Install

# Install

Which way to install dsd-upsample on which system. Every release is on the
[releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases), with SHA-256 sums and
build provenance attestations.

## Choose a guide

| System | How | Guide |
|---|---|---|
| Linux, x86_64 | Release archive (`.tar.gz`, glibc 2.34 or later) with the CLI and the C library; `cargo install dsd-upsample-cli` | [Linux](linux.md) |
| Linux, as a library | Rust crate `dsd-upsample`, C library `libdsd_upsample` | [Packages](packages.md) |

Linux x86_64 at 0.1.0; aarch64 follows when our ARM test machine arrives. Windows and macOS
follow in a later release.

## See also

- [User guide](../user-guide.md)
- [Options](../options.md)
- [Release process](../release.md): how the archives are built

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
