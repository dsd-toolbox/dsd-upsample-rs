#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate the 48 kHz-family resampler table: crates/dsd-upsample/src/resample_table.rs
and its reference vector crates/dsd-upsample/tests/data/resample_ref.rs.

Run with the pinned tool environment (tools/requirements.txt, Python 3.9):

    python tools/gen_resampler.py            # rewrite both files, print the design figures
    python tools/gen_resampler.py --check    # fail if the committed files differ
    python tools/gen_resampler.py --report   # also simulate tones through the resampler

The resampler changes the rate by 147/160 (48 -> 44.1, 96 -> 88.2, 192 -> 176.4,
384 -> 352.8 kHz; 44100/48000 = 147/160). One prototype lowpass serves all four rates,
because its band edges scale with the rate: it runs at 147 x the input rate (7.056 MHz for
48 kHz input), passes 0 to 20/44.1 of the output rate (20 kHz at 44.1 kHz output,
40 kHz at 88.2 kHz, ...) and stops from the output rate's Nyquist frequency (22.05 kHz at
44.1 kHz output), the same band edges as the steep x2 stage that follows it.

Design: Kaiser window method (J. F. Kaiser 1974; Oppenheim & Schafer), beta and length
from Kaiser's formulas for ATTEN_DB, the centre rounded up to a multiple of 160 so that
the delay is a whole number of output samples. Gain 147 (the upsampling factor), so a
DC input passes at unity. The table stores the first half (symmetric, linear phase) as
IEEE-754 f64 bit patterns; the library builds the 147 polyphase branches from it by copying,
without arithmetic.
"""
import argparse
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_RS = os.path.join(ROOT, "crates", "dsd-upsample", "src", "resample_table.rs")
OUT_VEC = os.path.join(ROOT, "crates", "dsd-upsample", "tests", "data", "resample_ref.rs")

UP = 147
DOWN = 160
# Band edges as fractions of the OUTPUT rate (44.1 kHz output: 20 kHz and 22.05 kHz).
PASS_FRAC = 20000.0 / 44100.0  # of the output rate (0.907 x its Nyquist)
STOP_FRAC = 0.5  # of the output rate: its Nyquist frequency
# Where the stopband is also reported: the input's Nyquist (24 kHz at 48 kHz input).
FAR_FRAC = 24000.0 / 44100.0
ATTEN_DB = 250.0
# Acceptance limits checked on every run (measured on a dense FFT of the table).
MAX_STOP_DB = -240.0
MAX_RIPPLE_DB = 1e-10
FFT_SIZE = 1 << 24

# Reference vector: exactly representable input, outputs from the Rust summation order.
REF_IN = 4096
REF_OUT = 2048


def kaiser_beta(a):
    if a > 50:
        return 0.1102 * (a - 8.7)
    if a >= 21:
        return 0.5842 * (a - 21) ** 0.4 + 0.07886 * (a - 21)
    return 0.0


def bits(x):
    return struct.unpack("<Q", struct.pack("<d", float(x)))[0]


def design():
    """The prototype at UP x the input rate; frequencies normalised to that rate."""
    # output rate = UP/DOWN x input rate, prototype rate = UP x input rate
    fp = PASS_FRAC / DOWN
    fs = STOP_FRAC / DOWN
    dw = 2 * np.pi * (fs - fp)
    nmin = int(np.ceil((ATTEN_DB - 8.0) / (2.285 * dw))) + 1
    c = int(np.ceil((nmin - 1) / 2 / DOWN)) * DOWN
    n = 2 * c + 1
    k = np.arange(n) - c
    fc = (fp + fs) / 2
    beta = kaiser_beta(ATTEN_DB)
    h = 2 * fc * np.sinc(2 * fc * k) * np.kaiser(n, beta)
    h = h / h.sum() * UP
    # exact symmetry: the stored half defines the table
    half = h[: c + 1].copy()
    h = np.concatenate([half, half[-2::-1]])
    return dict(h=h, half=half, c=c, n=n, beta=beta, fp=fp, fs=fs)


def response(d):
    """Passband deviation (dB, max and min) and stopband peaks (dB), gain UP removed: from
    the output's Nyquist frequency (the edge, where the main lobe's skirt peaks; evaluated
    on a 1 Hz grid at 44.1 kHz output up to the input's Nyquist) and from the input's
    Nyquist (FFT grid)."""
    H = np.abs(np.fft.rfft(d["h"], FFT_SIZE)) / UP
    f = np.arange(len(H)) / FFT_SIZE
    pb = H[f <= d["fp"]]
    far = FAR_FRAC / DOWN
    sb = H[f >= far]
    # direct evaluation near the edge: H(f) = h[c] + 2 sum_k h[c+k] cos(2 pi f k)
    c, h = d["c"], d["h"]
    k = np.arange(1, c + 1)
    hk = h[c + 1:]
    fe = np.linspace(d["fs"], far, 1951)
    edge = np.array([abs(h[c] + 2 * np.dot(hk, np.cos(2 * np.pi * v * k))) for v in fe]) / UP
    return dict(pass_max=20 * np.log10(pb.max()), pass_min=20 * np.log10(pb.min()),
                stop=20 * np.log10(max(edge.max(), sb.max())), stop_far=20 * np.log10(sb.max()))


def phases(d):
    """Polyphase branches padded to equal length: phase p, tap j is h[p + j*UP]."""
    h = d["h"]
    k = -(-len(h) // UP)
    hp = np.concatenate([h, np.zeros(k * UP - len(h))])
    return [hp[p::UP].copy() for p in range(UP)], k


def resample_ref(x, ph, k, down):
    """The library's algorithm with its exact summation order (plain Python floats):
    output m: n = floor(m*down/UP), p = (m*down) mod UP, y = sum_j ph[p][j] * x[n - j]
    in ascending j, with x[i] = 0 for i < 0."""
    out = []
    m = 0
    while True:
        t = m * down
        n, p = divmod(t, UP)
        if n >= len(x):
            break
        taps = ph[p]
        s = 0.0
        for j in range(k):
            i = n - j
            if i < 0:
                break
            s += float(taps[j]) * x[i]
        out.append(s)
        m += 1
    return out


def ref_input():
    return [float(((i * 37) % 101) - 50) / 64.0 for i in range(REF_IN)]


def check_ref(x, y, d, down):
    """The ordered sum against an independent polyphase implementation (SciPy upfirdn)."""
    from scipy.signal import upfirdn
    z = upfirdn(d["h"], np.asarray(x), UP, down)
    err = np.max(np.abs(np.asarray(y) - z[: len(y)]))
    if err > 1e-12:
        raise SystemExit(f"reference loop disagrees with upfirdn: {err}")
    return err


def tone_report(d, down):
    """In-band error of a full-scale tone after resampling, against the exact tone, with
    the delay removed: 48 kHz input, output 44.1 kHz x UP*... (down=160) or 88.2 (80)."""
    from scipy.signal import upfirdn
    fin = 48000.0
    fout = fin * UP / down
    nin = 48000 * 2
    print(f"tones, 48 kHz in, {fout / 1000:g} kHz out (error 0-20 kHz re the tone, after "
          "the delay; Blackman window, 1 s):", file=sys.stderr)
    for f in (1000.0, 10000.0, 19000.0, 19990.0):
        # exact phase: (f * n) mod rate in integers, so the argument stays below 2 pi
        x = np.sin(2 * np.pi * ((int(f) * np.arange(nin)) % int(fin)) / fin)
        y = upfirdn(d["h"], x, UP, down)
        dly = d["c"] // down
        y = y[dly:]
        m0 = int(0.5 * fout)
        nn = int(fout)
        ph = (int(f) * np.arange(m0, m0 + nn)) % int(fout)
        e = y[m0:m0 + nn] - np.sin(2 * np.pi * ph / fout)
        w = np.blackman(nn)
        E = np.abs(np.fft.rfft(e * w)) ** 2
        fr = np.fft.rfftfreq(nn, 1 / fout)
        inb = E[(fr >= 20) & (fr <= 20000)].sum() / (w ** 2).sum() * 2 / nn
        print(f"  {f:7.0f} Hz: in-band error {10 * np.log10(inb / 0.5 + 1e-300):.1f} dB re the tone, "
              f"peak |e| {20 * np.log10(np.abs(e).max() + 1e-300):.1f} dB FS",
              file=sys.stderr)


def fmt_u64s(vals, indent):
    items = [f"0x{bits(v):016x}" for v in vals]
    return "\n".join(indent + ", ".join(items[i:i + 4]) + ","
                     for i in range(0, len(items), 4))


def emit_table(d, r):
    o = ["// SPDX-License-Identifier: MIT OR Apache-2.0",
         "// @generated by tools/gen_resampler.py. Do not edit by hand; rerun the script.",
         "//! The 48 kHz-family resampler's prototype lowpass (IEEE-754 f64 bit patterns).",
         "",
         "#![allow(clippy::unreadable_literal)]",
         "",
         "use crate::filters::ResampleTable;",
         "",
         f"/// x{UP}/{DOWN} prototype: Kaiser, beta {d['beta']:.4f}, {d['n']} taps (centre "
         f"{d['c']}), pass to {PASS_FRAC:.6f} x the output rate,",
         f"/// stop from its Nyquist; ripple {r['pass_min']:+.1e}/{r['pass_max']:+.1e} dB, "
         f"stopband {r['stop']:.1f} dB from the output Nyquist, {r['stop_far']:.1f} dB from the input's.",
         "/// First half only (symmetric).",
         "pub(crate) static RESAMPLE_147: ResampleTable = ResampleTable {",
         f"    up: {UP},",
         f"    center: {d['c']},",
         "    half: &[",
         fmt_u64s(d["half"], "        "),
         "    ],",
         "};",
         ""]
    return "\n".join(o)


def emit_vector(x, y):
    o = ["// SPDX-License-Identifier: MIT OR Apache-2.0",
         "// @generated by tools/gen_resampler.py. Do not edit by hand.",
         f"// x{UP}/{DOWN} resampler; input x[i] = (((i * 37) % 101) - 50) / 64, {REF_IN} samples,",
         "// zero history; outputs as f64 bit patterns, from the library's summation order.",
         f"pub const RESAMPLE_REF_IN: usize = {REF_IN};",
         f"pub const RESAMPLE_REF_OUT: [u64; {len(y)}] = ["]
    o.append(fmt_u64s(y, "    "))
    o.append("];")
    o.append("")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed files differ")
    ap.add_argument("--report", action="store_true", help="also simulate tones")
    args = ap.parse_args()
    d = design()
    r = response(d)
    ph, k = phases(d)
    print(f"x{UP}/{DOWN}: Kaiser beta {d['beta']:.4f}, {d['n']} taps, centre {d['c']} "
          f"(delay {d['c'] // DOWN} output samples), {k} taps per phase", file=sys.stderr)
    print(f"passband 0-{PASS_FRAC:.6f} x output rate: {r['pass_min']:+.3e} to "
          f"{r['pass_max']:+.3e} dB; stopband from the output Nyquist: {r['stop']:.1f} dB, "
          f"from {FAR_FRAC:.6f} x output rate: {r['stop_far']:.1f} dB",
          file=sys.stderr)
    if r["stop"] > MAX_STOP_DB or max(abs(r["pass_min"]), abs(r["pass_max"])) > MAX_RIPPLE_DB:
        raise SystemExit("design misses its acceptance limits")
    x = ref_input()
    y = resample_ref(x, ph, k, DOWN)[:REF_OUT]
    err = check_ref(x, y, d, DOWN)
    print(f"reference vector: {len(y)} outputs, max difference to upfirdn {err:.1e}",
          file=sys.stderr)
    if args.report:
        tone_report(d, DOWN)
        tone_report(d, DOWN // 2)
    rs = emit_table(d, r)
    vec = emit_vector(x, y)
    if args.check:
        ok = open(OUT_RS).read() == rs and open(OUT_VEC).read() == vec
        print("resampler table up to date" if ok else "resampler table differs", file=sys.stderr)
        sys.exit(0 if ok else 1)
    os.makedirs(os.path.dirname(OUT_VEC), exist_ok=True)
    with open(OUT_RS, "w") as fh:
        fh.write(rs)
    with open(OUT_VEC, "w") as fh:
        fh.write(vec)


if __name__ == "__main__":
    main()
