[dsd-upsample-rs](../../README.md) › [Modulator design](../../docs/modulator-design.md) › Stability study

# Stability study harness

Two scripts measure the modulator's stability through the command-line tool, 60 s per
signal; the [modulator design](../../docs/modulator-design.md) says which tables come from
which:

- `stab.py` is the **stability study** behind the default
  ([modulator design, stability study](../../docs/modulator-design.md#stability-study)): 29
  legal and 10 hot PCM signals from 88.2 and 352.8 kHz, with the clipped states and resets
  and the error left in the audio band beyond an ideal hard limiter. It needs a build with
  `dump.patch`.
- `gate.py` is the **acceptance gate** that decides which orders the library accepts
  ([modulator design, acceptance gate](../../docs/modulator-design.md#acceptance-gate)): the
  same 29 PCM signals plus 23 through the 48 kHz-family resampler (48, 96 and 384 kHz),
  0 dB SACD holds and DSD tones up to +3.1 dB SACD from DSD64, DSD128 and DSD256, counters
  only, with the released CLI, at the default gain and with `--gain -3`. At the default
  gain nothing may be limited on the legal signals
  ([headroom](../../docs/modulator-design.md#headroom)); `gate.py headroom` finds each
  signal's peak at the modulator input from the gain at which limiting starts.
  `gate_metrics.py` adds SINAD, ultrasonic noise and the SINAD cost of the default gain.
  Its commands are in the modulator design.
- `peak.patch` and `file_peaks.py` give the **peak at the modulator input of audio files**
  (the released tool reports limited samples, not the peak): the real-file table of the
  headroom section. The patched build goes into `target-peak/` and is never shipped; the
  commands are at the top of `file_peaks.py`.

The shipped test `crates/dsd-upsample/tests/stability.rs` runs the same signals (from 88.2
and 352.8 kHz, and through the resampler from 48, 96 and 384 kHz), three sines at 0 dB
SACD and DSD tones at +3.1 dB SACD for 1.5 s each on every accepted combination, and fails
on a single clipped state, or on a single limited sample of a legal signal at the defaults. These
scripts are the 60 s versions; they are not part of `cargo test`.

| File | What it does |
|---|---|
| `stab.py` | The stability study: counters, error beyond an ideal limiter (needs the patched build), 1 kHz tones at −3 and 0 dB SACD, CCIF, SMPTE and multitone at a 0 dB SACD peak |
| `counts.py` | Counters only, for every signal and candidate of `stab.py`; runs with the released CLI |
| `summ.py` | Prints the results of `stab.py` |
| `ctab.py` | Clipped states / resets per candidate from `counts.py`, legal and hot apart |
| `dump.patch` | A measurement-only change to `convert.rs`: writes the modulator input to the file named by `DSDUP_DUMP_U` |
| `gate.py`, `gate_metrics.py` | The acceptance gate, the headroom search, and the SINAD and ultrasonic figures |
| `peak.patch`, `file_peaks.py` | Peak at the modulator input of audio files, with a patched build |

## Running it

Needs Python 3 with NumPy and SciPy (the pinned set is `tools/requirements.txt`), a Rust
toolchain, and git. From the repository root:

```sh
git apply tools/stability/dump.patch
cargo build --release --target-dir target-dump -p dsd-upsample-cli
git apply -R tools/stability/dump.patch
STAB_CANDS=64:6:0.51,128:6:0.51,256:6:0.51 python tools/stability/stab.py
python tools/stability/summ.py target/stability
```

The patched binary is never shipped: it is built into `target-dump/` and the patch is
reverted at once. Without `DSDUP_DUMP_U` it writes the same output as the released CLI.

Counters alone, with any build of the CLI:

```sh
cargo build --release -p dsd-upsample-cli
DSDUP_BIN=target/release/dsd-upsample STAB_CANDS=64:6:0.51,128:6:0.51,256:6:0.51 python tools/stability/counts.py
python tools/stability/ctab.py target/stability/counts
```

A candidate is `RATE:ORDER:LIMIT`, for example `128:7:0.51`. The rows of the earlier tables
in the modulator design come from builds of that earlier design, which this release cannot
select. The other settings are environment variables:
`STAB_SECONDS` (default 60), `STAB_JOBS` (parallel conversions, default 5), `STAB_ONLY`
(signal names, comma-separated), `STAB_WORK` (default `target/stability`) and `DSDUP_BIN`.
Results are one JSON file per signal and candidate under `STAB_WORK/results/` (or
`STAB_WORK/counts/`); a finished result is not run again.

Cost: the 29 signal files (64-bit float WAV, 60 s each, 88.2 or 352.8 kHz) take about 2.2 GB
in `STAB_WORK`; every conversion at DSD256 also decodes 60 s of DSD256 in Python, so a full
run is hours of CPU time. As a check of the setup, `STAB_SECONDS=2` with
`STAB_ONLY=csine4_1k,sq_fs2_352` and `STAB_CANDS=64:6:0.51,256:6:0.51` took 71 s of wall
clock on four threads of an AMD Ryzen AI Max+ 395 (2026-11-24, not a controlled timing),
and its tone and IMD rows matched the [modulator design](../../docs/modulator-design.md)
tables (for example SINAD 195.8 / 198.6 dB at −3 / 0 dB SACD, DSD256).

## Signals

Legal in the study's sense (PCM within full scale, converted with `--gain -3`, the default
gain when the study was made; `stab.py` passes it explicitly, since the default is now −6 dB
and `--gain -3` is the louder setting): sines at 1,
5 and 10 kHz overdriven 2× and 4× and clipped at full scale; DC at 0.5, 0.75, 1 and −1;
white and pink noise at 0 and −3 dBFS; random ±full-scale samples at 88.2 and 352.8 kHz;
squares at 1 kHz, 10 kHz, a quarter and half of the sample rate at 88.2 and 352.8 kHz; a
full-scale 20 kHz sine at 352.8 kHz; full-scale steps; single-sample impulses. Hot: ten of
them with `--gain 3`, 6 dB louder than the study's gain and 9 dB above today's default. The exact definitions are in
`make()` in `stab.py`; the noise signals are seeded, so every run uses the same samples.

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
