[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › Install

# Install

Which way to install dsd-upsample on which system. Every release is on the
[releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases), with SHA-256 sums and
build provenance attestations.

## Choose a guide

| System | How | Guide |
|---|---|---|
| Linux, x86_64 | Release archive (`.tar.gz`, glibc 2.34 or later) with the CLI and the C library; `cargo install dsd-upsample-cli` | [Linux](linux.md) |
| macOS, Apple Silicon and Intel (Intel: built, not run in our tests) | Universal release archive (`.zip`, signed and notarised) with the CLI and the C library; `cargo install dsd-upsample-cli` | [macOS](macos.md) |
| Windows 11, x64 | Release `.zip` (not code-signed yet, named `-unsigned`) with the CLI and the C library; `cargo install dsd-upsample-cli` | [Windows](windows.md) |
| Any of these, as a library | Rust crate `dsd-upsample`, C library `libdsd_upsample` | [Packages](packages.md) |

macOS and Windows x64: the full test suite and golden hashes on GitHub's runners (macOS 15
arm64, Windows Server 2025), and each release in a Windows 11 and a macOS virtual machine. The
Intel half of the macOS archive is built but not run in our tests; Windows 10 is not tested.
Linux aarch64 follows when our ARM test machine arrives; Windows on ARM once tested on ARM64
Windows.

## See also

- [User guide](../user-guide.md)
- [Options](../options.md)
- [Release process](../release.md): how the archives are built and signed

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
