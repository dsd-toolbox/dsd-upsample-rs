[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Release test plan

# Release test plan

CI proves that the code does what its tests say. A release also has to work on real music and
from the packages people install. This page says what is tested before a release, on what, and
what blocks it. For 0.1.0 it covers this repository on Linux x86_64 (aarch64 follows when our
ARM test machine arrives). Windows and macOS follow in a later release.

## When each level runs

| Level | Runs on | Contents | Blocks |
|---|---|---|---|
| **Change** | Local CI on the branch (`tools/local-ci.sh`) | `cargo fmt`, `clippy -D warnings`, tests in debug and release on stable and the MSRV, the C smoke test and the C leak loop under AddressSanitizer, the short soak, `cargo doc`, the quality gate's unit tests, the fuzz build | The merge |
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

### 2. Long-running use

- The soak test with 1,200 conversions (`SOAK_N=1200`): threads back to their baseline after every
  conversion, no growth in mean resident memory.
- The C leak loop (`tools/c-leak.sh 1000`) under AddressSanitizer with leak detection.
- A one-hour live-heap run: the CLI's batch mode over the music set below, under heaptrack or
  valgrind's massif, with peak and final live heap recorded.
- Passes when: no definitely or indirectly lost bytes in our code, threads back to baseline,
  no upward trend in the live heap.

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
Linux release archives and crates.io. A failure here means a patch release, not
a withdrawn one.

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
