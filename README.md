<img src="https://raw.githubusercontent.com/dsd-toolbox/dsd-upsample-rs/main/docs/assets/icon-256.png" alt="" width="96">

# dsd-upsample-rs

[![CI](https://github.com/dsd-toolbox/dsd-upsample-rs/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dsd-toolbox/dsd-upsample-rs/actions/workflows/ci.yml)
[![License: MIT OR Apache-2.0](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue)](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/LICENSE-MIT)
[![MSRV 1.83](https://img.shields.io/badge/MSRV-1.83-orange)](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/Cargo.toml)
[![crates.io](https://img.shields.io/crates/v/dsd-upsample.svg)](https://crates.io/crates/dsd-upsample)
[![docs.rs](https://img.shields.io/docsrs/dsd-upsample)](https://docs.rs/dsd-upsample)

dsd-upsample converts DSF, DFF, WAV and FLAC files to DSD128 or DSD256 (and PCM to DSD64), for
listeners who like upsampled DSD as files rather than real-time processing. The output is
designed to be byte-identical across platforms and thread counts within a release, and its
noise, distortion and overload behaviour are measured and published with the commands to
reproduce them.

## Platforms

| System | How | Guide |
|---|---|---|
| Linux, x86_64 | Release archives (`.tar.gz`, glibc 2.34 or later) with the CLI and the C library; `cargo install dsd-upsample-cli` | [Linux](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/install/linux.md) |
| Linux, as a library | Rust crate `dsd-upsample`; C library `libdsd_upsample` with a pkg-config file | [Packages](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/install/packages.md) · [C interface](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/c-api.md) |

Linux x86_64 at 0.1.0; aarch64 follows when our ARM test machine arrives. CI checks the output
against golden hashes on Linux x86_64. Windows and macOS follow in a later release. The crates
are source and may build elsewhere, but this release makes no claims for other systems.

## Quick start

With Rust 1.83 or later. With Rust from rustup, `cargo install` puts the command on your `PATH`;
with a distribution's Rust (for example Fedora's `cargo` package), add `~/.cargo/bin` to your
`PATH` first.

```sh
cargo install dsd-upsample-cli
dsd-upsample gen tone.dsf --rate 64 --freq 1000 --level -6 --seconds 5
dsd-upsample tone.dsf tone256.dsf --rate 256
```

The second line writes a DSD64 test tone and the third converts it to DSD256; the converter
prints its speed and the overload counters. Prebuilt archives are on the
[releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases); every way to install is
in the [install guides](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/install/README.md).

PCM input can be at 44.1, 88.2, 176.4 or 352.8 kHz, or at 48, 96, 192 or 384 kHz, which the
converter resamples by 147/160 first, below the measurable noise of its output
([how](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/user-guide.md#48-khz-family-input)).

## Documentation

- [Documentation index](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/README.md)
- [Install](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/install/README.md): Linux, packages
- [User guide](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/user-guide.md): converting files, batch mode, JSON progress, troubleshooting
- [Options](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/options.md): every command-line option
- [C interface](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/c-api.md)
- [Design](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/design.md): the processing chain and determinism
- [Measurements](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/measurements.md): noise floor, distortion, IMD, idle tones, overload, speed
- [Releases](https://github.com/dsd-toolbox/dsd-upsample-rs/releases) and [release process](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/release.md)
- [Contributing](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/AGENTS.md)

## Licence and credits

**Code** is dual-licensed under either of the Apache License, Version 2.0
([LICENSE-APACHE](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/LICENSE-APACHE)) or the MIT licence ([LICENSE-MIT](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/LICENSE-MIT)), at your
option. [NOTICE](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/NOTICE) holds the attributions to keep with it. Unless you state otherwise, any
code contribution you intentionally submit for inclusion in this work, as defined in the
Apache-2.0 licence, is dual-licensed as above, without any additional terms or conditions.

**Documentation, measurement data and creative assets** are licensed under [CC BY
4.0](https://creativecommons.org/licenses/by/4.0/)
([LICENSES/CC-BY-4.0.txt](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/LICENSES/CC-BY-4.0.txt)): every README (this one included), the pages
under `docs/` (the measurement pages included), the icons and the measurement charts under
`docs/assets/`, the measurement data and signal definitions published with them
(`tools/measure/multitone32.json`, `tools/modulator/state_scale.json`), and the READMEs under
`tools/`. Code examples and commands in these files may also be used under the code licence.
Not covered: facts and figures cited from other sources (for example the SoX-DSD comparison's
method, which follows Archimago's articles), which keep their own terms. Suggested attribution:
"dsd-upsample documentation, the dsd-upsample-rs authors,
https://github.com/dsd-toolbox/dsd-upsample-rs, CC BY 4.0". Contributions to these files are
licensed the same way. [CITATION.cff](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/CITATION.cff) says how to cite the software.

Credits:
- [dsd2pcm](https://github.com/dsd-toolbox/dsd2pcm-rs) (MIT OR Apache-2.0) for reading DSF, DFF,
  WAV and FLAC and writing DSF, DFF and WAV, and the DSD64 to PCM path; it is ported from scarletbook-pcm (MIT OR
  Apache-2.0) and reads FLAC with claxon (Apache-2.0).
- The modulator coefficients were designed offline with
  [python-deltasigma](https://github.com/ggventurini/python-deltasigma) (BSD-2-Clause), a port of R. Schreier's
  [Delta-Sigma Toolbox](https://www.mathworks.com/matlabcentral/fileexchange/19-delta-sigma-toolbox); the structure follows Schreier and Temes,
  [*Understanding Delta-Sigma Data Converters*](https://doi.org/10.1109/9780470546772).
- The [DSD measurements](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/docs/measurements-dsd.md) follow the method of
  [Archimago](https://archimago.blogspot.com/)'s DSD articles
  ([2021-10](https://archimago.blogspot.com/2021/10/measurements-look-at-dsd-and-using-sox.html),
  [2022-06](https://archimago.blogspot.com/2022/06/notes-on-dac-dsd-1-bit-pdm-measurements.html)),
  with SINAD and the 32-tone multitone as used by
  [Audio Science Review](https://www.audiosciencereview.com/) and the J-Test as used by
  [Stereophile](https://www.stereophile.com/content/measurements-maps-precision).
- Every source is listed in [PROVENANCE.md](https://github.com/dsd-toolbox/dsd-upsample-rs/blob/main/PROVENANCE.md).

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
