# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## 0.1.1 - 2026-11-26

Release archives for macOS and Windows, and the fixes found after 0.1.0. The output is
byte-identical to 0.1.0's: the golden hashes are unchanged, and
[docs/quality/0.1.1.md](docs/quality/0.1.1.md) has the comparison.

### Added
- Release archives for macOS (universal, arm64 and x86_64; signed and notarised) and Windows
  (x64; not code-signed yet, named `-unsigned`), with the CLI and the C library, SHA-256 sums
  and build provenance attestations. Each build runs the full test suite in release, golden
  hashes included, on its runner before it is packaged. Windows on ARM is not supported; it
  comes in a later release, once tested on ARM64 Windows.
- CI runs the tests and golden hashes on macOS 15 (arm64) and Windows x64 as well as Linux
  x86_64.
- Install guides for [macOS](docs/install/macos.md) and [Windows](docs/install/windows.md).
- `dsd_upsample::VERSION` and `dsd_upsample::engine_id()` (`dsd-upsample/X.Y.Z`): the
  engine's identity at run time for a host's cache keys; `dsdup_version()` in C gives the
  same version.
- `examples/golden.rs`: SHA-256 hashes of conversions at the default settings (built-in
  stereo and 5.1 tones, or given files), for programs that pin the engine's bytes in their
  own tests. Its stereo cases are the crate's golden hashes.
- `tools/musl-check.sh` and a CI job: the test suite, golden hashes included, on
  `x86_64-unknown-linux-musl`, and the C library built as a shared object on musl's libc
  (it needs musl's loader and `libgcc_s.so.1`).
- `tests/channels.rs`: a 1-channel stream gives the bytes of that channel in a
  multichannel stream without dither (DSD and PCM input); with dither only channel 0
  does, because each channel's dither is seeded with its index.
- `tests/heap_flat.rs`, in CI: after every conversion in one process, the live heap,
  counted exactly by a counting allocator, is back to its baseline to the byte, and the
  threads are back, over whole conversions of each input class, cancelled and failed
  conversions, and damaged files. Three positive controls (a leak per conversion, a leak on
  one error path, a thread left running) must be caught.

### Fixed
- A conversion joins its front-end threads, and batch mode its worker threads, before it
  returns, so every worker thread has ended when the call returns. No memory was lost before.
  In `tests/heap_flat.rs` with `HEAP_FLAT_N=100` (1,400 conversions in one process), the
  kernel still listed a worker thread at the moment of return 57 times before and 0 and 3
  times in two runs after (a joined thread can stay listed for a few milliseconds while the
  kernel reaps it).
- A DSF header whose fmt chunk size puts the data chunk past the end of the file (the file
  changed after it was opened) is reported as a damaged header (a format error), not as an
  I/O error.
- The `dsd-upsample` and `dsd-upsample-cli` crates include `LICENSE-MIT`, `LICENSE-APACHE`
  and `NOTICE`; CI checks the package lists.
- Install guides: a line to paste that puts `~/.cargo/bin` on the `PATH`, and the platform
  lines say what is tested (macOS 15 on arm64; Windows 11 and Windows Server 2025 on x64).

## 0.1.0 - 2026-11-25

First public release.

### Added
- Conversion of DSF, DFF, WAV and FLAC files to DSD128 or DSD256, and of PCM to DSD64.
  PCM input at 44.1, 88.2, 176.4 and 352.8 kHz, and at 48, 96, 192 and 384 kHz, which is
  resampled by 147/160 to the 44.1 kHz family with a synchronous linear-phase polyphase
  filter (stopband −244.6 dB at the new rate's Nyquist frequency, passband ripple within
  ±5e-12 dB). See [resampler design](docs/resampler-design.md).
- A one-bit CRFB sigma-delta modulator with an input limiter and optional TPDF dither. Its
  noise-shaping zeros lie over 0 to 20 kHz (library `Options::band`, C
  `dsdup_settings.band`: this release has that one band; the C value 1 is reserved and
  refused). Orders 5 to 8 at DSD64 and DSD256 and 5 to 7 at DSD128 (`accepted_orders`);
  each accepted combination clipped no modulator state and never reset on the legal
  signals of the 60 s stability study, and `tests/stability.rs` runs those signals on each
  of them for a shorter time. Defaults: order 6, an input limit of 0.51 and a gain of −6 dB
  at every rate. The gain leaves 6 dB of headroom so that legal input is not limited at
  the defaults (PCM with true peaks up to +6 dBTP, DSD tones held at +3.1 dB SACD;
  `tests/stability.rs` checks it); a higher `--gain` is louder, and what it limits is
  counted ([design, Decisions](docs/design.md#decisions)).
  SINAD of a 1 kHz tone at −3 dB SACD from 64-bit float input at 88.2 kHz 118.2, 157.1 and 195.8 dB at
  DSD64, DSD128 and DSD256 (188.0 dB at DSD256 from a 32-bit integer source). See
  [modulator design](docs/modulator-design.md).
- Output designed to be byte-identical within a release across platforms and with any
  number of threads (golden hashes checked in CI on Linux x86_64). Later
  releases may change the output where a measured improvement is found, and list each such
  change with its measured effect here.
- DSF and DFF output with ID3v2.4 tags, PCM output at 88.2, 176.4 and 352.8 kHz, and an
  option never to overwrite existing files. DSF input with an odd sample count: the padding
  bits after the last sample of a block are ignored (dsd2pcm 0.1.2).
- Outputs are written to a temporary file and renamed on success: an error, a cancel or
  Ctrl-C never leaves a partial output, and an existing output is replaced only by a
  complete one.
- The `dsd-upsample` command line tool, with a batch mode (`--jobs`, `--json`), a test
  signal generator (`gen`; DSD tones up to +3.1 dB SACD, made by modulators that do not
  overload), `--help`, `--version`, `--` to end the options, and distinct
  exit statuses (1 conversion or I/O error, 2 usage error, 130 interrupted). Each
  conversion reports per channel the limited samples, clipped modulator states and resets,
  and, whenever any sample was limited, their count and share (batch mode adds a total);
  `--json` done events carry the output length and the `limited`, `clipped`, `resets` and
  `clamped` totals. A warning (stderr, and `warning` in `--json`) when 1 % or more of a
  channel's samples were limited, naming a DC offset in the source when there is one.
- The Rust library `dsd-upsample`, with whole-file conversion, progress and cancellation,
  a streaming interface, and `Report::input_mean`, the input's mean per channel.
- Input checks: a DSF file whose header declares 0 samples while its data chunk holds audio
  is refused with both numbers; a custom `convert` source that ends before the length it
  declared, or gives its channels different lengths in one read, is refused with an error.
- A C library (`libdsd_upsample`) with a header, and a pkg-config file on Linux. Its
  structs have no implicit padding (`dsdup_report` has an explicit `reserved` field, and
  `band` completes `dsdup_settings`), so every byte is written.
- Release archives for Linux x86_64 (glibc), with SHA-256 sums and build provenance
  attestations. Linux x86_64 at 0.1.0; aarch64 follows when our ARM test machine arrives.
  Windows and macOS follow in a later release.
- Published measurements of noise, distortion, idle tones, overload and long-running memory
  use ([measurements](docs/measurements.md)), of the output through a reference software
  decoder next to SoX-DSD and 24-bit PCM ([DSD measurements](docs/measurements-dsd.md)),
  and controlled [speed](docs/measurements.md#speed) timings on an Intel Core i9-13900H,
  with the tools that produce them: `tools/measure/`, `tools/stability/` (the stability
  study and the acceptance gate) and `tools/speed/`.
