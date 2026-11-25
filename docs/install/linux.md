[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › [Install](README.md) › Linux

# Linux

Install the `dsd-upsample` command on Linux x86_64, from crates.io or from a
release archive.

## From crates.io

With Rust 1.83 or later:

```sh
cargo install dsd-upsample-cli
```

This builds the command and puts it in `~/.cargo/bin`. With Rust from rustup that folder is
already on your `PATH`; with a distribution's Rust (for example Fedora's `cargo` package), add
`~/.cargo/bin` to your `PATH` first.

## From a release archive

The [releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases) has a `.tar.gz` for
`x86_64-unknown-linux-gnu` with a `.sha256` file and a build provenance attestation.
Download both files, check the sum, check the attestation (needs the
[GitHub CLI](https://cli.github.com/)), extract the archive and run the command:

```sh
curl -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.0/dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz
curl -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.0/dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz.sha256
sha256sum -c dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz.sha256
gh attestation verify dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz --repo dsd-toolbox/dsd-upsample-rs
tar -xzf dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz
dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu/dsd-upsample --version
```

`sha256sum -c` prints `dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu.tar.gz: OK`, and the last
line prints `dsd-upsample 0.1.0`. The archive unpacks into one folder,
`dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu/`, which holds:

| Path | Contents |
|---|---|
| `dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu/` | The folder everything below is in |
| `dsd-upsample` | The command |
| `lib/` | `libdsd_upsample.so.1` (with a `libdsd_upsample.so` link) and `libdsd_upsample.a` |
| `lib/pkgconfig/dsd_upsample.pc` | pkg-config file, with paths relative to its own location |
| `include/dsd_upsample.h` | C header |
| `README.md`, `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE` | Documentation, licences and notices |

Put `dsd-upsample` in a folder on your `PATH`, for example:

```sh
mkdir -p ~/.local/bin
cp dsd-upsample-v0.1.0-x86_64-unknown-linux-gnu/dsd-upsample ~/.local/bin/
```

RHEL 9 and Ubuntu (for a regular user, not root) add `~/.local/bin` to your `PATH` at login once
the folder exists; elsewhere, add it yourself. Log out and in again (or open a new terminal), then
check with `dsd-upsample --version`.

The archives are built on Ubuntu 24.04 and need glibc 2.34 or later (RHEL 9, Debian 12,
Ubuntu 22.04 and later distributions): the newest symbol version the command and the
library use is `GLIBC_2.34` (measured with `objdump -T` on builds made
as the release workflow makes them). On an older system, build from crates.io instead.

## Tested

Linux x86_64 at 0.1.0; aarch64 follows when our ARM test machine arrives.

## See also

- [Install](README.md)
- [User guide](../user-guide.md)
- [C interface](../c-api.md)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
