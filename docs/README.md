[dsd-upsample-rs](../README.md) › Documentation

<img src="assets/icon-256.png" alt="" width="96">

# Documentation

Everything about installing, using and maintaining dsd-upsample, the converter from DSF, DFF,
WAV and FLAC to DSD128 or DSD256 (and from PCM to DSD64).

## Install

- [Install guides](install/README.md): which package to use on which system
- [Linux](install/linux.md): release archives and `cargo install`
- [macOS](install/macos.md): universal release archive and `cargo install`
- [Windows](install/windows.md): release zip and `cargo install`
- [Packages](install/packages.md): crates.io and the C library

## Use

- [User guide](user-guide.md): converting files, batch mode, test tones, JSON progress,
  troubleshooting

## Reference

- [Options](options.md): every command-line option
- [C interface](c-api.md): `libdsd_upsample`
- [Rust API](https://docs.rs/dsd-upsample) on docs.rs

## Internals

- [Design](design.md): the processing chain and determinism
- [Modulator design](modulator-design.md): the noise-transfer functions, their candidates and measurements
- [Stability study harness](../tools/stability/README.md): the 60 s acceptance test behind the
  modulator defaults
- [Resampler design](resampler-design.md): the 147/160 filter for 48 kHz-family input, its
  specification and measurements
- [Measurements](measurements.md): noise floor, distortion, IMD, idle tones, overload, speed,
  long-running use
- [DSD measurements](measurements-dsd.md): the output through a reference software decoder next to
  SoX-DSD, in the style of Archimago's DSD articles

## Project

- [Changelog](../CHANGELOG.md)
- [Security policy](../SECURITY.md): how to report a vulnerability
- [Release process](release.md)
- [Release test plan](release-test-plan.md): what a release candidate must pass
- [Quality against the previous release](quality/README.md): the dsd-measure comparison of
  every release
- [Contributing](../AGENTS.md)
- [Provenance](../PROVENANCE.md): the source and licence of every borrowed design
- [Icon](assets/README.md): the project icon files
- [Releases](https://github.com/dsd-toolbox/dsd-upsample-rs/releases)

## See also

- [README](../README.md)
- [dsd2pcm](https://github.com/dsd-toolbox/dsd2pcm-rs): the DSF, DFF, WAV and FLAC library underneath

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
