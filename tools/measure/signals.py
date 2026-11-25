# SPDX-License-Identifier: MIT OR Apache-2.0
"""Deterministic test signals for measuring a DSD modulator (or any converter).

Levels are peak levels in dBFS, where 0 dBFS is 100 % DSD modulation; 0 dB SACD (50 %)
is -6.02 dBFS and the 71.43 % peak level (+3.1 dB SACD) is -2.92 dBFS.

Every tone is placed on a bin centre of the analysis FFT (coherent): a multiple of
``ANALYSIS_FS / 2**20`` (0.3365 Hz at 352.8 kHz), which is also a bin of 2**18 points when
the multiple is divisible by 4. Each file starts with ``SILENCE`` s of digital silence and
a ``RAMP`` s linear fade-in, then the steady part.

    python tools/measure/signals.py --list
    python tools/measure/signals.py sine out.wav --fs 88200 --fmt i32 --freq 1000 --level -6.02

Signals (``ID``):
  sine       one tone, --freq, --level
  silence    digital zero
  jtest      J-Test: fs/4 tone at --level plus a square wave at fs/192 of 1 LSB at
             --jbits (24): only meaningful at its own --fs (44.1 or 48 kHz)
  multitone  32 tones, 1/10 decade, 17.6 Hz to 21.4 kHz, crest factor 13.3 dB
             (multitone32.json); --level is the composite peak
  smpte      60 Hz + 7 kHz, 4:1 in amplitude; --level is the composite peak
  ccif       --f1 and --f2 (default 19 and 20 kHz), equal amplitude; --level is the peak
  hold       stability test: --freq at --level for --steady s, then 10 s of silence
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsdio  # noqa: E402

ANALYSIS_FS = 352800
SILENCE = 3.0
RAMP = 2.0
SACD0 = -20 * np.log10(2.0)  # 0 dB SACD in dBFS (-6.0206)
PEAK = SACD0 + 20 * np.log10(0.7143 / 0.5)  # +3.1 dB SACD, -2.92 dBFS
HERE = os.path.dirname(os.path.abspath(__file__))
MULTITONE = os.path.join(HERE, "multitone32.json")


def coherent(f, n=1 << 18, fs=ANALYSIS_FS):
    """Nearest bin-centre frequency of an n-point FFT at fs."""
    df = fs / n
    return round(f / df) * df


def amp(level_dbfs):
    return 10 ** (level_dbfs / 20)


def frame(steady, fs, seconds):
    """Prepend silence and a linear ramp to steady(t) (t in seconds from the ramp start)."""
    n0 = int(round(SILENCE * fs))
    nr = int(round(RAMP * fs))
    n = nr + int(round(seconds * fs))
    t = np.arange(n) / fs
    x = steady(t)
    x[:nr] *= np.arange(nr) / nr
    return np.concatenate([np.zeros(n0), x])


def tones(freqs, amps, phases=None):
    phases = np.zeros(len(freqs)) if phases is None else phases

    def f(t):
        y = np.zeros_like(t)
        for fr, a, ph in zip(freqs, amps, phases):
            y += a * np.sin(2 * np.pi * fr * t + ph)
        return y
    return f


def multitone_table():
    with open(MULTITONE) as f:
        return json.load(f)


def design_multitone(target_crest=13.3, seeds=1000):
    """Search seeded random phases for the crest factor closest to target (dB).

    Tones: 32, log spaced 17.6 Hz to 21.4 kHz, snapped to distinct 2**20-point bins at
    352.8 kHz (bin indices divisible by 4, so they are also 2**18-point bins)."""
    n = 1 << 20
    f = np.geomspace(17.6, 21400.0, 32)
    k = np.round(f / (ANALYSIS_FS / n) / 4).astype(int) * 4
    assert len(set(k)) == 32
    best = None
    for seed in range(seeds):
        ph = np.random.default_rng(seed).uniform(0, 2 * np.pi, 32)
        X = np.zeros(n // 2 + 1, complex)
        X[k] = np.exp(1j * (ph - np.pi / 2)) * n / 2
        y = np.fft.irfft(X, n)
        crest = 20 * np.log10(np.max(np.abs(y)) / np.sqrt(np.mean(y ** 2)))
        if best is None or abs(crest - target_crest) < abs(best[1] - target_crest):
            best = (seed, crest, ph, np.max(np.abs(y)))
    seed, crest, ph, peak = best
    return {"description": "32-tone multitone, 1/10 decade, 17.6 Hz to 21.4 kHz; tone i is "
                           "amplitude 'unit_peak_amplitude' * sin(2 pi f_i t + phase_i) with "
                           "unit amplitude giving a composite peak of 1.0",
            "analysis_fs": ANALYSIS_FS, "fft_points": n, "seed": seed,
            "crest_factor_db": round(float(crest), 3),
            "bins": [int(v) for v in k], "freqs_hz": [float(v) for v in k * ANALYSIS_FS / n],
            "phases_rad": [float(v) for v in ph],
            "unit_peak_amplitude": float(1.0 / peak)}


def make(sig, fs, level=None, freq=1000.0, steady=15.0, f1=19000.0, f2=20000.0, jbits=24):
    """Return the float64 samples of a signal (see the module docstring)."""
    if sig == "sine":
        return frame(tones([coherent(freq)], [amp(level)]), fs, steady)
    if sig == "silence":
        return np.zeros(int(round((SILENCE + RAMP + steady) * fs)))
    if sig == "hold":
        x = frame(tones([coherent(freq)], [amp(level)]), fs, steady)
        return np.concatenate([x, np.zeros(int(10 * fs))])
    if sig == "multitone":
        t = multitone_table()
        a = amp(level) * t["unit_peak_amplitude"]
        return frame(tones(t["freqs_hz"], [a] * 32, t["phases_rad"]), fs, steady)
    if sig == "smpte":
        a = amp(level) / 1.25
        return frame(tones([coherent(60.0), coherent(7000.0)], [a, a / 4]), fs, steady)
    if sig == "ccif":
        a = amp(level) / 2
        return frame(tones([coherent(f1), coherent(f2)], [a, a]), fs, steady)
    if sig == "jtest":
        lsb = 2.0 ** -(jbits - 1)
        n0, nr = int(round(SILENCE * fs)), int(round(RAMP * fs))
        n = nr + int(round(steady * fs))
        i = np.arange(n)
        # fs/4 tone sampled at 45 degrees: samples +-A/sqrt(2), exact on the LSB grid
        a = amp(level) / np.sqrt(2)
        tone = np.round(a / lsb * np.array([1, 1, -1, -1])[i % 4]) * lsb
        tone[:nr] = np.round(tone[:nr] * (np.arange(nr) / nr) / lsb) * lsb
        square = np.where((i % 192) < 96, 0.0, lsb)
        return np.concatenate([np.zeros(n0), tone + square])
    raise ValueError(f"unknown signal {sig}")


def tpdf(n, bits, seed):
    """TPDF dither of +-1 LSB at the given bit depth, fixed seed."""
    lsb = 2.0 ** -(bits - 1)
    r = np.random.default_rng(seed)
    return (r.random(n) - r.random(n)) * lsb


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("signal", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--fs", type=int, default=88200)
    ap.add_argument("--fmt", default="i32", choices=["i16", "i24", "i32", "f32", "f64"])
    ap.add_argument("--level", type=float, default=SACD0, help="peak dBFS (100 %% = 0)")
    ap.add_argument("--freq", type=float, default=1000.0)
    ap.add_argument("--f1", type=float, default=19000.0)
    ap.add_argument("--f2", type=float, default=20000.0)
    ap.add_argument("--steady", type=float, default=15.0, help="seconds after the ramp")
    ap.add_argument("--jbits", type=int, default=24)
    ap.add_argument("--dither-seed", type=int, help="add TPDF dither at --fmt bit depth")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--design-multitone", action="store_true",
                    help="regenerate multitone32.json (seeded search, deterministic)")
    a = ap.parse_args()
    if a.list:
        print(__doc__)
        return
    if a.design_multitone:
        t = design_multitone()
        with open(MULTITONE, "w") as f:
            json.dump(t, f, indent=1)
        print(f"seed {t['seed']}, crest {t['crest_factor_db']} dB")
        return
    x = make(a.signal, a.fs, a.level, a.freq, a.steady, a.f1, a.f2, a.jbits)
    if a.dither_seed is not None and a.fmt.startswith("i"):
        x = x + tpdf(len(x), int(a.fmt[1:]), a.dither_seed)
    dsdio.write_wav(a.out, x, a.fs, a.fmt)


if __name__ == "__main__":
    main()
