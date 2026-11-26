[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Release test plan

# Release test plan

CI proves that the code does what its tests say. A release also has to work on real music and
from the packages people install. This page says what is tested before a release, on what, and
what blocks it. It covers this repository on Linux x86_64, macOS and Windows x64 (Linux
aarch64 follows when our ARM test machine arrives).

## When each level runs

| Level | Runs on | Contents | Blocks |
|---|---|---|---|
| **Change** | Local CI on the branch (`tools/local-ci.sh`) | `cargo fmt`, `clippy -D warnings`, tests in debug and release on stable and the MSRV, the C smoke test and the C leak loop under AddressSanitizer, the short soak, the heap-flat test and its positive controls, the licence files in the crate packages, `cargo doc`, the quality gate's unit tests, the fuzz build | The merge |
| **Release candidate** | `vX.Y.Z-rcN` | Everything in [the candidate gate](#the-candidate-gate) | The final tag |
| **After the tag** | The published release assets and packages | [Install checks](#install-checks) | Nothing; a failure means a patch release |

**Later candidates.** The full gate runs on the first candidate. A later candidate re-runs what its
changes could affect, plus the soak and fuzzing if shipped code changed, and lists what changed and
what carried over. The final tag carries, on top of the last candidate, only these edits:

- the version and the release date (`Cargo.toml`, `CHANGELOG.md`, the docs that name the
  version);
- `docs/quality/X.Y.Z.md`, the record of item 7 measured on the last candidate (it cannot
  exist before that candidate is measured), and the links to it.

Anything else is a new candidate.

## The candidate gate

Tag `vX.Y.Z-rcN` from the tree that will be published. Every
item below passes on that tag.

### 1. Fuzzing

The fuzz targets in `fuzz/` (`stream`: the streaming interface with arbitrary pushes;
`convert`: whole conversions from a source that breaks the reader contract, with arbitrary
settings and declared lengths and at most about 0.19 s of input each, while the file parsers
are fuzzed in dsd2pcm; `cli_args`: the CLI's argument parser with arbitrary argument vectors in
both modes, including arguments that are not valid UTF-8) run for at least four hours each on
the candidate.

- Passes when: no crash, hang (`-timeout=30`), out-of-memory (`-rss_limit_mb=2048`) or leak.
- Record: runs, coverage, corpus size, duration, CPU.

### 2. Long-running use and memory

The referee for memory is an exact in-process count of live heap bytes (a counting
allocator), never an external recorder: heaptrack and similar tools are for investigation
only. Every memory check has a positive control, a build or run that leaks on purpose and
must fail it.

- Heap-flat: `tests/heap_flat.rs` with `HEAP_FLAT_N=100`, and once per file of an 8-file set
  from the music set below (`HEAP_FLAT_INPUT`). Its three positive controls are caught where
  they were injected, and after every conversion (whole conversions of each input class, the
  failure paths, hostile files) the live heap equals the baseline to the byte and the threads
  are back.
- Bytes at exit: the release CLI under a preloaded counting allocator, batch mode with 1, 10
  and 130 conversions, plus valgrind memcheck on the 130 run; the bytes still allocated at
  exit do not depend on the number of conversions, and every remaining block is named.
- The soak test with 1,200 conversions (`SOAK_N=1200`): threads back to their baseline after every
  conversion; resident memory recorded as an observation.
- The C leak loop (`tools/c-leak.sh 1000`) under AddressSanitizer with leak detection.
- A one-hour run of the CLI's batch mode over the music set below: the counted live heap at
  the idle points between conversions equal each time; resident memory and the cgroup's peak
  recorded every minute as observations against a stated ceiling.
- Passes when: every condition above holds, each positive control fails, and memcheck reports
  no definitely or indirectly lost bytes.

### 3. Real music

A fixed set from a real library, at least 300 files: DSF and DFF (DSD64, plus some DSD128 and
DSD256 sources), stereo and multichannel, quiet and loud masters, odd sample counts, and PCM
sources (WAV and FLAC at 44.1, 88.2, 176.4 and 352.8 kHz and, through the resampler, 48, 96 and
192 kHz, including mono and 6-channel files; 16 and 24 bit). It also holds PCM files the
converter must refuse with a clear error: rates below 44.1 kHz. It is converted at the default
settings to DSD128 and DSD256, and a subset to DSD64 (from PCM) and PCM.

- Through the CLI in batch mode on x86_64 Linux, recording each file's limiter, clip and
  reset counters.
- Passes when: every conversion succeeds or fails with a clear error for a bad file; no resets;
  and limiter or clip counts are explained by the source's level.
- Damaged files: the CLI must refuse them with a clear error.

### 4. Release archives and crates

On clean virtual machines or containers, from the candidate's artifacts. Candidate tags
(`vX.Y.Z-rcN`) stay on the development server, and `release.yml` builds release archives only from a
tag equal to `v` and the workspace version, so the candidate's archive is built locally the
way `release.yml` builds it (the same build, package step and names, `vX.Y.Z` in the name):

- Linux x86_64: the release archive (the CLI, and the C library through its pkg-config
  file) and `cargo install`.
- macOS, in a virtual machine: the test suite, and the universal archive (the CLI and the
  dylib) from the dry run, on arm64; output byte-identical to the Linux CLI.
- Windows 11 x64, in a virtual machine: the test suite, and the release zip from the dry run
  (the CLI and the DLL); output byte-identical to the Linux CLI.
- Passes when: each installs, runs a conversion that is byte-identical to the CLI built from
  the tree, and uninstalls cleanly.

### 5. Documentation

- The README's Quick start, run exactly as written in an empty folder.
- The commands in the install guides and the user guide.
- The link check: no broken relative links or anchors.
- Every outside source the docs cite (for example Archimago, Audio Science Review or
  Stereophile) is linked, at least in the README.
- Passes when: every command works as written, or the text is fixed in the candidate.

### 6. Independent review

A reviewer who has not worked on the code reads the candidate tree for correctness, security
(the C interface, the file parsers, path handling, the workflows) and the
accuracy of the documentation.

- Passes when: no open finding of high severity. Lower findings are fixed or filed with a reason.

### 7. Quality against the previous release

The pinned measurement suite (`suites/upconverter.toml` in this repository, which fixes the
[dsd-measure](https://github.com/dsd-toolbox/dsd-measure) version it runs with)
runs on the candidate and on the previous release (before the first release: the previous
candidate), on the same machine and inputs: PCM to DSD at every output rate, with dsd-measure's
full profile (about 24 GB of memory per parallel job).

- Run: `tools/quality-compare.sh PREVIOUS-CLI CANDIDATE-CLI VERSION`
  ([how it measures](quality/README.md)).
- Record: `docs/quality/<version>.md`, one table by version (SINAD, noise floor, THD+N, alias
  rejection, null-test depth) with both binaries' SHA-256, and one sentence of conclusion, linked
  from the release notes. Alias rejection reads "not measured" until dsd-measure measures it for
  PCM-to-DSD devices.
- Passes when: no change beyond the suite's stated repeatability, in either part (equal explicit
  settings, and each build's defaults), or a change that is explained and accepted in the design
  decisions and recorded in the suite, which marks it "explained by decision".

### 8. Headroom and modulator stability of every accepted combination

When a candidate changes a modulator table, the default gain, the default input limit, an
input filter, or the combinations of order and output rate the library accepts
(`accepted_orders`), the 60 s set of
[modulator design](modulator-design.md#acceptance-gate) runs on every accepted combination at
the defaults and with `--gain -3`:
`python tools/stability/gate.py run --work target/gate --cands 64:5:default,64:6:default,64:7:default,64:8:default,128:5:default,128:6:default,128:7:default,256:5:default,256:6:default,256:7:default,256:8:default --louder`
(the full command with `--hot` and the table and headroom steps is in
[modulator design](modulator-design.md#acceptance-gate)). The 1.5 s version
of the same set is part of every change (`tests/stability.rs`).

- Passes when: at the defaults nothing is limited on any legal signal (PCM with a true peak
  up to +6 dBTP, and DSD tones held at +3.1 dB SACD from DSD64, DSD128 and DSD256), and no
  modulator state clips and no reset occurs on any signal, at the defaults or with
  `--gain -3`, in any accepted combination. A combination that cannot meet this is refused
  by the library, never shipped with a warning.

## Install checks

After the tag, the published assets and packages are installed as a user would: from the
release archives (Linux, macOS, Windows) and crates.io. A failure here means a patch release,
not a withdrawn one.

## Recording results

Each candidate gets one results note: what ran, on which tag, on which CPU and system, the
numbers for fuzzing and the soak, and a pass or fail per item. Music is described by count and
characteristics, never by title. Hardware is named by CPU model.

## See also

- [Measurements](measurements.md): audio quality, overload and long-running use
- [Release process](release.md): building and publishing
- [Design](design.md): the processing chain and its decisions
- [C interface](c-api.md): the library interface for host applications

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
