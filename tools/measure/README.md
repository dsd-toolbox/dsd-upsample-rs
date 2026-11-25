# Measurement tools

Generic, standalone tools for measuring a DSD modulator under test (PCM in, DSD out) at file
level: test signals, a reference software decoder (Archimago's "perfect DAC" method), FFT analysers, a bit-density
check and SVG plots. They follow the dsd-measure footprint (class B, tests 6 to 12, 18 and
19). They import nothing from this repository's crates; the only dependencies are NumPy,
SciPy and Matplotlib. Licence: MIT OR Apache-2.0.

| Tool | Input | Output |
|---|---|---|
| `signals.py` | signal id and parameters (`--fs`, `--fmt`, `--level` peak dBFS, `--freq`) | WAV: sine, silence, J-Test, 32-tone multitone, SMPTE, CCIF, 60 s hold; 3 s silence + 2 s ramp first |
| `multitone32.json` | (data) | the 32 multitone bins, frequencies, phases and amplitude, from `signals.py --design-multitone` |
| `decode.py` | DSF or DFF, `--fs` output rate | 32 or 64-bit float WAV; 100 % modulation = 1.0; Kaiser FIR, 128 taps per decimation step, beta 20. Also `decode_fast` (CIC + FIR, audio band only) for long files |
| `analyse.py` | DSF, DFF (decoded with `decode.py`) or WAV; `--test` | JSON: THD, THD+N, SINAD, dynamic range, noise floor, ultrasonic noise, J-Test, multitone distortion-free range, SMPTE and CCIF IMD. Library functions: `true_peak`, `compare` (error against a reference, per 50 ms block), `excess` (error against an ideal float signal, e.g. a hard-clipped input) |
| `density.py` | DSF or DFF | JSON: 28-bit window density of ones, windows beyond 71.43 % modulation, longest run, per-second min/mean/max |
| `plot.py` | spectra and series from the analysers | SVG overlays and x-y charts (library functions) |
| `dsdio.py` | DSF, DFF, WAV | bit arrays and float samples (library functions); `iter_dsf` streams long DSF files |

Levels: dBFS re a full-scale sine; 100 % modulation = 0 dBFS, so 0 dB SACD = -6.02 dBFS
and the 71.43 % peak level (+3.1 dB SACD) = -2.92 dBFS.

```sh
python tools/measure/signals.py sine sine.wav --fs 88200 --fmt i32 --freq 1000 --level -6.02
python tools/measure/analyse.py out.dsf --test tone --freq 1000
python tools/measure/density.py out.dsf --start 5.5
```
