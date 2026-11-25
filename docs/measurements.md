[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Measurements

# Measurements

How good the output is, measured: noise floor, distortion, IMD, idle tones, overload,
48 kHz-family input, speed and long-running use.

For the output decoded by an independent reference decoder and compared with SoX-DSD and
24-bit PCM (multitone, J-Test, ultrasonic noise by rate and order, stability at the
+3.1 dB SACD peak), see [DSD measurements](measurements-dsd.md).

## Method

Each table states its settings. Unless it says otherwise, a table is at the CLI's defaults
(order 6 at every rate, input limit 0.51) with, where it matters, orders 5, 7 and 8 as
labelled extra rows; the PCM-source tables run at `--gain 0` (below), and any other gain,
limit or `--cutoff` filter is named with its table. Measured 2026-11-24 with the 0.1.0
conversion code (a 0.1.0 release-candidate build). `python tools/measure_suite.py` (needs numpy and scipy,
`tools/requirements.txt`) makes the signals, runs the CLI and measures the output; each
table names the command that produced it, and
`python tools/measure_suite.py --doc docs/measurements.md` rewrites the tables it makes (the
`suite:` blocks; the other tables name their own scripts). Method
(`tools/measure.py`): the output is decimated to 352.8 kHz with a long reference Kaiser
FIR, then analysed with one 2^20-point FFT and a 7-term Blackman-Harris window. Levels are
in dB re 0 dB SACD (50 % modulation). Noise figures exclude the tone and its harmonics 2
to 10. This analysis reads no more than about 168 dB below the tone (window leakage of
the single FFT): the DSD256 rows at 0 to −20 dB at the defaults and orders 5, 7 and 8 at
DSD256 (167.0 to 168.2 dB SNR) reach that floor and order 7 at DSD128 (165.1 dB) comes within
about 3 dB of it, so their SNR and THD+N are lower bounds. The [modulator design](modulator-design.md)
and [DSD measurements](measurements-dsd.md) pages measure further down with a reference
decoder.

PCM sources are f64 WAV at 352.8 kHz converted at `--gain 0`, so the stated level is the
modulator input; they show the interpolators and the modulator alone. DSD64 sources come
from `dsd-upsample gen` and are converted at the default -6 dB gain with this crate's
DSD64 decimator.

## Level sweep, 1 kHz, f64 PCM source (modulator and interpolators)

<!-- suite:levels -->
| Level (dB SACD) | Output rate | Order | Level out (dB SACD) | SNR 20k (dB) | THD+N (dB) | Noise 20-20k (dB SACD) | 20-50k (dB SACD) | 50-100k (dB SACD) |
|---|---|---|---|---|---|---|---|---|
| 0 | DSD64 | 6 (default) | 0.0 | 121.4 | -121.0 | -121.3 | -48.5 | -22.5 |
| -6 | DSD64 | 6 (default) | -6.0 | 115.0 | -114.7 | -121.0 | -47.9 | -22.1 |
| -20 | DSD64 | 6 (default) | -20.0 | 101.6 | -101.3 | -121.6 | -47.6 | -23.8 |
| -60 | DSD64 | 6 (default) | -60.0 | 60.9 | -60.6 | -120.9 | -48.9 | -22.7 |
| -120 | DSD64 | 6 (default) | -119.9 | 0.1 | -0.1 | -120.0 | -47.3 | -20.5 |
| -6 | DSD64 | 5 | -6.0 | 107.2 | -106.8 | -113.2 | -53.2 | -24.6 |
| -6 | DSD64 | 7 | -6.0 | 123.0 | -122.4 | -129.0 | -42.9 | -20.6 |
| -6 | DSD64 | 8 | -6.0 | 128.2 | -128.0 | -134.2 | -35.1 | -19.9 |
| 0 | DSD128 | 6 (default) | 0.0 | 159.8 | -159.3 | -159.8 | -87.9 | -46.9 |
| -6 | DSD128 | 6 (default) | -6.0 | 153.9 | -153.5 | -159.9 | -87.5 | -46.4 |
| -20 | DSD128 | 6 (default) | -20.0 | 140.5 | -140.2 | -160.5 | -87.9 | -46.0 |
| -60 | DSD128 | 6 (default) | -60.0 | 102.2 | -99.1 | -162.2 | -91.0 | -49.8 |
| -120 | DSD128 | 6 (default) | -120.0 | 48.7 | -48.7 | -168.7 | -96.8 | -55.1 |
| -6 | DSD128 | 5 | -6.0 | 140.1 | -139.4 | -146.1 | -86.5 | -51.9 |
| -6 | DSD128 | 7 | -6.0 | 165.1 | -164.5 | -171.1 | -88.5 | -41.0 |
| 0 | DSD256 | 6 (default) | -0.0 | 168.2 | -168.2 | -168.2 | -127.0 | -86.4 |
| -6 | DSD256 | 6 (default) | -6.0 | 168.2 | -168.2 | -174.2 | -126.6 | -86.0 |
| -20 | DSD256 | 6 (default) | -20.0 | 167.9 | -167.9 | -187.9 | -127.0 | -86.1 |
| -60 | DSD256 | 6 (default) | -60.0 | 139.5 | -135.7 | -199.5 | -128.9 | -88.9 |
| -120 | DSD256 | 6 (default) | -120.0 | 87.4 | -87.4 | -207.4 | -135.9 | -95.3 |
| -6 | DSD256 | 5 | -6.0 | 167.0 | -166.7 | -173.0 | -119.6 | -85.1 |
| -6 | DSD256 | 7 | -6.0 | 168.2 | -168.2 | -174.2 | -133.6 | -86.6 |
| -6 | DSD256 | 8 | -6.0 | 168.2 | -168.2 | -174.2 | -137.7 | -84.5 |

Produced by `python tools/measure_suite.py --only levels`.
<!-- /suite -->

## Level sweep, 1 kHz, DSD64 source (dsd-upsample gen), default gain (−6 dB)

<!-- suite:dsd64 -->
| Source level, DSD64 (dB SACD) | Source (modulator) | Source noise 20-20k (dB SACD) | Output rate | Order | Level out (dB SACD) | SNR 20k (dB) | THD+N (dB) | Noise 20-20k (dB SACD) | 20-50k (dB SACD) | 50-100k (dB SACD) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | gen, order 7 | -129.3 | DSD128 | 6 (default) | -6.0 | 129.3 | -128.7 | -135.3 | -52.7 | -45.4 |
| 0 | gen, order 7 | -129.3 | DSD256 | 6 (default) | -6.0 | 129.3 | -128.7 | -135.3 | -52.7 | -52.7 |
| -6 | gen, order 7 | -129.0 | DSD128 | 6 (default) | -12.0 | 123.0 | -122.4 | -135.0 | -52.2 | -45.3 |
| -6 | gen, order 7 | -129.0 | DSD256 | 6 (default) | -12.0 | 123.0 | -122.4 | -135.0 | -52.2 | -52.0 |
| -20 | gen, order 7 | -129.5 | DSD128 | 6 (default) | -26.0 | 109.5 | -109.3 | -135.5 | -51.7 | -44.5 |
| -20 | gen, order 7 | -129.5 | DSD256 | 6 (default) | -26.0 | 109.5 | -109.3 | -135.5 | -51.7 | -50.8 |
| -60 | gen, order 7 | -130.9 | DSD128 | 6 (default) | -66.0 | 70.9 | -69.2 | -136.9 | -54.4 | -47.2 |
| -60 | gen, order 7 | -130.9 | DSD256 | 6 (default) | -66.0 | 70.9 | -69.3 | -136.9 | -54.4 | -53.2 |
| -120 | gen, order 7 | -138.2 | DSD128 | 6 (default) | -126.0 | 18.2 | -18.2 | -144.2 | -59.1 | -54.0 |
| -120 | gen, order 7 | -138.2 | DSD256 | 6 (default) | -126.0 | 18.2 | -18.2 | -144.2 | -59.2 | -61.9 |

Produced by `python tools/measure_suite.py --only dsd64`.
<!-- /suite -->

## CCIF IMD, 19 + 20 kHz, each -6.02 dB (composite peak 0 dB SACD)

<!-- suite:ccif -->
| Output rate | Order | d2, 1 kHz (dB re one tone) | d3, 18 + 21 kHz (dB re one tone) |
|---|---|---|---|
| DSD64 | 6 (default) | -139.5 dB | -111.1 dB |
| DSD64 | 7 | -154.8 dB | -116.7 dB |
| DSD128 | 6 (default) | -185.9 dB | -146.9 dB |
| DSD128 | 7 | -206.9 dB | -158.1 dB |
| DSD256 | 6 (default) | -229.0 dB | -183.1 dB |
| DSD256 | 7 | -242.4 dB | -200.7 dB |

Produced by `python tools/measure_suite.py --only ccif`.
<!-- /suite -->

## Idle tones: silence and DC

<!-- suite:idle -->
| Input (dB SACD) | Output rate | Order | Dither | Strongest line 20-20k | at | Noise 20-20k |
|---|---|---|---|---|---|---|
| silence | DSD128 | 6 (default) | no | -187.1 dB SACD | 213 Hz | -168.5 dB SACD |
| silence | DSD256 | 6 (default) | no | -219.2 dB SACD | 24 Hz | -208.2 dB SACD |
| DC -40 dB | DSD128 | 6 (default) | no | -182.3 dB SACD | 19927 Hz | -161.6 dB SACD |
| DC -40 dB | DSD256 | 6 (default) | no | -220.8 dB SACD | 19998 Hz | -200.9 dB SACD |
| DC -60 dB | DSD128 | 6 (default) | no | -159.4 dB SACD | 2821 Hz | -156.7 dB SACD |
| DC -60 dB | DSD128 | 6 (default) | yes | -159.4 dB SACD | 2825 Hz | -154.6 dB SACD |
| DC -60 dB | DSD256 | 6 (default) | no | -201.6 dB SACD | 16933 Hz | -195.7 dB SACD |
| DC -60 dB | DSD256 | 6 (default) | yes | -190.9 dB SACD | 15230 Hz | -161.7 dB SACD |
| DC -80 dB | DSD128 | 6 (default) | no | -154.9 dB SACD | 284 Hz | -153.6 dB SACD |
| DC -80 dB | DSD256 | 6 (default) | no | -191.3 dB SACD | 563 Hz | -190.3 dB SACD |

Produced by `python tools/measure_suite.py --only idle`.
<!-- /suite -->

## Overload, 1 kHz, DSD256

<!-- suite:overload -->
| Level (dB SACD), DSD256 output | Order, limit | Limited | Clipped-state samples | Resets | THD+N (dB) |
|---|---|---|---|---|---|
| +0 dB | 6, 0.51 (defaults) | 0 | 0 | 0 | -168.2 |
| +1 dB | 6, 0.51 (defaults) | 10500560 | 0 | 0 | -28.4 |
| +2 dB | 6, 0.51 (defaults) | 15304080 | 0 | 0 | -21.4 |
| +3 dB | 6, 0.51 (defaults) | 18668720 | 0 | 0 | -17.9 |
| +4 dB | 6, 0.51 (defaults) | 21298960 | 0 | 0 | -15.7 |
| +6 dB | 6, 0.51 (defaults) | 25272880 | 0 | 0 | -12.9 |

Produced by `python tools/measure_suite.py --only overload`.
<!-- /suite -->

### Reading the tables

- **Noise floor, PCM input.** At the defaults the in-band noise (20 Hz-20 kHz) at -6 dB is
  -121.0 dB SACD at DSD64, -159.9 dB at DSD128 and below -174 dB at DSD256 (the analysis
  floor). Just above the audio band, from 20 to 50 kHz, the noise is -47.9 (DSD64), -87.5
  (DSD128) and -126.6 dB (DSD256).
- **Noise floor, DSD64 input.** The DSD64 source itself has -129.0 dB SACD in band at
  -6 dB, -135.0 dB after the default -6 dB gain. At the defaults the conversion keeps that
  floor at DSD128 and DSD256 (-135.0 and -135.0 dB).
- **IMD.** With the composite at exactly 0 dB SACD, the CCIF d3 products (18 and 21 kHz)
  are at -111.1 dB (DSD64), -146.9 dB (DSD128) and -183.1 dB (DSD256) at the defaults. At
  DSD64 the 21 kHz product sits just above the audio band, where the modulator's noise
  rises.
- **Idle tones.** At the defaults, silence gives no line above -187.1 dB SACD (DSD128) and
  -219.2 dB SACD (DSD256). A DC offset
  produces the classic DC limit cycle at output rate × DC level (2.8 kHz at DSD128 for DC
  at -60 dB) at -159.4 dB SACD (DSD128) and -201.6 dB SACD (DSD256) at the defaults. The 24-bit TPDF dither (`--dither`) does not
  remove the DSD128 line (-159.4 dB); its own noise (-154.6 and -161.7 dB SACD in band)
  is above the defaults' floor. The DSD256 silence floor reads −208.2 dB SACD here,
  −207.8 dB SACD through the reference decoder of `tools/measure/`
  ([48 kHz-family input](#48-khz-family-input)) and −213.4 dBFS (−207.4 dB SACD) on
  [DSD measurements](measurements-dsd.md#summary): digital silence in each case, read by
  different analysers (decimation filter, FFT length, averaging) in different runs.
- **Overload.** At the defaults the input is limited above +0.17 dB SACD (0.51), and the
  modulator never clips its states in this test (0 clipped samples up to +6 dB SACD); the
  THD+N above 0 dB SACD is that of the limiting.

### Input limit 0.6 versus lower limits

Same sources, `--limit` 0.6, 0.55 and 0.51 (the default), THD+N at DSD256, the default order:

<!-- suite:limits -->
| Level (dB SACD), DSD256 output | THD+N (dB), limit 0.6 | 0.55 | 0.51 |
|---|---|---|---|
| 0 dB | -168.2 | -168.2 | -168.2 |
| +1 dB | -168.2 | -43.9 | -28.4 |
| +2 dB | -35.0 | -25.3 | -21.4 |
| +3 dB | -23.6 | -20.0 | -17.9 |

Produced by `python tools/measure_suite.py --only limits`.
<!-- /suite -->

THD+N of an over-level sine mostly measures the limiting itself. The fairer question is
how much the modulator adds on top of an ideal limiter, which the next section answers.

## Default order and limit

The defaults are order 6 at every rate and an input limit of 0.51
(0.17 dB above 0 dB SACD). The design study behind them, with the stability tests on legal
and hot signals, is on the [modulator design](modulator-design.md) page; the
[DSD measurements](measurements-dsd.md#defaults) page measures them near full scale and
under hot input. Orders 5, 7 and 8 remain available (order 8 not at DSD128); the tables
above show them.

<!-- table:defaults_main -->
| Output | Order | Limit | SINAD at −3 dB SACD, 1 kHz (dB) | Clip events, 60 s at 0 dB SACD, 1 / 10 / 20 kHz | Excess over an ideal limiter, worst hot input: whole / worst 10 ms (dB re the ideal signal) | Resets |
|---|--:|--:|--:|--:|--:|--:|
| DSD64 | 6 (default) | 0.51 | 118.3 | 0 / 0 / 0 | -115.3 / -114.4 | 0 |
| DSD128 | 6 (default) | 0.51 | 157.1 | 0 / 0 / 0 | -153.5 / -152.8 | 0 |
| DSD256 | 6 (default) | 0.51 | 188.0 | 0 / 0 / 0 | -156.6 / -156.6 | 0 |
<!-- /table -->

Produced by `python tools/measure_dsdup.py run --only main,final` and
`python tools/measure_dsdup.py report --doc docs/measurements.md`: SINAD from the 1 kHz tone
at -3 dB SACD (32-bit integer source, whose own noise limits SINAD to 188.8 dB at that
level), clip events from 60 s tones at 0 dB SACD, and the error beyond an ideal limiter
from 60 s tones at +3.1, +4.8 and +7.0 dB SACD before a -3 dB gain (`--gain -3`, 3 dB above
the default).

Real recordings: eight tracks (four DSD64 SACD rips and four loud PCM tracks, 16 and
24-bit, 44.1 and 88.2 kHz) were converted whole with `tools/measure_dsdup_music.py` at the
defaults and at every other accepted order. They are private and not in the repository, so
this result cannot be reproduced from it; the same command runs on any files you point it
at. Their audio-band true peaks were −0.2 to +3.6 dB SACD before the default −6 dB gain;
the limiter never engaged, no clip event and no reset occurred
([DSD measurements](measurements-dsd.md#real-material)).

## DSD64 decimator choice

Using dsd2pcm's DSD64 filters (the PCM-output filters, 105 dB stopband) as the first stage
lets DSD64's large ultrasonic noise alias back into the audio band. The default first
stage is this crate's 140 dB Kaiser decimator; the dsd2pcm filters stay selectable with
`--cutoff`.

<!-- suite:cutoff -->
| First stage (DSD64 source at -6 dB SACD, DSD256 output) | Source (modulator) | Source noise 20-20k | Order | Noise 20-20k |
|---|---|---|---|---|
| 140 dB Kaiser (default) | gen, order 7 | -129.0 dB SACD | 6 (default) | -135.0 dB SACD |
| `--cutoff 30` | gen, order 7 | -129.0 dB SACD | 6 (default) | -126.7 dB SACD |
| `--cutoff 40` | gen, order 7 | -129.0 dB SACD | 6 (default) | -126.7 dB SACD |
| `--cutoff wide` | gen, order 7 | -129.0 dB SACD | 6 (default) | -121.1 dB SACD |

Produced by `python tools/measure_suite.py --only cutoff`.
<!-- /suite -->

## 48 kHz-family input

PCM at 48, 96, 192 and 384 kHz passes the 147/160 resampler (see
[resampler design](resampler-design.md)) and then the chain of 44.1, 88.2, 176.4 or
352.8 kHz. Each signal below is converted from a 48 kHz-family source and from its
44.1 kHz-family partner at the same level; the differences show what the resampler adds.
Conventions: mono f64 WAV sources (no quantisation), CLI defaults except `--gain 6.0206`
(WAV 0 dBFS = 100 % modulation, so a source at −6.02 dBFS is 0 dB SACD), output decoded by
the reference decoder of `tools/measure/` at 352.8 kHz, levels in **dB re 0 dB SACD** unless
a column says otherwise. Made by
`python tools/measure_resample.py --bin target/release/dsd-upsample --work DIR`.

**SINAD, 1 kHz, 20 Hz–20 kHz** (dB; source level in dB SACD; output rate per column):

| Source | Level | DSD64 | DSD128 | DSD256 |
|---|---|---|---|---|
| 48 kHz | 0 | 121.0 | 159.9 | 198.4 |
| 44.1 kHz | 0 | 121.1 | 160.0 | 198.4 |
| difference | 0 | -0.1 | -0.1 | -0.0 |
| 48 kHz | -3 | 118.0 | 157.1 | 195.8 |
| 44.1 kHz | -3 | 118.3 | 156.9 | 195.8 |
| difference | -3 | -0.3 | +0.2 | +0.0 |
| 96 kHz | 0 | 121.1 | 159.9 | 198.4 |
| 88.2 kHz | 0 | 121.1 | 159.9 | 198.6 |
| difference | 0 | -0.0 | -0.0 | -0.2 |
| 96 kHz | -3 | 118.2 | 157.0 | 195.7 |
| 88.2 kHz | -3 | 118.2 | 157.1 | 195.8 |
| difference | -3 | -0.0 | -0.1 | -0.1 |
| 192 kHz | 0 | 121.3 | 160.0 | 198.3 |
| 176.4 kHz | 0 | 121.0 | 160.0 | 198.6 |
| difference | 0 | +0.4 | -0.0 | -0.3 |
| 192 kHz | -3 | 118.3 | 157.1 | 195.8 |
| 176.4 kHz | -3 | 118.3 | 157.2 | 195.7 |
| difference | -3 | -0.1 | -0.1 | +0.0 |
| 384 kHz | 0 | 121.3 | 160.1 | 198.6 |
| 352.8 kHz | 0 | 121.1 | 160.1 | 198.5 |
| difference | 0 | +0.2 | +0.0 | +0.1 |
| 384 kHz | -3 | 118.0 | 157.1 | 195.6 |
| 352.8 kHz | -3 | 118.4 | 157.4 | 195.7 |
| difference | -3 | -0.4 | -0.3 | -0.1 |

The differences (−0.4 to +0.4 dB, in both directions) are the scatter of the measurement:
the four 44.1 kHz-family rates differ from each other by up to 0.5 dB. The 64-bit float
figures in [modulator design](modulator-design.md#result) and the changelog
(`tools/stability/gate_metrics.py`, an 88.2 kHz source) equal the 88.2 kHz rows; the 44.1 kHz
rows differ from them by up to 0.2 dB (118.3 against 118.2 dB at DSD64, −3 dB SACD), within
that scatter.

**IMD, composite peak 0 dB SACD** (dB re the tones): CCIF 19 + 20 kHz 1:1, SMPTE 60 Hz +
7 kHz 4:1.

| Source | Output | CCIF IMD | CCIF IMD+N | SMPTE IMD | SMPTE IMD+N |
|---|---|---|---|---|---|
| 48 kHz | DSD64 | -112.6 | -118.0 | -121.5 | -118.9 |
| 48 kHz | DSD128 | -151.1 | -156.5 | -157.7 | -157.5 |
| 48 kHz | DSD256 | -185.7 | -195.1 | -194.9 | -195.9 |
| 44.1 kHz | DSD64 | -112.5 | -118.0 | -122.3 | -119.0 |
| 44.1 kHz | DSD128 | -150.2 | -156.5 | -158.6 | -157.4 |
| 44.1 kHz | DSD256 | -186.3 | -195.1 | -194.6 | -195.8 |
| 96 kHz | DSD64 | -114.0 | -117.8 | -122.4 | -119.2 |
| 96 kHz | DSD128 | -151.0 | -156.5 | -158.2 | -157.5 |
| 96 kHz | DSD256 | -186.2 | -195.1 | -194.7 | -195.6 |
| 88.2 kHz | DSD64 | -114.3 | -117.8 | -122.1 | -119.0 |
| 88.2 kHz | DSD128 | -150.8 | -156.6 | -158.1 | -157.6 |
| 88.2 kHz | DSD256 | -186.4 | -195.4 | -194.7 | -195.6 |
| 192 kHz | DSD64 | -113.1 | -117.8 | -122.0 | -118.9 |
| 192 kHz | DSD128 | -150.5 | -156.4 | -158.3 | -157.7 |
| 192 kHz | DSD256 | -185.9 | -195.2 | -194.4 | -195.7 |
| 176.4 kHz | DSD64 | -112.5 | -117.7 | -122.2 | -118.9 |
| 176.4 kHz | DSD128 | -150.9 | -156.7 | -158.3 | -157.5 |
| 176.4 kHz | DSD256 | -186.1 | -195.2 | -194.5 | -195.6 |
| 384 kHz | DSD64 | -112.8 | -118.0 | -121.5 | -119.2 |
| 384 kHz | DSD128 | -150.0 | -156.5 | -157.8 | -157.4 |
| 384 kHz | DSD256 | -186.5 | -195.3 | -194.6 | -195.7 |
| 352.8 kHz | DSD64 | -113.1 | -118.0 | -121.5 | -119.1 |
| 352.8 kHz | DSD128 | -151.1 | -156.8 | -158.4 | -157.4 |
| 352.8 kHz | DSD256 | -186.7 | -195.3 | -194.3 | -195.6 |

Between families at the same output rate the figures differ by at most 1.1 dB, in both
directions; between the 44.1 kHz-family rates themselves by up to 1.8 dB (CCIF at DSD64).

**Flatness**, 32-tone multitone (composite peak 0 dB SACD) to DSD128, each tone's level out
minus its level in (dB):

| Source | Tones 28.3 Hz-17.0 kHz, min / max | 21.4 kHz tone | Largest difference to the other family, tones to 17.0 kHz |
|---|---|---|---|
| 48 kHz | -1.27e-06 / +1.83e-06 | -53.04 | 2.3e-08 |
| 44.1 kHz | -1.26e-06 / +1.82e-06 | -22.01 | 2.3e-08 |
| 96 kHz | -1.69e-06 / +1.27e-06 | -0.00 | 2.8e-08 |
| 88.2 kHz | -1.69e-06 / +1.28e-06 | -0.00 | 2.8e-08 |
| 192 kHz | -2.56e-06 / +1.28e-06 | -0.00 | 2.0e-08 |
| 176.4 kHz | -2.57e-06 / +1.28e-06 | -0.00 | 2.0e-08 |
| 384 kHz | -2.55e-06 / +1.29e-06 | -0.00 | 3.3e-08 |
| 352.8 kHz | -2.55e-06 / +1.28e-06 | -0.00 | 3.3e-08 |

The chain is flat within −2.6e-6 to +1.8e-6 dB from 28 Hz to 17 kHz from either family
(the reference decoder included); the two families differ by at most 3.3e-8 dB there. At
the top of the band, the 19.99 kHz tone of the band-edge table below comes out at −1.3e-6
(48 kHz), −2.6e-6 (96 kHz) and −3.0e-6 dB (192 kHz). The 21.4 kHz tone lies in the
transition band (20 to 22.05 kHz), which the 48 kHz path crosses twice (resampler, then the
steep ×2 stage).

**Band edges**, single exact-phase tones at 0 dB SACD to DSD256 (the lowest modulator
noise). "Tone level out" is the output's line at the tone's frequency relative to the tone
in, next to the same line with digital silence in (the floor the measurement can see). A
tone in the stopband (above the new rate's Nyquist frequency) that the filter let through
would alias to the new rate minus its frequency: between 20 kHz and the new Nyquist
frequency, never into the audio band. The alias columns give the output's line there, next
to the same line with digital silence in and with white noise at −260 dB SACD in (two
floors: digital silence lets the modulator settle into patterns that sit slightly below
its noise with any real input). The last column is the in-band residual with the tone's
own line excluded:

| Source | Tone (Hz) | Tone level out (dB re in) | Same frequency, silence in (dB SACD) | Alias frequency (Hz) | Level there (dB SACD) | Same frequency, silence in (dB SACD) | Same frequency, noise at -260 dB SACD in (dB SACD) | In-band residual 20 Hz-20 kHz, tone excluded (dB SACD) |
|---|---|---|---|---|---|---|---|---|
| 44.1 kHz | silence | - | - | - | - | - | - | -207.8 |
| 44.1 kHz | 1000 at -215 dB SACD | - | - | - | - | - | - | -207.1 |
| 44.1 kHz | white noise at -260 dB SACD | - | - | - | - | - | - | -207.5 |
| 48 kHz | silence | - | - | - | - | - | - | -207.8 |
| 48 kHz | white noise at -260 dB SACD | - | - | - | - | - | - | -206.9 |
| 48 kHz | 1000 at -215 dB SACD | - | - | - | - | - | - | -207.4 |
| 48 kHz | 19990 | -0.0 | -233.5 | - | - | - | - | -199.5 |
| 48 kHz | 21000 | -10.6 | -224.6 | - | - | - | - | -198.6 |
| 48 kHz | 22000 | -220.4 | -217.2 | - | - | - | - | -207.1 |
| 48 kHz | 22100 | -216.4 | -221.4 | 22000 | -219.2 | -217.2 | -220.9 | -207.0 |
| 48 kHz | 23000 | -217.6 | -217.6 | 21100 | -224.7 | -222.4 | -222.7 | -207.7 |
| 48 kHz | 23990 | -210.7 | -213.2 | 20111 | -231.5 | -230.7 | -232.6 | -206.9 |
| 96 kHz | silence | - | - | - | - | - | - | -207.8 |
| 96 kHz | white noise at -260 dB SACD | - | - | - | - | - | - | -206.6 |
| 96 kHz | 19990 | -0.0 | -233.5 | - | - | - | - | -199.5 |
| 96 kHz | 39990 | -0.0 | -176.2 | - | - | - | - | -199.6 |
| 96 kHz | 42000 | -10.6 | -172.7 | - | - | - | - | -199.6 |
| 96 kHz | 44000 | -171.2 | -169.6 | - | - | - | - | -207.1 |
| 96 kHz | 44200 | -171.1 | -170.5 | 44000 | -171.5 | -169.6 | -168.5 | -207.1 |
| 96 kHz | 47990 | -164.5 | -165.6 | 40211 | -177.9 | -174.6 | -174.9 | -207.2 |
| 192 kHz | silence | - | - | - | - | - | - | -207.8 |
| 192 kHz | white noise at -260 dB SACD | - | - | - | - | - | - | -206.9 |
| 192 kHz | 19990 | -0.0 | -233.5 | - | - | - | - | -199.5 |
| 192 kHz | 79990 | -0.0 | -141.3 | - | - | - | - | -199.7 |
| 192 kHz | 84000 | -10.6 | -137.5 | - | - | - | - | -199.4 |
| 192 kHz | 88000 | -133.0 | -135.7 | - | - | - | - | -206.9 |
| 192 kHz | 88300 | -132.4 | -130.7 | 88100 | -131.7 | -133.6 | -131.2 | -206.9 |
| 192 kHz | 95990 | -128.3 | -129.2 | 80410 | -136.3 | -141.3 | -133.3 | -206.9 |

Every stopband tone (from 22.05, 44.1 and 88.2 kHz at 48, 96 and 192 kHz) reads at the
modulator's own noise at its frequency, and its alias frequency reads at the floors there
(for example 23 kHz in: −224.7 dB SACD at 21.1 kHz against −222.4 and −222.7 dB without
it). So neither the tone nor its alias is visible above the noise of a DSD256 output; the
filter's attenuation (−244.6 dB at the edge, −256 dB from the input's Nyquist frequency)
is beyond what this measurement can show. The in-band residual of the stopband tones
(−206.9 to −207.7 dB SACD) equals that of negligible non-zero inputs (−206.6 to −207.5), so
the removed tones leave nothing else in the audio band either. Digital silence reads
−207.8 dB SACD, slightly below any non-zero input, from both families.

**Real music.** The 32 48 kHz-family files of the release test set (mono to 6 channels, 8.1
channel-hours) to DSD128 and DSD256: 0 limited samples, 0 clipped states, 0 resets in the 31
readable files; the 32nd is a truncated FLAC and is refused with a clear error.
*Measured at order 6, limit 0.51 and gain −3 dB, on an earlier build of 0.1.0 (not the release
defaults, which use gain −6 dB).*

## Speed

Measured 2026-11-24 on an Intel Core i9-13900H (6 P-cores with Hyper-Threading, 8 E-cores;
20 logical CPUs), Fedora 44 Server, kernel 7.3, 94 GB RAM, NVMe SSD. Release build with
Rust 1.100.0: `cargo build --locked --release -p dsd-upsample-cli` (the release profile:
thin LTO, one codegen unit; no `RUSTFLAGS`, so the generic x86-64 target, as in the
published archives). CPU frequency governor `powersave` (intel_pstate active, energy
preference `balance_performance`), turbo on.

**Method.** Each figure is × real time: seconds of audio divided by the wall-clock time of
the whole `dsd-upsample` process (reading the input, converting, writing the DSF to the
SSD; inputs in the page cache). Every configuration ran 5 times in a row; the tables give
**best / median**. Inputs are 60 s synthetic music-like signals, 24-bit: pink noise at
-20 dBFS RMS plus five slowly modulated tones (110 Hz to 9 kHz), peaks at -3 dBFS, an
independent noise seed per channel; the DSD64 inputs are the 176.4 kHz signals converted
with `--rate 64`. Settings are the defaults (order 6, limit 0.51, gain −6 dB). The machine was otherwise idle (1-minute load below 4
when each batch started); the package temperature reached 92 °C under the heaviest runs.
Sampled clocks were about 3.7 GHz for one thread on a P-core and 2.6 to 2.7 GHz on the
E-cores, below the 5.4 GHz maximum turbo, so the figures reflect this machine's sustained
power limits. A configuration repeated 3.5 minutes apart gave the same median within 0.1 %.

**All threads and one thread** (no pinning). By default each channel runs on two threads,
front end and modulator; `--single-thread` uses one thread per file.

| Input | Output | Stereo, all threads | Stereo, one thread | 5.1, all threads | 5.1, one thread |
|---|---|--:|--:|--:|--:|
| DSD64 DSF | DSD128 | 17.2 / 17.1 | 6.1 / 6.1 | 12.2 / 11.7 | 2.0 / 2.0 |
| DSD64 DSF | DSD256 | 8.6 / 8.6 | 3.3 / 3.2 | 6.8 / 6.5 | 1.1 / 1.1 |
| 44.1 kHz PCM | DSD64 | 34.1 / 34.0 | 12.7 / 12.7 | 26.9 / 25.1 | 4.2 / 4.2 |
| 44.1 kHz PCM | DSD128 | 17.2 / 17.1 | 6.5 / 6.5 | 14.0 / 13.4 | 2.2 / 2.2 |
| 44.1 kHz PCM | DSD256 | 8.6 / 8.6 | 3.3 / 3.3 | 6.8 / 6.6 | 1.1 / 1.1 |
| 88.2 kHz PCM | DSD64 | 34.2 / 34.2 | 12.2 / 12.2 | 24.6 / 21.6 | 4.1 / 4.1 |
| 88.2 kHz PCM | DSD128 | 17.1 / 17.1 | 6.5 / 6.5 | 14.8 / 13.2 | 2.2 / 2.2 |
| 88.2 kHz PCM | DSD256 | 8.6 / 8.6 | 3.3 / 3.3 | 7.4 / 7.1 | 1.1 / 1.1 |
| 176.4 kHz PCM | DSD64 | 34.1 / 34.0 | 11.2 / 11.2 | 21.3 / 21.2 | 3.7 / 3.7 |
| 176.4 kHz PCM | DSD128 | 17.2 / 17.0 | 6.2 / 6.2 | 13.2 / 12.7 | 2.1 / 2.1 |
| 176.4 kHz PCM | DSD256 | 8.6 / 8.6 | 3.2 / 3.2 | 7.6 / 6.8 | 1.1 / 1.1 |

What the table shows:
- The output rate sets the speed; the input rate hardly matters. Each step up in output
  rate halves the speed, because the modulator, a serial recurrence per channel, runs at
  the output rate and sets the pace.
- Stereo with all threads runs at the modulator's own pace (two channels in parallel). 5.1
  needs 12 threads; its spread between best and median (up to 14 %) comes from the
  scheduler moving threads between P- and E-cores (see the pinned rows below).
- With `--single-thread`, 5.1 at DSD256 is only just faster than real time (1.1 ×).

**P-cores only and E-cores only** (`taskset -c 0-11` and `taskset -c 12-19`; logical CPU
numbers from `lscpu -e`).

| Input | Output | Threads | Stereo, P-cores | Stereo, E-cores | 5.1, P-cores | 5.1, E-cores |
|---|---|---|--:|--:|--:|--:|
| DSD64 DSF | DSD128 | all | 17.2 / 17.1 | 10.7 / 10.6 | 14.0 / 13.9 | 7.2 / 7.2 |
| DSD64 DSF | DSD256 | all | 8.6 / 8.6 | 5.3 / 5.2 | 7.2 / 7.2 | 4.1 / 4.1 |
| 44.1 kHz PCM | DSD64 | all | 34.1 / 34.0 | 20.9 / 20.9 | 27.1 / 27.0 | 16.5 / 16.3 |
| 44.1 kHz PCM | DSD128 | all | 17.1 / 17.0 | 10.5 / 10.4 | 14.0 / 13.9 | 8.4 / 8.4 |
| 44.1 kHz PCM | DSD256 | all | 8.6 / 8.6 | 5.2 / 5.2 | 7.0 / 7.0 | 4.2 / 4.2 |
| DSD64 DSF | DSD256 | one | 3.3 / 3.3 | 1.8 / 1.8 | not run | not run |
| 44.1 kHz PCM | DSD128 | one | 6.5 / 6.5 | 3.8 / 3.8 | not run | not run |
| 44.1 kHz PCM | DSD256 | one | 3.3 / 3.3 | 1.9 / 1.9 | not run | not run |

By median, the E-cores run at 55 to 62 % of the P-cores' speed in the stereo rows and at
52 to 60 % in the 5.1 rows. 5.1 restricted to the P-cores is
faster and steadier than unpinned (DSD64 to DSD256: 7.2 / 7.2 against 6.8 / 6.5).

**Batch mode**: eight 60 s stereo files in one `dsd-upsample IN... --out-dir DIR` call, all
cores; × real time is the total audio (480 s) over the wall time.

| Input | Output | `--jobs` | × real time |
|---|---|---|--:|
| DSD64 DSF | DSD256 | default (CPU threads / 4 = 5) | 26.1 / 25.2 |
| DSD64 DSF | DSD256 | 8 | 31.6 / 31.3 |
| 44.1 kHz PCM | DSD128 | default (5) | 48.6 / 46.9 |
| 44.1 kHz PCM | DSD128 | 8 | 61.7 / 60.8 |

**Against earlier figures.** The earlier version of this section gave indicative figures
from an AMD Ryzen AI Max+ 395 shared with other jobs, with the earlier defaults (order 6,
order 5 at DSD256, the earlier modulator tables, limit 0.5). The middle column is the
earlier build, the one just before the current defaults, timed on the i9-13900H in the
same session as the current build; no option of this release selects its tables.

| Case | Earlier figure (Ryzen AI Max+ 395, indicative) | Earlier build at its defaults, i9-13900H | Current defaults, i9-13900H |
|---|--:|--:|--:|
| DSD64 to DSD256, stereo, all threads | 10.9 | 8.5 / 8.5 | 8.6 / 8.6 |
| DSD64 to DSD128, stereo, all threads | not given | 17.0 / 16.9 | 17.2 / 17.1 |
| 44.1 kHz to DSD64, stereo, all threads | not given | 33.6 / 33.5 | 34.1 / 34.0 |
| 44.1 kHz to DSD256, stereo, all threads | not given | 8.5 / 8.5 | 8.6 / 8.6 |
| 176.4 kHz to DSD256, stereo, all threads | not given | 8.5 / 8.5 | 8.6 / 8.6 |
| DSD64 to DSD256, 5.1, all threads | not given | 7.0 / 6.6 | 6.8 / 6.5 |
| 44.1 kHz to DSD256, 5.1, all threads | not given | 7.2 / 6.8 | 6.8 / 6.6 |
| DSD64 to DSD256, stereo, one thread | not given | 3.2 / 3.2 | 3.3 / 3.2 |
| 44.1 kHz to DSD128, stereo, one thread | not given | 6.5 / 6.5 | 6.5 / 6.5 |
| Batch, 8 stereo files, DSD64 to DSD256 | 28 (8 × 10 s, 8 CPUs, 4 at a time) | not run | 25.2 (5 at a time), 31.3 (8 at a time) |

The current defaults cost no speed: by median, stereo with all threads is 1.2 to 1.5 %
faster than the earlier build on the same machine, with one thread equal at this table's
resolution, and the 5.1 rows are 1.5 and 2.9 % slower, within their best-to-median spread. The lower
figure against the Ryzen comes from the CPU, not the version.

**Reproduce.** `tools/speed/` holds the scripts (Python 3 with numpy). From the repository,
on Linux:

```sh
cargo build --locked --release -p dsd-upsample-cli
mkdir -p speed/bin/v2
cp target/release/dsd-upsample speed/bin/v2/
python3 tools/speed/gen_signals.py --all speed
cd speed
python3 ../tools/speed/make_jobs.py
python3 ../tools/speed/bench.py jobs/a_v2_all.tsv results.jsonl 5
python3 ../tools/speed/bench.py jobs/b1_v2_single_2ch.tsv results.jsonl 5
python3 ../tools/speed/bench.py jobs/b2_v2_single_6ch_lo.tsv results.jsonl 5
python3 ../tools/speed/bench.py jobs/b3_v2_single_6ch_256.tsv results.jsonl 5
python3 ../tools/speed/bench.py jobs/c_v2_pinned.tsv results.jsonl 5
python3 ../tools/speed/bench.py jobs/d_v2_batch.tsv results.jsonl 5
python3 ../tools/speed/report.py results.jsonl
```

`make_jobs.py` sets the P- and E-core CPU lists for the i9-13900H; edit them for another
CPU. `jobs/e_v1_xver.tsv` is the comparison with the earlier build and needs that build at
`speed/bin/v1/dsd-upsample`. The full run takes about 2 hours 20 minutes on this machine;
`report.py` prints the tables above.

48 kHz-family input (60 s stereo, best of 3, no other timing run on the machine, on the AMD
Ryzen AI Max+ 395 of [resampler design](resampler-design.md#speed), not the i9-13900H): with the
default threads it converts as fast as its 44.1 kHz-family partner (within 1 %); with
`--single-thread` the resampler adds 4 to 7 % at 48 kHz and 13 to 26 % at 192 kHz (DSD256
to DSD128) ([resampler design](resampler-design.md#speed)).

## Long-running use: threads and memory

These checks matter for a host application that keeps the library loaded for hours, such as
a player. Linux x86_64, release build.

| Check | Method | Result |
|---|---|---|
| Soak | `SOAK_N=1200 cargo test --release --test soak`: 1,200 conversions in one process (DSD64/DSD128/WAV input, 2 and 6 channels, orders 5–8, threaded and single-thread, the streaming API with odd push sizes and abandoned streams, cancel mid-way, a failing sink, a source that ends early, PCM output) | Thread count back to its baseline after every conversion (max settle 10 ms). Mean RSS 51.3 MB in the second quarter and 51.3 MB in the last quarter (it swings between conversions with the allocator's arenas, max 72.6 MB); no growth. A 3,600-conversion run gave the same picture. |
| C interface leaks | `tools/c-leak.sh 300`: settings, file conversion (also cancelled and failing), streams finished, stopped by the callback, freed without finishing and freed from inside their own callback, all under AddressSanitizer with `detect_leaks=1` | No leaks reported |
| CLI under valgrind | `valgrind --leak-check=full` of a 41 s DSD64 track converted to DSD256 | 0 bytes definitely or indirectly lost, 0 errors (612 bytes in use at exit: the Rust runtime's one-time allocations) |

CI runs the short versions on every change: the soak with 64 conversions (threads only; the
memory check needs at least 800, when the allocator's arenas have filled) and the C leak loop
with 100 iterations (Linux).

## See also

- [DSD measurements](measurements-dsd.md): results through a reference software decoder next to SoX-DSD
- [Design](design.md): the chain being measured
- [Options](options.md): `--order`, `--gain`, `--limit`, `--cutoff`, `--dither`
- [User guide](user-guide.md): the report printed after each conversion

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
