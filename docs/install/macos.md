[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › [Install](README.md) › macOS

# macOS

Install dsd-upsample on macOS, Apple Silicon or Intel: the `dsd-upsample` command and the C
library.

## Release archive

The [releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases) has a universal
(arm64 and x86_64) `.zip`, signed and notarised, with a `.sha256` file and a build provenance
attestation. In Terminal, download both files, check the sum, check the attestation (needs the
[GitHub CLI](https://cli.github.com/)), unpack the archive and run the command:

```sh
curl -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.1/dsd-upsample-v0.1.1-macos-universal.zip
curl -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.1/dsd-upsample-v0.1.1-macos-universal.zip.sha256
shasum -a 256 -c dsd-upsample-v0.1.1-macos-universal.zip.sha256
gh attestation verify dsd-upsample-v0.1.1-macos-universal.zip --repo dsd-toolbox/dsd-upsample-rs
ditto -x -k dsd-upsample-v0.1.1-macos-universal.zip .
dsd-upsample-v0.1.1-macos-universal/dsd-upsample --version
```

`shasum` prints `dsd-upsample-v0.1.1-macos-universal.zip: OK`, and the last line prints
`dsd-upsample 0.1.1`. The archive unpacks into one folder,
`dsd-upsample-v0.1.1-macos-universal/`, which holds:

| Path | Contents |
|---|---|
| `dsd-upsample-v0.1.1-macos-universal/` | The folder everything below is in |
| `dsd-upsample` | The command |
| `lib/libdsd_upsample.dylib` | The C library |
| `include/dsd_upsample.h` | C header |
| `README.md`, `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE` | Documentation, licences and notices |

Put the command in `/usr/local/bin`, which is on your `PATH` (macOS asks for your password):

```sh
sudo mkdir -p /usr/local/bin
sudo install -m 755 dsd-upsample-v0.1.1-macos-universal/dsd-upsample /usr/local/bin/
```

The library's install name is `@rpath/libdsd_upsample.dylib`: add the folder you keep it in to
your program's run-time search path (`-Wl,-rpath,FOLDER`). There is no pkg-config file on
macOS; point the compiler at `include/` and the linker at `lib/`.

## From crates.io

With Rust 1.83 or later:

```sh
cargo install dsd-upsample-cli
```

This builds the command and puts it in `~/.cargo/bin`. With Rust from rustup that folder is
already on your `PATH`. With another Rust (for example Homebrew's `rust`), run this line once
and open a new Terminal window. Paste it as it is: `$HOME` and `$PATH` are read by the shell,
not placeholders to fill in.

```sh
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.zprofile
```

## Tested

The macOS build runs the full test suite in release, golden hashes included, on GitHub's
macOS 15 arm64 runners before it is packaged; CI runs the tests on every change. Each release
is also tested in a macOS virtual machine on Apple hardware (arm64): the test suite, the
universal build, and output byte-identical to the Linux command. The Intel (x86_64) half of
the universal archive is built but not run in our tests.

## See also

- [Install](README.md)
- [User guide](../user-guide.md)
- [C interface](../c-api.md)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
