[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Modulator design

# Modulator design

Why the one-bit modulator has the noise-transfer functions (NTFs) it has: the candidates,
how each was derived and measured, and the defaults that came out. Measured 2026-11-23 and
2026-11-24.

## Contents

- [Result](#result)
- [The problem](#the-problem)
- [Method](#method)
- [What sets the in-band noise](#what-sets-the-in-band-noise)
- [What sets the stable input range](#what-sets-the-stable-input-range)
- [Candidates per rate](#candidates-per-rate)
- [The tables that ship](#the-tables-that-ship)
- [The earlier tables](#the-earlier-tables)
- [Orders 7 and 8](#orders-7-and-8)
- [Input limit](#input-limit)
- [Stability study](#stability-study)
- [Acceptance gate](#acceptance-gate)
- [Headroom](#headroom)
- [Speed](#speed)
- [Rejected approaches](#rejected-approaches)
- [Reproducing](#reproducing)

## Result

Default at every output rate: **order 6, NTF zeros over 0 to 20 kHz, H_inf 1.36, input
limit 0.51**. Orders 5 to 8 are accepted at DSD64 and DSD256, orders 5 to 7 at DSD128
([acceptance gate](#acceptance-gate)). The earlier tables (zeros spread to
22, 50 or 80 kHz, H_inf 1.5), called "wide" on this page, are not selectable in this
release: see [the earlier tables](#the-earlier-tables).

1 kHz tone through the command-line tool, 64-bit float input at 88.2 kHz, reference decoder and
analysers of `tools/measure`. Levels in dBFS with 100 % modulation = 0 dBFS. "Overloads"
are clipped modulator states / modulator resets, summed over the 60 s runs of the
[stability study](#stability-study) (29 PCM signals within full scale at a gain of −3 dB; 10 hot signals, 6 dB above
that).

| Output | Design | SINAD at −3 / 0 dB SACD (dB) | Noise 22–96 kHz (dBFS) | Noise 100–192 kHz (dBFS) | Overloads, legal | Overloads, hot |
|---|---|--:|--:|--:|--:|--:|
| DSD64 | order 6, audio (default) | 118.2 / 121.1 | −28.9 | −24.9 | 0 / 0 | 0 / 0 |
| DSD64 | order 6, wide (earlier default, limit 0.5) | 125.5 / 128.1 | −28.6 | −20.9 | 12 / 0 | 137,648,804 / 6 |
| DSD64 | order 5, wide (limit 0.5073) | 114.6 / 117.3 | −40.9 | −25.1 | 0 / 0 | 27,530 / 197 |
| DSD128 | order 6, audio (default) | 157.1 / 159.9 | −56.4 | −29.1 | 0 / 0 | 0 / 0 |
| DSD128 | order 6, wide (earlier default, limit 0.5) | 123.5 / 124.8 | −71.9 | −30.8 | 0 / 0 | 317,509,011 / 18 |
| DSD128 | order 5, wide (limit 0.5073) | 112.2 / 115.0 | −72.0 | −35.7 | 0 / 0 | 0 / 0 |
| DSD256 | order 6, audio (default) | 195.8 / 198.6 | −97.0 | −57.0 | 0 / 0 | 0 / 0 |
| DSD256 | order 5, wide (earlier default, limit 0.5) | 126.2 / 129.1 | −113.7 | −71.2 | 0 / 0 | 0 / 0 |

SoX-DSD, run as a black box ([DSD measurements](measurements-dsd.md)), for the same tone at
0 dB SACD: `sdm-8` 140.7, 190.9 and 197.7 dB at DSD64, DSD128 and DSD256 with −27.7, −56.5
and −107.7 dBFS from 22 to 96 kHz; `clans-8` 119.3 and 180.0 dB at DSD64 and DSD128 with
−40.9 and −62.2 dBFS. `sdm-8` at DSD256 and `clans-8` at DSD64 and DSD256 lose stability
within a 60 s tone at 0 dB SACD.

What the default gives and what it costs:

- Its SINAD at −3 dB SACD (1 kHz, 64-bit float input) is 34 dB (DSD128) and 70 dB (DSD256)
  higher than the earlier defaults'. Against SoX-DSD, at 0 dB SACD from the same 32-bit
  integer sources (SoX's tone 6.02 dB higher in the file, see [method](#method)): at DSD256
  the default reads 191.0 dB and SoX `sdm-8` 197.7 dB, each within 0.8 dB of the limit its
  source allows (191.8 and 197.8 dB), so this comparison cannot separate the two modulators there; at
  DSD128 the default reads 159.8 dB, 31.1 dB below `sdm-8` (190.9 dB) and 20.2 dB below
  `clans-8` (180.0 dB); at DSD64 121.1 dB, 19.6 dB below `sdm-8` (140.7 dB).
- It did not overload once in the stability study (29 legal and 10 hot signals, 60 s each,
  at every rate). The earlier DSD64 default (order 6, earlier tables, limit 0.5) clipped
  states on one legal signal and on 7 of the 10 hot ones.
- Noise from 22 to 96 kHz is 15.5 dB (DSD128) and 16.7 dB (DSD256) higher than with the earlier
  tables. Against SoX `sdm-8` (−60 dB SACD tone): −56.4 against −56.5 dBFS at DSD128, and
  −97.0 against −107.7 dBFS (10.7 dB more) at DSD256.
- At DSD64 the SINAD is 7.3 dB lower than the earlier default's (118.2 against 125.5 dB at
  −3 dB SACD), which clipped modulator states on legal input.
- The DSD128 gap to SoX `sdm-8` in the audio band cannot be closed by a loop of this family
  that also survives legal full-scale ultrasonic input: see
  [orders 7 and 8](#orders-7-and-8).

## The problem

The earlier defaults were order 6 (5 at DSD256) with an input limit of 0.5, chosen for
stability, and measured 66 to 69 dB less SINAD than SoX-DSD's `sdm-8` at DSD128 and DSD256. The stability study then found that the earlier default still clipped modulator states on legal input at
DSD64 (12 clipped states on a full-scale 88.2 kHz square from 352.8 kHz PCM, −57 dB in the
worst 10 ms). The requirement for a new default became:

- no clipped state and no reset on any legal signal in 60 s (PCM within full scale at the
  −3 dB gain that was then the default: tones, clipped sines, DC, noise, random full-scale samples, squares
  to the Nyquist frequency, steps, impulses), and none on hot input where a design can
  reach that;
- as little as possible limited up to a 0 dB SACD peak;
- in-band noise as close to SoX-DSD as that allows, and ultrasonic noise no worse than it
  has to be;
- byte-identical output on every platform within a release, and no loss of speed.

## Method

- **Design** (`tools/modulator/design.py`, NumPy only). Zeros on the unit circle at the
  roots of the Legendre polynomial scaled to a band, which minimise the integrated noise
  in that band, or at given frequencies. Poles from the maximally flat family of the
  Delta-Sigma Toolbox's `synthesizeNTF`, bisected until the NTF gain at half the sample
  rate equals H_inf (Lee's rule). CRFB coefficients are solved from the pole polynomial
  using the state update of `modulator.rs` itself, with a unity signal transfer function
  (b = [a, 1]); the largest pole error of the shipped tables is 6 × 10⁻⁹.
- **Simulation** (`tools/modulator/dsm.c`, `sim.py`). The recurrence of `modulator.rs` in
  the same operation order, fed directly at the DSD rate. It reproduces the earlier tables'
  SINAD of the [result](#result) table within 0.4 dB (DSD128 order 6: 123.4 / 125.2 dB
  against 123.5 / 124.8 dB; DSD256 order 5: 126.4 / 129.1 dB against 126.2 / 129.1 dB). Figures marked "modulator alone" come from it; all others are through
  the command-line tool.
- **Measurement.** Bits are decoded with `tools/measure/decode.py` and analysed with
  `tools/measure/analyse.py` (2^18-point FFT at 352.8 kHz, 20 Hz to 20 kHz; ultrasonic
  noise with a −60 dB SACD tone, as on the [DSD measurements](measurements-dsd.md) page).
- **Input word length.** The measurement suite feeds 32-bit integer PCM, whose own noise
  limits SINAD to 191.8 dB for a tone at 0 dB SACD (−6.02 dBFS) and 188.8 dB at −3 dB
  SACD. SoX-DSD maps PCM full scale to 0 dB SACD, so its tone sits 6 dB higher in the file
  and its limit is 197.8 dB: the 197.7 dB of `sdm-8` at DSD256 is that limit. The tables
  here use 64-bit float input; with 32-bit input the DSD256 default reads 188.0 / 191.0 dB.
- **Stress test** (`tools/modulator/hold.py`, modulator alone). Sixteen inputs bounded by a
  level and held for 60 s each: DC, sines at 1, 10, 20 and 50 kHz, squares at 0.1, 1, 10,
  44.1 and 176.4 kHz, random ±level steps held for 1.4, 5.7, 23 and 363 µs, uniform noise
  held for 2.8 and 23 µs. A run "diverges" when a state leaves its normal range by a
  factor of about 1000; the count is the number of such events. This is harsher than
  anything the interpolators deliver (a square with instant edges at the limit), and it
  does not depend on the rest of the chain. The 1.4 µs random steps (705.6 kHz) are
  not used for decisions: no input the chain accepts can switch that fast (its widest
  input, 352.8 kHz PCM, ends at 176.4 kHz).
- **Stability study** (the stability study's harness, `tools/stability/stab.py`, through the
  command-line tool): see [below](#stability-study). Its successor with the 48 kHz-family
  sources, `tools/stability/gate.py`, is the [acceptance gate](#acceptance-gate).

## What sets the in-band noise

The earlier tables spread their zeros over 0 to 50 kHz (DSD128) and 0 to 80 kHz (DSD256). That
choice, not the order, is most of the gap. Order 6, modulator alone, SINAD at −3 dB SACD:

| Output | Zeros over | H_inf | SINAD (dB) | Noise 22–96 kHz (dBFS) |
|---|--:|--:|--:|--:|
| DSD128 | 0–50 kHz (earlier) | 1.5 | 123.4 | −71.6 |
| DSD128 | 0–30 kHz | 1.4 | 141.0 | −62.2 |
| DSD128 | 0–24 kHz | 1.4 | 152.5 | −62.1 |
| DSD128 | 0–20 kHz | 1.4 | 161.1 | −61.8 |
| DSD256 | 0–40 kHz | 1.4 | 164.1 | −102.3 |
| DSD256 | 0–30 kHz | 1.4 | 179.4 | −101.1 |
| DSD256 | 0–24 kHz | 1.4 | 191.0 | −100.6 |
| DSD256 | 0–20 kHz | 1.4 | 199.8 | −100.3 |

Narrowing the band from 40 to 20 kHz buys 36 dB in the audio band and costs 2 dB above
it, so the new tables put every zero in 0 to 20 kHz. The noise from 22 to 96 kHz is set by
H_inf and the order, not by the band (below).

## What sets the stable input range

Level at which a 15 s amplitude ramp first diverges, modulator alone at DSD256, zeros over
0 to 20 kHz; "random" is ±level steps held for 5.7 µs. The range depends on H_inf and, for
wideband input, on the order; it does not depend on the band (20 to 40 kHz gave the same
values within 0.03).

| Order | H_inf | DC | 1 kHz sine | 20 kHz sine | 1 kHz square | Random | SINAD at −3 dB SACD (dB) | 22–96 kHz (dBFS) | 100–192 kHz (dBFS) |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 6 | 1.30 | 0.73 | 0.75 | 0.78 | 0.69 | 0.65 | 188.4 | −90.7 | −48.3 |
| 6 | 1.35 | 0.68 | 0.70 | 0.72 | 0.66 | 0.60 | 194.7 | −96.0 | −55.9 |
| 6 | 1.40 | 0.63 | 0.64 | 0.65 | 0.59 | 0.57 | 199.8 | −100.3 | −60.8 |
| 6 | 1.45 | 0.57 | 0.59 | 0.60 | 0.57 | 0.51 | 204.2 | −104.0 | −64.6 |
| 6 | 1.50 | 0.49 | 0.51 | 0.53 | 0.51 | 0.45 | 207.7 | −107.3 | −67.8 |
| 7 | 1.30 | 0.74 | 0.74 | 0.77 | 0.66 | 0.63 | 205.0 | −90.1 | −37.1 |
| 7 | 1.40 | 0.62 | 0.62 | 0.64 | 0.59 | 0.53 | 219.5 | −102.0 | −56.2 |
| 7 | 1.50 | 0.47 | 0.50 | 0.51 | 0.48 | 0.45 | 229.1 | −110.7 | −65.1 |
| 8 | 1.30 | 0.72 | 0.74 | 0.75 | 0.64 | 0.63 | 224.0 | −86.3 | −24.1 |
| 8 | 1.40 | 0.60 | 0.62 | 0.63 | 0.58 | 0.49 | 212.9 (zeros to 30 kHz) | −103.0 | −50.3 |
| 8 | 1.50 | 0.46 | 0.47 | 0.49 | 0.45 | 0.41 | 224.4 (zeros to 30 kHz) | −113.6 | −61.1 |

Three things follow:

1. With H_inf 1.5, as in the earlier tables, no order holds an input of 0.5 (0 dB SACD) with margin. That
   is why the earlier tables clip.
2. In the order 6 rows, each 0.05 of H_inf is worth 0.02 to 0.08 of input range and costs
   3.5 to 6.3 dB in the audio band and 3.3 to 5.3 dB from 22 to 96 kHz. Robustness and low ultrasonic noise pull against
   each other.
3. Tones are not the hard case. Wideband bounded input, which is what a hard limiter leaves
   of hot ultrasonic content, diverges first, and sooner at higher orders.

## Candidates per rate

"Stress" is the number of diverging events in the stress test at ±0.51 / ±0.53, all
signals but the 1.4 µs steps, 60 s each. SINAD at −3 / 0 dB SACD.

### DSD128

| Design | SINAD (dB) | 22–96 kHz (dBFS) | 100–192 kHz (dBFS) | Stress 0.51 / 0.53 | Stability study |
|---|--:|--:|--:|--:|---|
| order 6, wide, H 1.5 (earlier) | 123.5 / 124.8 | −71.9 | −30.8 | 558,785 at 0.50 | legal clean; hot fails |
| order 5, 0–20 kHz, H 1.38 | 142.9 / 145.6 | −62.2 | −31.3 | 0 / not run | clean, legal and hot |
| **order 6, 0–20 kHz, H 1.36** | 157.1 / 159.9 | −56.4 | −29.1 | 0 / 0 (0 at 0.55) | clean, legal and hot |
| order 6, 0–20 kHz, H 1.38 | 159.1 / 161.9 | −59.9 | −31.1 | 0 / 0 (1 to 2 at 0.55) | legal clean; hot random 333 / 4 |
| order 6, 0–20 kHz, H 1.40 | 160.8 / 163.7 | −60.3 | −28.4 | 0 / 2 to 9 | not run |
| order 6, 0–20 kHz, H 1.42 | not run | not run | not run | 0 to 1 / 47 to 50 | not run |
| order 7, 0–20 kHz, H 1.30 | 161.3 / 164.7 | −38.7 | −32.4 | 0 at 0.50, 3 at 0.52 | not run |
| order 7, 0–20 kHz, H 1.36 | 170.3 / 173.3 | −50.9 | −27.0 | 5.7 µs random steps diverge at 0.51 | legal clean; hot random 81,782 / 1,120 |
| order 7, 0–20 kHz, H 1.40 | 175.1 / 177.6 | −56.0 | −26.3 | 9 at 0.50 | legal fails: 330 / 4 |
| order 8, 0–20 kHz, H 1.30 | 173.7 / 176.4 | −24.9 | −30.2 | 1,640 at 0.50 | legal clean; hot fails |
| order 8, 0–20 kHz, H 1.35 | 182.2 / 185.0 | −39.5 | −25.6 | not run | legal fails: 2,535 / 37 |
| order 8, 0–20 kHz, H 1.40 | withdrawn | −50.3 | −23.7 | 840 at 0.50 | legal fails: 32,411 / 454 |
| order 7, one zero pair at 60 kHz, H 1.35 | 138.4 / 141.4 | −56.6 | −31.1 | 0 / 0 | not run |

Rows in the stress column marked "at 0.50" or "at 0.52" are from an earlier run at those
levels. Figures of the rows without a stability-study entry are for the modulator alone.

Order 6 at H 1.36 has the highest SINAD of the designs that are clean on every legal and hot
signal; order 5 at H 1.38, also clean, has 5.8 dB less noise from 22 to 96 kHz and 14.2 dB
less SINAD at −3 dB SACD.
Order 6 at H 1.38 gains 2 dB and resets four times on hot random input. Order 7 gains 13 dB and stays
clean on legal input only at H 1.36 or below. Order 8 at H 1.40 fails legal input 32,411
times in 60 s (its SINAD figure is withdrawn); made safe on legal input (H 1.30) it
reads 3 dB higher SINAD than order 7 at −3 dB SACD and 26 dB more noise from 22 to 96 kHz.

### DSD256

| Design | SINAD (dB) | 22–96 kHz (dBFS) | 100–192 kHz (dBFS) | Stress 0.51 / 0.53 | Stability study |
|---|--:|--:|--:|--:|---|
| order 5, wide, H 1.5 (earlier) | 126.2 / 129.1 | −113.7 | −71.2 | not run | clean, legal and hot |
| order 5, 0–20 kHz, H 1.38 | 175.3 / 177.8 | −95.9 | −62.3 | 0 / not run | clean, legal and hot |
| **order 6, 0–20 kHz, H 1.36** | 195.8 / 198.6 | −97.0 | −57.0 | 0 / 0 (0 at 0.55) | clean, legal and hot |
| order 6, 0–20 kHz, H 1.38 | 197.9 / 200.5 | −98.7 | −59.0 | 0 / 0 (3 at 0.55) | clean, legal and hot |
| order 6, 0–20 kHz, H 1.40 | 199.6 / 202.6 | −100.4 | −60.8 | 0 / 1 | not run |
| order 7, 0–20 kHz, H 1.36 | 214.4 / 217.7 | −97.9 | −51.1 | 0 / not run | clean, legal and hot |
| order 8, 0–20 kHz, H 1.35 | 232.4 / 234.8 | −95.0 | −39.2 | not clean at 0.51 | clean, legal and hot |
| order 7, one zero pair at 90 kHz, H 1.35 | 175.1 / 178.3 | −112.8 | −52.7 | 0 / 0 (0 at 0.55) | not run |
| order 7, one zero pair at 90 kHz, H 1.38 | 179.7 / 182.2 | −116.1 | −56.7 | 0 / 1 | not run |
| order 7, one zero pair at 75 kHz, H 1.38 | 182.7 / 185.3 | −109.9 | −55.7 | not run | not run |
| order 8, one zero pair at 110 kHz, H 1.38 | 195.9 / 198.8 | −105.5 | −51.7 | not run | not run |

At DSD256 the default is already at the floor a 32-bit input allows, so the open choice is
ultrasonic noise. Moving one zero pair of an order 7 loop to 90 kHz gives −116 dBFS from 22
to 96 kHz (2.4 dB below the earlier table, 8.4 dB below SoX `sdm-8`) for 16 dB of in-band SINAD
(182 dB). It was not chosen: one rule for every rate is simpler to explain and to test,
order 6 has the larger stress margin, and −97 dBFS is 68 dB below what DSD64 carries in
that band. It is the first candidate if ultrasonic noise at DSD256 should rank above the
in-band figure, as a mode of its own in a later release.

### DSD64 (from PCM)

| Design | SINAD (dB) | 22–96 kHz (dBFS) | 100–192 kHz (dBFS) | Stress 0.51 / 0.53 | Stability study |
|---|--:|--:|--:|--:|---|
| order 6, wide, H 1.5 (earlier) | 125.5 / 128.1 | −28.6 | −20.9 | fails at 0.51, with DC (11 events) and a 1 kHz sine (1) among the signals | legal fails: 12 / 0 |
| order 5, wide, H 1.5 | 114.6 / 117.3 | −40.9 | −25.1 | not run | legal clean; hot fails |
| order 5, 0–20 kHz, H 1.38 | 110.0 / 113.0 | −42.5 | −27.8 | not run | clean, legal and hot |
| **order 6, 0–20 kHz, H 1.36** | 118.2 / 121.1 | −28.9 | −24.9 | only the 176.4 kHz square diverges at 0.51 | clean, legal and hot |
| order 6, 0–20 kHz, H 1.30 | 111.7 / 114.1 | −30.9 | −26.1 | 0 / 0 | not run |
| order 6, 0–20 kHz, H 1.40 | 121.9 / 124.8 | −27.7 | −23.8 | 47,583 / 24,327 | not run |
| order 7, 0–20 kHz, H 1.36 | 125.7 / 129.0 | −39.5 | −27.7 | not run | legal clean; hot random 145 / 2 |
| order 8, 0–20 kHz, H 1.35 | 131.4 / 134.1 | −24.4 | −23.6 | not run | legal clean; hot random 3,478 / 52 |

At DSD64 a 176.4 kHz square is a sixteenth of the sample rate and no design at a useful
H_inf holds one at ±0.51 when driven directly; through the chain, whose interpolators
round its edges, the default is clean on every legal and hot signal. DSD64 has little to
give: order 7 would restore the earlier SINAD (129.0 dB) and is clean on legal input, but it
resets on hot random input, so order 6 is the default here too.

## The tables that ship

`tables.rs` holds 24 modulator tables: twelve audio-band ones, zeros over 0 to 20 kHz,
of which the library uses eleven (order 8 at DSD128 is refused, see the
[acceptance gate](#acceptance-gate)), and the twelve earlier wide-band ones, unchanged,
which only the reference-vector test of the recurrence still reads.

| Order | H_inf, audio band |
|--:|---|
| 5 | 1.38 |
| 6 | 1.36 |
| 7 | 1.36 |
| 8 | 1.35 (DSD64, DSD256), 1.30 (DSD128) |

The rule: the highest H_inf, in the steps tried, at which the table is clean on every
legal signal of the stability study at every rate; order 6 also had to be clean on every
hot signal. Order 8 at DSD128 needed 1.30, and with the 48 kHz-family sources added to
the set afterwards it still fails one legal signal, so it is not accepted.

The audio-band states are scaled by powers of two measured with `tools/modulator/scale.py`
(the largest state value over the stress signals at ±0.51, 60 s each, rounded up so that
the states stay within ±0.75). Powers of two make the scaled recurrence produce exactly the
bits of the unscaled one, which `gen_tables.py` checks. The state clip stays at 1.5 and the
reset at 64 consecutive clipped samples: with these tables they are a last resort that no
test reached at the defaults.

## The earlier tables

The earlier ("wide") tables spread their zeros to 22.05 kHz (DSD64), 50 kHz (DSD128) or
80 kHz (DSD256) with H_inf 1.5. Builds before this release could select them with a band
option; this release has no such option, and the library refuses every band but the
audio band. The reason is the rule of the [acceptance gate](#acceptance-gate): a
combination is accepted only if, at its default input limit, it clips no modulator state
and never resets on the legal 60 s set. Clipped states / resets of the wide tables, next
to the audio tables, summed over the 29 legal signals of the
[stability study](#stability-study), three sines held at 0 dB SACD for 60 s (1, 10 and
20 kHz) and, for DSD128 and DSD256, three DSD64 tones (1 kHz at 0 and +3 dB SACD, 19 kHz at
0 dB SACD, from the test-tone generator of that build, whose loud tones were not clean
streams, see [headroom](#headroom)): 32 signals at DSD64, 35 at DSD128 and DSD256 (the 48 kHz-family sources of
the gate were added later and were not run on the wide tables):

| Tables | Order | Limit | DSD64 | DSD128 | DSD256 |
|---|--:|--:|--:|--:|--:|
| audio | 5, 6, 7, 8 | 0.51 | 0 / 0 each | 0 / 0 each | 0 / 0 each |
| audio | 6 | 0.53, 0.55 | 0 / 0 | 0 / 0 | 0 / 0 |
| wide | 5 | 0.5073, 0.51, 0.53 | 0 / 0 | 0 / 0 | 0 / 0 |
| wide | 5 | 0.55 | 0 / 0 | 2,504 / 0 | 110 / 0 |
| wide | 6 | 0.51 | 1 / 0 | 2 / 0 | 150 / 0 |
| wide | 6 | 0.5073 | 3 / 0 | 2 / 0 | 140 / 0 |
| wide | 7 | 0.51 | 1,411 / 4 | 1,385 / 0 | 2,404 / 0 |
| wide | 7 | 0.5073 | 1,509 / 4 | 1,469 / 0 | 1,821 / 0 |
| wide | 8 | 0.51 | 9,918 / 24 | 172,691 / 982 | 16,289 / 0 |
| wide | 8 | 0.5073 | 9,542 / 24 | 175,038 / 995 | 14,570 / 0 |

The wide rows were measured on 0.1.0-rc1, the last build with the option. Rows above the
default limit show the margin: the legal set stays clean with the audio tables at order 6
up to a limit of 0.55, and with the wide tables at order 5 up to 0.53.

- **Wide at orders 6 to 8 cannot be accepted.** Order 6, the order the band option used by
  default, clips on sines held at 0 dB SACD (1 clipped state at DSD64; 6 and 4 at 1 and
  10 kHz at DSD256) and on random full-scale samples. A lower limit does not help: at
  0.5073 the counts are 3, 2 and 140, and at 0.5 a tone at 0 dB SACD is itself limited
  ([input limit](#input-limit)).
- **Wide at order 5 passes, and was still left out.** What it would offer, against the
  audio tables (1 kHz tone, 64-bit float input at 88.2 kHz, through the command-line tool; noise with
  the tone at −60 dB SACD):

  | Output | Tables, order | SINAD at −3 / 0 dB SACD (dB) | Noise 22–96 kHz (dBFS) | Legal set | Hot signals (10) |
  |---|---|--:|--:|--:|--:|
  | DSD64 | audio, 5 | 110.0 / 113.0 | −42.5 | 0 / 0 | 0 / 0 |
  | DSD64 | audio, 6 (default) | 118.2 / 121.1 | −28.9 | 0 / 0 | 0 / 0 |
  | DSD64 | wide, 5 | 114.6 / 117.3 | −40.9 | 0 / 0 | 921,712 / 8,322 |
  | DSD128 | audio, 5 | 142.9 / 145.6 | −62.2 | 0 / 0 | 0 / 0 |
  | DSD128 | audio, 6 (default) | 157.1 / 159.9 | −56.4 | 0 / 0 | 0 / 0 |
  | DSD128 | wide, 5 | 112.2 / 115.0 | −72.0 | 0 / 0 | 0 / 0 |
  | DSD256 | audio, 5 | 175.3 / 177.8 | −95.9 | 0 / 0 | 0 / 0 |
  | DSD256 | audio, 6 (default) | 195.8 / 198.6 | −97.0 | 0 / 0 | 0 / 0 |
  | DSD256 | wide, 5 | 126.2 / 129.1 | −113.7 | 0 / 0 | 0 / 0 |

  At DSD64 it has no lower ultrasonic noise than order 5 of the audio tables. At DSD128
  and DSD256 it measures 15.6 and 16.7 dB less noise from 22 to 96 kHz than the
  default, for 44.9 and 69.5 dB less SINAD at 0 dB SACD, with less margin (the
  0.55 row), and on hot input at DSD64 it overloads (921,712 clipped states and 8,322 resets in the
  10 hot signals, at limit 0.51).
  Accepting it would also mean a band whose only order is not the default order. A
  low-ultrasonic-noise mode designed under the rule of [the tables that ship](#the-tables-that-ship)
  is the better addition: at DSD256 a candidate of [the study](#dsd256) (order 7, one zero
  pair at 90 kHz, H_inf 1.35) measures −112.8 dBFS from 22 to 96 kHz with a SINAD of
  178.3 dB at 0 dB SACD (modulator alone), against −113.7 dBFS and 129.1 dB for wide at
  order 5. Adding a band later changes nothing for existing users; removing one would.

The decision is recorded in [design](design.md#decisions).

## Orders 7 and 8

`--order 7` stays selectable at every rate and `--order 8` at DSD64 and DSD256. Order 8 at
DSD128 is refused: it is clean on the legal signals from 88.2 and 352.8 kHz but clips on a
full-scale square at a quarter of the sample rate from 384 kHz PCM
([acceptance gate](#acceptance-gate)). 60 s runs:

| Output | Order | SINAD at −3 / 0 dB SACD (dB) | 22–96 kHz (dBFS) | Legal signals | Hot signals |
|---|--:|--:|--:|---|---|
| DSD64 | 7 | 125.7 / 129.0 | −39.5 | clean | random ±2 FS at 352.8 kHz: 145 clipped, 2 resets |
| DSD64 | 8 | 131.4 / 134.1 | −24.4 | clean | random ±2 FS at 352.8 kHz: 3,478 / 52 |
| DSD128 | 7 | 170.3 / 173.3 | −50.9 | clean | random ±2 FS at 352.8 kHz: 81,782 / 1,120 |
| DSD128 | 8 (refused) | 173.7 / 176.4 | −24.9 | 96 kHz square from 384 kHz: 58,116 clipped, 823 resets | random ±2 FS at 352.8 kHz: 480,143 / 6,782; 88.2 kHz square: 27,437 / 392 |
| DSD256 | 7 | 214.4 / 217.7 | −97.9 | clean | clean |
| DSD256 | 8 | 232.4 / 234.8 | −95.0 | clean | clean |

Use them for material known to stay within full scale. At DSD128 order 8 had little over
order 7: 3 dB of SINAD for 26 dB more noise from 22 to 96 kHz. Beyond about 190 dB the figures are properties of the arithmetic only: no
input format but 64-bit float carries them.

## Input limit

The limit is 0.51 (0.17 dB above 0 dB SACD). At 0.5 a tone at exactly 0 dB SACD is itself
limited: interpolator ripple lifts its peaks above 0.5, as the counts at 0.51 below show.
At 0.51, 60 s holds through the reference measurements still limit a few samples: a 1 kHz
tone at exactly 0 dB SACD has 53, 106 and 212 limited samples in 60 s at DSD64, DSD128 and
DSD256 (3 × 10⁻⁷ of them), a 10 kHz tone 9, 17 and 35, a 20 kHz tone none
([DSD measurements](measurements-dsd.md#hot-input)). Limits 0.5073 and 0.51 are both clean on
every legal and hot signal with the default tables ([stability study](#stability-study));
0.51 leaves 0.05 dB more room for interpolator overshoot.
The stress test is clean to ±0.55 at DSD128 and DSD256, 0.66 dB above the limit.

## Stability study

The study behind the default, made with the stability study's harness (`tools/stability/stab.py`;
the [acceptance gate](#acceptance-gate) later added the 48 kHz-family sources):
29 legal signals (PCM within full scale at a gain of −3 dB, the default when the study was
made; the default is now −6 dB, see [headroom](#headroom), and `--gain -3` is the louder
setting) and 10 hot ones (the same kind of signal with `--gain 3`, 6 dB louder still), 60 s each,
through the command-line tool. Legal: sines at 1, 5 and 10 kHz overdriven 2× and 4× and
clipped at full scale, DC at 0.5, 0.75, 1 and −1, white and pink noise at 0 and −3 dBFS,
random ±full-scale samples at 88.2 and 352.8 kHz, squares at 1 kHz, 10 kHz, a quarter and
half of the sample rate at 88.2 and 352.8 kHz, a full-scale 20 kHz sine at 352.8 kHz,
steps and impulses. Hot: the 4× clipped sines at 1 and 10 kHz, DC 1, white and pink
noise, random ±full scale at 352.8 kHz, a 10 kHz square at 88.2 kHz, the 88.2 and 176.4 kHz
squares at 352.8 kHz and the 20 kHz sine. Legal PCM reaches the modulator at up to
+5.0 dB SACD (intersample peaks of random full-scale samples) and is limited there; the
limiter's work is not counted as an overload.

Clipped states / resets, summed over the signals of each group:

| Output | Order, band | Limit | Legal (29) | Hot (10) | Signals that overload |
|---|---|--:|--:|--:|---|
| DSD64 | 6, audio (default) | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD64 | 6, audio | 0.5073 | 0 / 0 | 0 / 0 | none |
| DSD64 | 5, audio | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD64 | 7, audio | 0.51 | 0 / 0 | 145 / 2 | hot random 352.8 kHz |
| DSD64 | 8, audio | 0.51 | 0 / 0 | 3,478 / 52 | hot random 352.8 kHz |
| DSD64 | 6, wide (earlier default) | 0.5 | 12 / 0 | 137,648,804 / 6 | legal 88.2 kHz square; hot: 7 of 10 |
| DSD64 | 5, wide | 0.5073 | 0 / 0 | 27,530 / 197 | hot random and 88.2 kHz square at 352.8 kHz |
| DSD128 | 6, audio (default) | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD128 | 6, audio | 0.5073 | 0 / 0 | 0 / 0 | none |
| DSD128 | 5, audio | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD128 | 7, audio | 0.51 | 0 / 0 | 81,782 / 1,120 | hot random 352.8 kHz |
| DSD128 | 8, audio | 0.51 | 0 / 0 | 507,580 / 7,174 | hot random and 88.2 kHz square at 352.8 kHz |
| DSD128 | 6, wide (earlier default) | 0.5 | 0 / 0 | 317,509,011 / 18 | hot: 7 of 10 |
| DSD128 | 5, wide | 0.5073 | 0 / 0 | 0 / 0 | none |
| DSD256 | 6, audio (default) | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD256 | 5, 7 and 8, audio | 0.51 | 0 / 0 | 0 / 0 | none |
| DSD256 | 5, wide (earlier default) | 0.5 | 0 / 0 | 0 / 0 | none |

This table is the study as first run, from 88.2 and 352.8 kHz sources only. The
[acceptance gate](#acceptance-gate) runs a larger legal set on every combination; it is
what found order 8 at DSD128.

Tones and intermodulation at the defaults (and orders 7 and 8 at DSD128), 64-bit float
input at a 0 dB SACD peak; nothing was limited, clipped or reset in any of these runs:

| Output | Order | SINAD at −3 dB SACD (dB) | THD+N at 0 dB SACD (dB) | CCIF 19 + 20 kHz (dB) | SMPTE (dB) | Multitone range (dB) |
|---|--:|--:|--:|--:|--:|--:|
| DSD64 | 6 | 118.2 | −121.3 | −113.6 | −121.9 | 125.1 |
| DSD128 | 6 | 157.1 | −159.8 | −150.9 | −158.1 | 163.6 |
| DSD128 | 7 | 170.2 | −173.2 | −162.1 | −176.2 | 176.9 |
| DSD128 | 8 | 173.9 | −176.7 | −162.1 | −172.1 | 178.7 |
| DSD256 | 6 | 195.8 | −198.6 | −185.7 | −194.8 | 200.5 |

Error left in the audio band (20 Hz to 20 kHz) beyond an ideal hard limiter fed the same
modulator input, in dB re 0 dB SACD: the range over the signals of the whole-file figure,
and the worst 10 ms of the worst signal. Where nothing overloads this is the modulator's
own noise.

| Output | Order | Legal, whole file (dB) | Legal, worst 10 ms (dB) | Hot, whole file (dB) | Hot, worst 10 ms (dB) |
|---|--:|--:|--:|--:|--:|
| DSD64 | 6 (default) | −122.7 to −107.9 | −106.5 | −123.5 to −107.8 | −106.2 |
| DSD128 | 6 (default) | −161.7 to −144.1 | −142.6 | −161.2 to −143.9 | −142.5 |
| DSD256 | 6 (default) | −200.8 to −180.2 | −178.8 | −200.3 to −180.0 | −178.7 |
| DSD128 | 7 | −175.5 to −158.0 | −156.6 | −175.0 to −43.0 | −27.2 |
| DSD128 | 8 | −178.8 to −159.0 | −157.5 | −178.8 to −32.3 | −21.6 |

For comparison, the earlier DSD256 default (order 5, wide) left −131 to −128 dB over the
whole file and at most −122.5 dB in the worst 10 ms, and the earlier DSD64 default left a
−57 dB error in the worst 10 ms of a legal signal. An overload is a large error: orders 7
and 8 at DSD128 leave −27 and −22 dB in the worst 10 ms of hot random input.

## Acceptance gate

The rule: the command-line tool, the library and the C interface accept a combination of
band, order and output rate only if, at its default input limit, it clips no modulator
state and never resets on the 60 s set, at the default gain and at the louder setting
`--gain -3`, and limits nothing on the legal signals at the default gain
([headroom](#headroom)). A combination that cannot meet this is refused; none is shipped
with a warning. `accepted_orders` in the library is the list.

The set, 60 s per signal through the command-line tool (`tools/stability/gate.py`):

- the 29 PCM signals of the stability study, from 88.2 and 352.8 kHz;
- 23 signals through the 48 kHz-family resampler: random ±full-scale samples, squares at
  1 kHz, 10 kHz, a quarter and half of the sample rate, steps and impulses at 48, 96 and
  384 kHz, and a full-scale 20 kHz sine at 96 and 384 kHz;
- three sines held at 0 dB SACD (1, 10 and 20 kHz), which takes `--gain 6.0206` on a
  −6.02 dBFS source;
- for DSD128 and DSD256, fifteen DSD tones from `dsd-upsample gen` at DSD64, DSD128 and
  DSD256 input: 1 and 19 kHz at 0 dB SACD, and 1, 10 and 19 kHz held at +3.1 dB SACD.

Of the 52 PCM signals, 47 are legal input (true peak at most +6 dBTP) and 5 are beyond it
(random ±full-scale samples at 48, 88.2, 96 and 384 kHz and white noise peaking at full
scale, true peaks +6.24 to +8.00 dBTP): the limiter may work on those. With the DSD tones
that is 47 legal signals at DSD64 and 62 at DSD128 and DSD256. Each cell is limited samples / clipped
states / resets, summed over the group, at the default limit 0.51, measured on the code
of this release. "Louder" is the 52 PCM signals again with `--gain -3` (the default of
earlier builds, and the condition of the stability study above); "hot" is the study's 10
hot signals with `--gain 3`, 9 dB above the default, and does not decide acceptance.

| Output | Order | Legal signals | Legal | Holds at 0 dB SACD | Beyond +6 dBTP | Louder (`--gain -3`) | Hot (`--gain 3`) | Passes |
|---|--:|--:|--:|--:|--:|--:|--:|---|
| DSD64 | 5 | 47 | 0 / 0 / 0 | 62 / 0 / 0 | 448,229 / 0 / 0 | 82,126,587 / 0 / 0 | 1,013,914,709 / 0 / 0 | yes |
| DSD64 | 6 (default) | 47 | 0 / 0 / 0 | 62 / 0 / 0 | 448,229 / 0 / 0 | 82,126,587 / 0 / 0 | 1,013,914,709 / 0 / 0 | yes |
| DSD64 | 7 | 47 | 0 / 0 / 0 | 62 / 0 / 0 | 448,229 / 0 / 0 | 82,126,587 / 0 / 0 | 1,013,914,709 / 145 / 2 | yes |
| DSD64 | 8 | 47 | 0 / 0 / 0 | 62 / 0 / 0 | 448,229 / 0 / 0 | 82,126,587 / 0 / 0 | 1,013,914,709 / 3,478 / 52 | yes |
| DSD128 | 5 | 62 | 0 / 0 / 0 | 123 / 0 / 0 | 896,353 / 0 / 0 | 163,929,960 / 0 / 0 | 2,038,383,816 / 0 / 0 | yes |
| DSD128 | 6 (default) | 62 | 0 / 0 / 0 | 123 / 0 / 0 | 896,353 / 0 / 0 | 163,929,960 / 0 / 0 | 2,038,383,816 / 0 / 0 | yes |
| DSD128 | 7 | 62 | 0 / 0 / 0 | 123 / 0 / 0 | 896,353 / 0 / 0 | 163,929,960 / 0 / 0 | 2,038,383,816 / 81,782 / 1,120 | yes |
| DSD256 | 5 | 62 | 0 / 0 / 0 | 247 / 0 / 0 | 1,792,737 / 0 / 0 | 328,024,335 / 0 / 0 | 4,109,186,787 / 0 / 0 | yes |
| DSD256 | 6 (default) | 62 | 0 / 0 / 0 | 247 / 0 / 0 | 1,792,737 / 0 / 0 | 328,024,335 / 0 / 0 | 4,109,186,787 / 0 / 0 | yes |
| DSD256 | 7 | 62 | 0 / 0 / 0 | 247 / 0 / 0 | 1,792,737 / 0 / 0 | 328,024,335 / 0 / 0 | 4,109,186,787 / 0 / 0 | yes |
| DSD256 | 8 | 62 | 0 / 0 / 0 | 247 / 0 / 0 | 1,792,737 / 0 / 0 | 328,024,335 / 0 / 0 | 4,109,186,787 / 0 / 0 | yes |

Order 8 at DSD128 is not in the table: it is refused. In the gate run that decided it (at
a gain of −3 dB) it clipped 58,116 states and reset 823 times, all on one signal, the
full-scale square at a quarter of the sample rate from 384 kHz PCM (a 96 kHz square through
the resampler). The holds are limited where the tone starts and nowhere else
([input limit](#input-limit)). The hot overloads of orders 7 and 8 are on input 9 dB above
the default gain.

SINAD and noise of each combination, for a 1 kHz tone from 64-bit float PCM at 88.2 kHz that reaches
the modulator at −3 and at 0 dB SACD, and noise for the tone at −60 dB SACD
(`tools/stability/gate_metrics.py`; these do not depend on the default gain, because the
tool sets the level at the modulator):

| Output | Order | SINAD at −3 / 0 dB SACD (dB) | Noise 22–96 kHz (dBFS) | Noise 100–192 kHz (dBFS) |
|---|--:|--:|--:|--:|
| DSD64 | 5 | 110.0 / 113.0 | −42.5 | −27.8 |
| DSD64 | 6 (default) | 118.2 / 121.1 | −28.9 | −24.9 |
| DSD64 | 7 | 125.7 / 129.0 | −39.5 | −27.7 |
| DSD64 | 8 | 131.4 / 134.1 | −24.4 | −23.6 |
| DSD128 | 5 | 142.9 / 145.6 | −62.2 | −31.3 |
| DSD128 | 6 (default) | 157.1 / 159.9 | −56.4 | −29.1 |
| DSD128 | 7 | 170.3 / 173.3 | −50.9 | −27.0 |
| DSD256 | 5 | 175.3 / 177.8 | −95.9 | −62.3 |
| DSD256 | 6 (default) | 195.8 / 198.6 | −97.0 | −57.0 |
| DSD256 | 7 | 214.4 / 217.7 | −97.9 | −51.1 |
| DSD256 | 8 | 232.4 / 234.8 | −95.0 | −39.2 |

`crates/dsd-upsample/tests/stability.rs` runs the same rules for 1.5 s per signal on every
combination the library accepts (`accepted_orders`), from 88.2 and 352.8 kHz and through the
resampler from 48, 96 and 384 kHz: nothing limited on legal input at the defaults, no
clipped state and no reset at the defaults, with `--gain -3`, on the sines at 0 dB SACD and
on the DSD tones at +3.1 dB SACD; at the default order it does the same with `--gain 3`.

Reproduce (needs NumPy and the measurement tools):

```sh
cargo build --locked --release -p dsd-upsample-cli
python tools/stability/gate.py run --work target/gate --cands 64:5:default,64:6:default,64:7:default,64:8:default,128:5:default,128:6:default,128:7:default,256:5:default,256:6:default,256:7:default,256:8:default --louder --hot
python tools/stability/gate.py table --work target/gate
python tools/stability/gate.py headroom --work target/gate
python tools/stability/gate_metrics.py target/gate/metrics.jsonl --work target/gate/tones 128:6:default
```

## Headroom

The rule: at the default settings, legal input is not limited. The limit cannot move up
(0.51 is where the modulators stay stable, [input limit](#input-limit)), so the default
gain sets the headroom: −6 dB puts the limit 6.17 dB above the nominal level, at
+6.17 dBTP for PCM and at 101.8 % modulation (+6.17 dB SACD) for DSD.

**Levels.** 0 dB SACD is 50 % modulation ("0 dB-SACD = 50% modulation index",
[Cirrus Logic CS4398 data sheet](https://www.manualsdir.com/manuals/466334/cirrus-logic-cs4398.html?page=9), note 3),
and Roon's documentation describes Super Audio CD authoring as keeping the signal 6 dB
below PCM full scale, which its DSD to PCM conversion undoes by default
([Roon, DSD to PCM settings](https://help.roonlabs.com/portal/en/kb/articles/dsd-to-pcm-settings)):
in that alignment PCM full scale and 0 dB SACD are at the same level. A gain of 0 dB is that
alignment here: PCM full scale reaches the modulator at 0 dB SACD (50 % modulation), and
it is the loudest setting a full-scale sine survives (the limit is 51 %). At the default
gain PCM full scale is at −6 dB SACD, 25 % modulation, and DSD input comes out 6 dB lower
than it went in (`tests/stability.rs` measures the two PCM levels as bit density). The output is
therefore 6 dB quieter than a disc mastered to the reference level; that is the headroom.

**Legal input**, in three parts:

1. *DSD tones up to the Super Audio CD peak level.* Public descriptions of the format give
   +3.1 dB SACD (71.4 % modulation) as the highest peak level
   ([Archimago, 2022](https://archimago.blogspot.com/2022/06/notes-on-dac-dsd-1-bit-pdm-measurements.html)).
   The set holds tones at +3.1 dB SACD for 60 s at 1, 10 and 19 kHz, from DSD64, DSD128
   and DSD256; the legal range is any tone from 20 Hz to 20 kHz up to that level.
2. *PCM within full scale whose true peak is at most +6 dBTP.* Samples within full scale
   do not bound the waveform between them: the true peak
   ([ITU-R BS.1770](https://www.itu.int/rec/R-REC-BS.1770)) of a sine at a quarter of the
   sample rate sampled at 45° is +3.01 dBTP, and clipped masters go higher. A public scan
   of about 107,000 tracks with a BS.1770 true-peak meter
   ([Archimago, 2025](https://archimago.blogspot.com/2025/08/a-look-at-music-library-how-much.html))
   found 99 % of the tracks of each genre below a level between +0.79 dBTP (classical) and
   +4.22 dBTP (electronica; rock +2.35, pop +2.87, hip-hop +3.08), a highest
   rock track at +5.88 dBTP among 31,400, and a highest track overall at +7.72 dBTP;
   [Benchmark Media](https://benchmarkmedia.com/blogs/application_notes/intersample-overs-in-cd-recordings)
   reports up to +1.49 dBFS on the commercial tracks it examined; an early paper on the
   effect is [Nielsen and Lund, 2000](https://www.aes.org/e-lib/browse.cfm?elib=9087). +6 dBTP
   covers the 99th percentile of every genre of that scan with 1.8 dB to spare and its
   highest rock track; it does not cover its highest track.
3. *Real files:* the test music set (below), except four tracks whose level is beyond
   100 % modulation.

PCM within full scale is not legal input as such: the true peak of random ±full-scale
samples grows with their length (+5.09 to +8.00 dBTP in 60 s here), and white noise
peaking at full scale reaches +6.24 dBTP. What exceeds +6.17 dBTP is limited and counted,
and never overloads the modulator.

**Peaks at the modulator input**, by the highest `--gain` at which nothing is limited
(`gate.py headroom`, 60 s per signal, search to 0.01 dB; dBTP for PCM, dB SACD for DSD):

| Signal | Peak at the modulator input | Highest gain with nothing limited (dB) | Margin at −6 dB (dB) | Group |
|---|--:|--:|--:|---|
| Random ±full-scale samples, 88.2 kHz | +8.00 dBTP | −7.83 | −1.83 | beyond +6 dBTP |
| Random ±full-scale samples, 96 kHz | +7.28 dBTP | −7.11 | −1.11 | beyond +6 dBTP |
| Random ±full-scale samples, 384 kHz | +7.25 dBTP | −7.08 | −1.08 | beyond +6 dBTP |
| Random ±full-scale samples, 48 kHz | +7.21 dBTP | −7.04 | −1.04 | beyond +6 dBTP |
| White noise peaking at 0 dBFS | +6.24 dBTP | −6.07 | −0.07 | beyond +6 dBTP |
| Random ±full-scale samples, 352.8 kHz | +5.09 dBTP | −4.92 | +1.08 | legal |
| 10 kHz square, 48 kHz | +3.89 dBTP | −3.72 | +2.28 | legal |
| DSD64 tone, 19 kHz at +3.1 dB SACD | +3.26 dB SACD | −3.09 | +2.91 | legal |
| DSD128 tone, 19 kHz at +3.1 dB SACD | +3.23 dB SACD | −3.06 | +2.94 | legal |
| DSD256 tone, 19 kHz at +3.1 dB SACD | +3.22 dB SACD | −3.05 | +2.95 | legal |
| DSD64 tone, 10 kHz at +3.1 dB SACD | +3.18 dB SACD | −3.01 | +2.99 | legal |
| Square at a quarter of the sample rate, 384 kHz | +3.17 dBTP | −3.00 | +3.00 | legal |
| Square at a quarter of the sample rate, 48 kHz | +3.16 dBTP | −2.99 | +3.01 | legal |
| Square at a quarter of the sample rate, 96 kHz | +3.16 dBTP | −2.99 | +3.01 | legal |
| DSD64 tone, 1 kHz at +3.1 dB SACD | +3.14 dB SACD | −2.97 | +3.03 | legal |
| DSD128 tone, 10 kHz at +3.1 dB SACD | +3.12 dB SACD | −2.95 | +3.05 | legal |
| Square at a quarter of the sample rate, 88.2 kHz | +3.11 dBTP | −2.94 | +3.06 | legal |
| Square at a quarter of the sample rate, 352.8 kHz | +3.11 dBTP | −2.94 | +3.06 | legal |
| DSD128 tone, 1 kHz at +3.1 dB SACD | +3.11 dB SACD | −2.94 | +3.06 | legal |
| DSD256 tone, 1 kHz at +3.1 dB SACD | +3.11 dB SACD | −2.94 | +3.06 | legal |
| DSD256 tone, 10 kHz at +3.1 dB SACD | +3.11 dB SACD | −2.94 | +3.06 | legal |
| White noise peaking at −3 dBFS | +3.09 dBTP | −2.92 | +3.08 | legal |
| 10 kHz square, 88.2 kHz | +3.05 dBTP | −2.88 | +3.12 | legal |
| The other 44 signals (squares, steps, clipped sines, DC, pink noise, impulses, 20 kHz sines, DSD tones at 0 dB SACD) | at most +2.51 dB | | at least +3.66 | legal |

**Real files.** Peak at the modulator input of the 332 readable files of the 335-file test
music set (two are at 22.05 kHz, which is not supported, and one FLAC file is truncated),
whole files, all channels, in dBTP for PCM and dB SACD for DSD, measured with a build that
records the largest input the modulator sees (`tools/stability/peak.patch` and
`file_peaks.py`; the released tool reports the limited samples, not the peak):

| Input | Files | Median peak (dB) | Highest peak (dB) | Above +3.17 dB (limited at −3 dB) | Above +4.17 dB (−4 dB) | Above +5.17 dB (−5 dB) | Above +6.17 dB (limited at the default) |
|---|--:|--:|--:|--:|--:|--:|--:|
| PCM (44.1 to 192 kHz) | 139 | −0.26 | +2.15 | 0 | 0 | 0 | 0 |
| DSD64 | 133 | −0.22 | +3.95 | 3 | 0 | 0 | 0 |
| DSD128 | 22 | +0.03 | +6.83 | 5 | 5 | 4 | 4 |
| DSD256 | 38 | −1.82 | +2.16 | 0 | 0 | 0 | 0 |

**The choice.** The smallest headroom that leaves each part of the legal set unlimited,
and what −6 dB leaves to spare:

| Part of the legal set | Highest peak | Needs a gain of at most (dB) | Margin at −6 dB (dB) |
|---|--:|--:|--:|
| 1. DSD tones held at +3.1 dB SACD, 1, 10 and 19 kHz, from DSD64, DSD128 and DSD256 | +3.26 dB SACD | −3.09 | 2.91 |
| 2. PCM true peak up to +6 dBTP | +6.00 dBTP | −5.83 | 0.17 |
| of which: the 99th percentile of every genre of the public scan | +4.22 dBTP | −4.05 | 1.95 |
| of which: the highest rock track of the public scan | +5.88 dBTP | −5.71 | 0.29 |
| of which: the highest legal PCM signal of the gate set (random ±full-scale samples at 352.8 kHz) | +5.09 dBTP | −4.92 | 1.08 |
| 3. Real files: 139 PCM files | +2.15 dBTP | −1.98 | 4.02 |
| 3. Real files: 133 DSD64 files | +3.95 dB SACD | −3.78 | 2.22 |
| 3. Real files: 38 DSD256 files | +2.16 dB SACD | −1.99 | 4.01 |
| 3. Real files: 18 of 22 DSD128 files | +4.76 dB SACD | −4.59 | 1.41 |
| Outside the legal set: 4 DSD128 tracks of one release | +6.76 to +6.83 dB SACD | −6.66 | −0.66 |

The PCM true-peak ceiling binds: −6 dB is the highest gain in whole decibels that passes
+6 dBTP, with 0.17 dB to spare (`tests/stability.rs` pins that margin: a sine with a true
peak of +6 dBTP must have nothing limited). The DSD parts alone would allow −5 dB.

Four tracks of the music set are outside the legal set and are limited at the default
gain: one DSD128 release whose waveform after the input filter reaches 109 to 110 % of
full modulation (+6.76 to +6.83 dB SACD). The tool reports a DC offset on it (an input mean
of −0.70 of full scale on one of the tracks); with `--gain -5` it limits 70 to 79 % of the
samples of both channels and with the default one in a million, so for most of each track
the stream sits between 91 % and 102 % of full modulation, close to a constant bit value. At the default gain these tracks have 3,023 to 4,885 limited samples
per channel out of 3.3 to 4.3 billion (about 1 in a million); with a gain of −5, −4 or
−3 dB, 2.4 to 3.0 billion per channel. The report shows the count for each file; the
warning, which starts at 1 % of a channel's samples, stays silent on them at the default
gain. Limiting nothing on them would take −7 dB (margin 0.34 dB).

Why not −7 dB: it would fit the default to one defective release, cost every conversion
another decibel, and still limit the scan's highest track (+7.72 dBTP). A DSD stream
cannot hold a level above 100 % modulation, and −6 dB passes everything up to there
(100 % × 0.501 is below the limit of 0.51), so that is where the legal set for DSD ends.

Why not −5 or −4 dB: −5 dB limits a true peak above +5.17 dBTP, below the scan's highest
rock track, and limits 70 % of the samples of the four tracks above instead of one in a
million; −4 dB also limits the DSD128 file that peaks at +4.76 dB SACD (1,067 and 118
samples in its two channels) and sits 0.05 dB below the scan's 99th percentile for
electronica. The earlier default of −3 dB limited a clean 19 kHz tone at +3.1 dB SACD
(it needs −3.09 dB), three of the 133 DSD64 files (57 to 2,943 samples per channel) and
five of the 22 DSD128 files.

Why one value for every input: DSD input alone would allow −5 dB, 1 dB more. That gain
would buy nothing measurable (below: with a DSD64 source the SINAD is the source's, at any
gain), it would make the default depend on the input, which the settings of the library
and of the C interface do not know when they are made, and it is the gain at which the
four tracks above are limited 70 % of the time.

**The cost.** The modulator's noise does not move with the gain, so a lower gain lowers the
signal against it by as much. The same source converted at the default and with
`--gain -3`, 1 kHz, SINAD from 20 Hz to 20 kHz (`gate_metrics.py`): a 64-bit float PCM tone
at 0 dBFS and 88.2 kHz, and a DSD64 tone at 0 dB SACD from `gen`; nothing was limited, clipped or reset
in any of these runs.

| Output | Order | PCM 0 dBFS, default gain (dB) | PCM 0 dBFS, `--gain -3` (dB) | Cost (dB) | DSD64 0 dB SACD, default gain (dB) | DSD64 0 dB SACD, `--gain -3` (dB) | Cost (dB) |
|---|--:|--:|--:|--:|--:|--:|--:|
| DSD64 | 5 | 106.8 | 110.2 | 3.4 | n/a | n/a | n/a |
| DSD64 | 6 (default) | 114.7 | 118.2 | 3.5 | n/a | n/a | n/a |
| DSD64 | 7 | 122.4 | 125.7 | 3.4 | n/a | n/a | n/a |
| DSD64 | 8 | 127.8 | 131.3 | 3.6 | n/a | n/a | n/a |
| DSD128 | 5 | 139.6 | 142.6 | 3.0 | 127.9 | 128.1 | 0.2 |
| DSD128 | 6 (default) | 153.7 | 157.1 | 3.4 | 128.5 | 128.5 | 0.0 |
| DSD128 | 7 | 167.0 | 170.2 | 3.2 | 128.5 | 128.5 | 0.0 |
| DSD256 | 5 | 172.1 | 175.3 | 3.2 | 128.5 | 128.6 | 0.0 |
| DSD256 | 6 (default) | 192.2 | 195.8 | 3.6 | 128.6 | 128.6 | 0.0 |
| DSD256 | 7 | 211.3 | 214.4 | 3.1 | 128.6 | 128.6 | 0.0 |
| DSD256 | 8 | 229.2 | 232.4 | 3.2 | 128.6 | 128.6 | 0.0 |

With a PCM source the default costs 3.0 to 3.6 dB of SINAD against `--gain -3`, at every
rate and order: 114.7 instead of 118.2 dB at DSD64, 153.7 instead of 157.1 dB at DSD128
and 192.2 instead of 195.8 dB at DSD256, at the default order. With a DSD64 source it
costs 0.0 to 0.2 dB: the source's own noise (128.6 dB below this tone) is far above the
modulator's at DSD128 and DSD256 and moves with the gain. The noise floor in absolute
terms does not change; the output is 3 dB lower than at −3 dB, and 6 dB below the source.

**The louder setting.** `--gain -3` (or any higher gain) remains available; what then
exceeds the limit is limited and counted per channel in the report and in `--json`, with a
warning above 1 % of a channel's samples.

**Test tones.** `dsd-upsample gen` makes DSD tones up to 0 dB SACD with the order-7
modulator and from there to +3.1 dB SACD with a second-order modulator (two integrators,
noise transfer function (1 − z⁻¹)²), which is stable at 71.4 % modulation where no shipped
table is; its in-band noise is 72, 87 and 102 dB below a 1 kHz tone at DSD64, DSD128 and
DSD256. Higher levels are refused. Earlier builds used order 7 of the earlier tables with
an input limit of 0.7 at every level: that modulator clipped its own states on 13 % of the
samples of a 1 kHz tone at +3 dB SACD at DSD64 (and on 17 samples in 10 s at 0 dB SACD),
so its loud tones were not clean streams, and after the input filter they peaked at 100 %
modulation. A test now checks that the generator's modulator never overloads at a level it
accepts.

## Speed

Whole conversion of 30 s of 88.2 kHz mono PCM, one thread, best of five on an AMD Ryzen AI
Max+ 395 shared with other jobs (indicative only, for comparing the tables with each other),
in ms per channel-second; the controlled timings of the released defaults are in
[measurements](measurements.md#speed):

| Output | wide (earlier default order) | audio order 6 | audio order 7 | audio order 8 |
|---|--:|--:|--:|--:|
| DSD64 | 37.4 (order 6) | 34.3 | 40.4 | not run |
| DSD128 | 67.5 (order 6) | 61.2 | 76.6 | 72.1 |
| DSD256 | 144.3 (order 5), 129.2 (order 6) | 133.8 | 141.3 | 137.3 |

The loop is the same code for every table. At order 6 the new tables took 8 % and 9 % less
time than the earlier ones at DSD64 and DSD128 and 4 % more at DSD256; a higher order costs
more: order 7 took 18 %, 25 % and 6 % more time than order 6 at DSD64, DSD128 and DSD256,
and order 8 18 % (DSD128) and 3 % (DSD256) more.

## Rejected approaches

- **A higher order with a lower H_inf.** At equal stability, order 7 at H 1.30 gives
  164.7 dB at DSD128 against 159.9 dB for order 6 at H 1.36, and −38.7 against −56.4 dBFS
  from 22 to 96 kHz: 5 dB for 18 dB.
- **CLANS pole optimisation** ([Kenney and Carley](https://doi.org/10.1007/BF01239365)), with
  [python-deltasigma](https://github.com/ggventurini/python-deltasigma)'s `clans`. At the
  lower 1-norm bounds tried, the predicted in-band noise at DSD128 was far above that of the
  maximally flat poles; at the higher bounds the NTF gain left a one-bit loop's stable range.
  The optimiser also returned more poles than the order for order 8. Not pursued (an
  exploratory run, not included in this repository).
- **A level-adaptive NTF**: the quiet loop (H_inf 1.5) while the input peak is low, the
  robust one (1.35) near full level. Simulated at DSD128, order 8, by switching
  coefficients at fixed periods. In the feedback form the in-band noise rose far above the
  quiet loop's, because the states depend on the coefficients. In a feed-forward form, whose
  states do not, switching to the robust loop was harmless but returns to the quiet loop
  diverged: the robust loop's normal states lie outside the quiet loop's stable region.
  Interpolating the coefficients gives intermediate NTFs with gains far outside the stable
  range. Dropped (exploratory simulations, not included in this repository).
- **Look-ahead (trellis) modulation**: not built. It runs many candidate loops per sample,
  at many times the cost; SoX-DSD's trellis settings ran slower than real time and, at DSD128
  and DSD256, measured below its plain `sdm-8`
  ([DSD measurements](measurements-dsd.md#all-results)). A candidate for a later, slower mode.

## Reproducing

```sh
python tools/modulator/sweep.py sweep256.jsonl --rates 256 --orders 6,7,8 --hinf 1.3,1.35,1.4,1.45,1.5 --bands 20000,24000,30000,40000 --secs 15
python tools/modulator/metrics.py metrics.jsonl --cands 128:6:1.36:20000,256:7:1.38:20000+90000
python tools/modulator/hold.py hold.jsonl --cands 128:6:1.36:20000,256:6:1.36:20000 --levels 0.51,0.53,0.55 --seeds 1,2
python tools/modulator/scale.py tools/modulator/state_scale.json
python tools/gen_tables.py --check
```

A candidate is `rate:order:H_inf:band`, with `+frequency` for each zero pair moved out of
the band. The simulator needs a C compiler; `sweep.py`, `metrics.py` and `hold.py` need
NumPy and SciPy and the measurement tools; `gen_tables.py` needs the pinned environment of
`tools/requirements.txt`.

The [stability study](#stability-study) (29 legal and 10 hot signals from 88.2 and
352.8 kHz, 60 s each, with the error left beyond an ideal hard limiter) runs through a build
of the command-line tool with a measurement-only patch that writes the modulator input to a
file; [tools/stability](../tools/stability/README.md) explains it. For the defaults:

```sh
git apply tools/stability/dump.patch
cargo build --release --target-dir target-dump -p dsd-upsample-cli
git apply -R tools/stability/dump.patch
STAB_CANDS=64:6:0.51,128:6:0.51,256:6:0.51 python tools/stability/stab.py
python tools/stability/summ.py target/stability
```

Its rows of the earlier tables came from builds that had them; this release cannot select
them. The [acceptance gate](#acceptance-gate) has its own commands above.

## See also

- [DSD measurements](measurements-dsd.md): the full matrix against SoX-DSD
- [Design](design.md): the processing chain
- [Options](options.md): `--order`, `--limit`
- [Provenance](../PROVENANCE.md): where each design method comes from

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
