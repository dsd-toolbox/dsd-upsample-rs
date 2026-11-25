#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate crates/dsd-upsample/src/tables.rs: every filter and modulator coefficient.

Run with the pinned tool environment (tools/requirements.txt, Python 3.9):

    python tools/gen_tables.py            # rewrite tables.rs and the test vector
    python tools/gen_tables.py --check    # fail if the committed files differ

Coefficients are stored as IEEE-754 f64 bit patterns (u64), so the library never
computes a coefficient at run time and every platform uses identical numbers.

Design methods (see PROVENANCE.md):
- FIR filters: Kaiser-window method (J. F. Kaiser, 1974; Oppenheim & Schafer,
  "Discrete-Time Signal Processing", window design and the Kaiser length/beta formulas).
- Half-band interpolators: windowed ideal half-band (every second tap is zero).
- Modulators: NTF synthesis, CRFB realisation and state scaling with python-deltasigma
  (BSD-2-Clause), a port of R. Schreier's Delta-Sigma Toolbox; Schreier & Temes,
  "Understanding Delta-Sigma Data Converters" (2005), chapters 4 and 8.
"""
import argparse
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modulator"))
from _dscompat import ds  # noqa: E402
import design as audio  # noqa: E402  (tools/modulator/design.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_RS = os.path.join(ROOT, "crates", "dsd-upsample", "src", "tables.rs")
OUT_VEC = os.path.join(ROOT, "crates", "dsd-upsample", "tests", "data", "crfb_ref.rs")
OUT_VEC_AUDIO = os.path.join(ROOT, "crates", "dsd-upsample", "tests", "data", "crfb_audio_ref.rs")
STATE_SCALE = os.path.join(ROOT, "tools", "modulator", "state_scale.json")

BASE = 44100
PCM_RATE = 8 * BASE  # 352.8 kHz intermediate rate
ATTEN_DB = 140.0

# Decimator (DSD -> 352.8 kHz): flat passband to 30 kHz, >= 140 dB from 70 kHz.
DEC_PASS = 30000.0
DEC_STOP = 70000.0
# Interpolators from 705.6 kHz up: flat to 80 kHz.
INTERP_PASS = 80000.0

# Modulator signal band per output rate (Hz): the NTF zeros are optimised over 0..band.
MOD_BAND = {64: 22050.0, 128: 50000.0, 256: 80000.0}
MOD_ORDERS = (5, 6, 7, 8)
H_INF = 1.5


def kaiser_beta(a):
    if a > 50:
        return 0.1102 * (a - 8.7)
    if a >= 21:
        return 0.5842 * (a - 21) ** 0.4 + 0.07886 * (a - 21)
    return 0.0


def kaiser_min_len(a, dw):
    return int(np.ceil((a - 8.0) / (2.285 * dw))) + 1


def bits(x):
    return struct.unpack("<Q", struct.pack("<d", float(x)))[0]


def windowed_lowpass(n_taps, fc_norm, beta):
    """Odd-length linear-phase lowpass; fc_norm = cutoff / sample rate."""
    c = (n_taps - 1) // 2
    n = np.arange(n_taps) - c
    h = 2.0 * fc_norm * np.sinc(2.0 * fc_norm * n)
    return h * np.kaiser(n_taps, beta)


def polyphase2(h):
    """Split a x2 interpolation filter (gain 2) into two phases, trim zeros, normalise
    each phase to unity DC gain. Returns [(offset, taps), (offset, taps)]."""
    phases = []
    for p in (0, 1):
        t = np.array(h[p::2], dtype=np.float64)
        t[np.abs(t) < 1e-300] = 0.0
        nz = np.nonzero(t)[0]
        first, last = int(nz[0]), int(nz[-1])
        t = t[first:last + 1]
        t = t / t.sum()
        phases.append((first, t))
    return phases


def design_decimator(k):
    fs = 64 * BASE * k
    ratio = fs // PCM_RATE
    dw = 2 * np.pi * (DEC_STOP - DEC_PASS) / fs
    nmin = kaiser_min_len(ATTEN_DB, dw)
    # centre index a multiple of 8 so the delay stays an integer at every output rate
    c = int(np.ceil((nmin - 1) / 2 / 8.0)) * 8
    n = 2 * c + 1
    h = windowed_lowpass(n, (DEC_PASS + DEC_STOP) / 2 / fs, kaiser_beta(ATTEN_DB))
    h = h / h.sum()
    padded = int(np.ceil(n / 8.0)) * 8
    h = np.concatenate([h, np.zeros(padded - n)])
    return dict(name=f"DECIM_DSD{64 * k}", in_rate=fs, ratio=ratio, center=c, taps=h)


def design_halfband(r_out):
    r_in = r_out // 2
    fp = r_out / 8.0 if r_out <= PCM_RATE else INTERP_PASS
    dw = 2 * np.pi * (r_in - 2 * fp) / r_out
    nmin = kaiser_min_len(ATTEN_DB, dw)
    kk = max(1, int(np.ceil((nmin + 1) / 4.0)))
    n = 4 * kk - 1
    c = (n - 1) // 2
    off = np.arange(n) - c
    h = np.sinc(off / 2.0) * np.kaiser(n, kaiser_beta(ATTEN_DB))
    h[(off % 2 == 0) & (off != 0)] = 0.0
    h[c] = 1.0
    return dict(name=f"HB_{r_out}", out_rate=r_out, delay=c, phases=polyphase2(h))


def design_steep(fs_in):
    r_out = 2 * fs_in
    fp = fs_in * 20000.0 / 44100.0
    fstop = fs_in / 2.0
    dw = 2 * np.pi * (fstop - fp) / r_out
    nmin = kaiser_min_len(ATTEN_DB, dw)
    c = (nmin + 1) // 2
    n = 2 * c + 1
    h = 2.0 * windowed_lowpass(n, (fp + fstop) / 2 / r_out, kaiser_beta(ATTEN_DB))
    return dict(name=f"STEEP_{fs_in}", out_rate=r_out, delay=c, phases=polyphase2(h))


def crfb_step(x, u, a, g, b, c, n):
    """One CRFB step with the exact operation order of modulator.rs."""
    y = c[n - 1] * x[n - 1] + b[n] * u
    v = 1.0 if y >= 0.0 else -1.0
    odd = n % 2
    pairs = [(p, p + 1) for p in range(odd, n, 2)]
    for k in range(len(pairs) - 1, -1, -1):
        p, q = pairs[k]
        if p > 0:
            t = (x[p] + c[p - 1] * x[p - 1]) + (b[p] * u - g[k] * x[q])
        else:
            t = x[p] + (b[p] * u - g[k] * x[q])
        t = t - a[p] * v
        s = (x[q] + (b[q] * u - a[q] * v)) + c[p] * t
        x[p] = t
        x[q] = s
    if odd:
        x[0] = (x[0] + b[0] * u) - a[0] * v
    return v


def design_modulator(rate_mult, order):
    fs = 64 * BASE * (rate_mult // 64)
    band = MOD_BAND[rate_mult]
    osr = fs / (2.0 * band)
    ntf = ds.synthesizeNTF(order, osr, 1, H_INF)
    a, g, b, c = ds.realizeNTF(ntf, "CRFB")
    abcd = ds.stuffABCD(a, g, b, c, "CRFB")
    abcds, umax, _ = ds.scaleABCD(abcd, 2, 0, 1, None, None, 100000, 10)
    a, g, b, c = ds.mapABCD(abcds, "CRFB")
    a, g, b, c = (np.real(np.asarray(z, dtype=np.complex128)).reshape(-1) for z in (a, g, b, c))
    # cross-check: our structured recurrence against the toolbox simulator
    nsim = 20000
    t = np.arange(nsim)
    u = 0.5 * umax * np.sin(2 * np.pi * t * (band / 7.0) / fs)
    vref = ds.simulateDSM(u, abcds)[0]
    x = [0.0] * order
    vours = np.array([crfb_step(x, float(ui), a, g, b, c, order) for ui in u])
    agree = int(np.argmax(vours != vref)) if np.any(vours != vref) else nsim
    return dict(rate=rate_mult, order=order, osr=osr, band=band, umax=float(umax),
                a=a, g=g, b=b, c=c, agree=agree)


def ref_bits(m, n_samples=8192):
    n = len(m["a"])
    x = [0.0] * n
    return [crfb_step(x, ((i % 97) - 48) / 128.0, m["a"], m["g"], m["b"], m["c"], n)
            for i in range(n_samples)]


def design_audio_modulator(rate_mult, order, scale):
    """Audio-band table: tools/modulator/design.py, states scaled by the powers of two
    measured with tools/modulator/scale.py."""
    d = audio.audio_design(rate_mult, order)
    sc = scale[f"{rate_mult}:{order}"]
    if sc["hinf"] != audio.AUDIO_HINF[(rate_mult, order)]:
        raise SystemExit(f"state_scale.json is stale for DSD{rate_mult} order {order}: rerun scale.py")
    s = audio.scaled(d, sc["exp"])
    m = dict(rate=rate_mult, order=order, hinf=d["hinf"], band=audio.AUDIO_BAND,
             umax=0.0, pole_err=d["pole_err"], **s)
    # powers of two: the scaled recurrence gives the same bits as the unscaled one
    if ref_bits(m) != ref_bits(dict(a=d["a"], g=d["g"], b=d["b"], c=d["c"])):
        raise SystemExit("scaled and unscaled recurrences differ")
    return m


def fmt_u64s(vals, indent="    "):
    items = [f"0x{bits(v):016x}" for v in vals]
    lines = []
    for i in range(0, len(items), 4):
        lines.append(indent + ", ".join(items[i:i + 4]) + ",")
    return "\n".join(lines)


def emit(decims, hbs, steeps, mods, amods):
    o = []
    o.append("// SPDX-License-Identifier: MIT OR Apache-2.0")
    o.append("// @generated by tools/gen_tables.py. Do not edit by hand; rerun the script.")
    o.append("//! Filter and modulator coefficients as IEEE-754 f64 bit patterns.")
    o.append("//!")
    o.append("//! Design methods and sources are listed in PROVENANCE.md.")
    o.append("")
    o.append("#![allow(clippy::unreadable_literal)]")
    o.append("")
    o.append("use crate::filters::{DecimTable, InterpTable, ModTable, PhaseTable};")
    o.append("")
    for d in decims:
        o.append(f"/// DSD{d['in_rate'] // BASE} to 352.8 kHz, {len(d['taps'])} taps "
                 f"(centre {d['center']}), pass {DEC_PASS:.0f} Hz, stop {DEC_STOP:.0f} Hz.")
        o.append(f"pub(crate) static {d['name']}: DecimTable = DecimTable {{")
        o.append(f"    in_rate: {d['in_rate']},")
        o.append(f"    ratio: {d['ratio']},")
        o.append(f"    center: {d['center']},")
        o.append("    taps: &[")
        o.append(fmt_u64s(d["taps"], "        "))
        o.append("    ],")
        o.append("};")
        o.append("")
    for f in hbs + steeps:
        kind = "half-band" if f["name"].startswith("HB") else "steep"
        o.append(f"/// x2 {kind} interpolator to {f['out_rate']} Hz, delay {f['delay']} output samples.")
        o.append(f"pub(crate) static {f['name']}: InterpTable = InterpTable {{")
        o.append(f"    out_rate: {f['out_rate']},")
        o.append(f"    delay: {f['delay']},")
        o.append("    phases: [")
        for off, taps in f["phases"]:
            o.append("        PhaseTable {")
            o.append(f"            offset: {off},")
            o.append("            taps: &[")
            o.append(fmt_u64s(taps, "                "))
            o.append("            ],")
            o.append("        },")
        o.append("    ],")
        o.append("};")
        o.append("")
    for m in mods:
        nm = f"MOD_DSD{m['rate']}_O{m['order']}"
        o.append(f"/// CRFB order {m['order']} for DSD{m['rate']}: OSR {m['osr']:.3f} "
                 f"(band {m['band']:.0f} Hz), H_inf {H_INF}, max stable input {m['umax']:.4f}.")
        o.append(f"pub(crate) static {nm}: ModTable = ModTable {{")
        o.append(f"    order: {m['order']},")
        o.append(f"    umax: 0x{bits(m['umax']):016x},")
        for key in ("a", "g", "b", "c"):
            o.append(f"    {key}: &[")
            o.append(fmt_u64s(m[key], "        "))
            o.append("    ],")
        o.append("};")
        o.append("")
    for m in amods:
        nm = f"MOD_DSD{m['rate']}_A{m['order']}"
        o.append(f"/// CRFB order {m['order']} for DSD{m['rate']}, audio band: zeros over "
                 f"0 to {m['band']:.0f} Hz, H_inf {m['hinf']}.")
        o.append(f"pub(crate) static {nm}: ModTable = ModTable {{")
        o.append(f"    order: {m['order']},")
        o.append(f"    umax: 0x{bits(0.0):016x},")
        for key in ("a", "g", "b", "c"):
            o.append(f"    {key}: &[")
            o.append(fmt_u64s(m[key], "        "))
            o.append("    ],")
        o.append("};")
        o.append("")
    o.append("/// Modulator table for a DSD rate multiple (64, 128, 256), an order (5..=8) and a")
    o.append("/// noise-shaping band (`wide`: the zeros spread to 22, 50 or 80 kHz).")
    o.append("pub(crate) fn modulator(rate_mult: u32, order: usize, wide: bool) -> Option<&'static ModTable> {")
    o.append("    match (rate_mult, order, wide) {")
    for m in mods:
        o.append(f"        ({m['rate']}, {m['order']}, true) => Some(&MOD_DSD{m['rate']}_O{m['order']}),")
    for m in amods:
        o.append(f"        ({m['rate']}, {m['order']}, false) => Some(&MOD_DSD{m['rate']}_A{m['order']}),")
    o.append("        _ => None,")
    o.append("    }")
    o.append("}")
    o.append("")
    return "\n".join(o)


def emit_vector(m, prefix="CRFB_REF"):
    """Reference output of the CRFB recurrence for a fixed, exactly representable input."""
    n = len(m["a"])
    out = ref_bits(m)
    by = []
    for i in range(0, len(out), 8):
        v = 0
        for bit in out[i:i + 8]:
            v = (v << 1) | (1 if bit > 0 else 0)
        by.append(v)
    o = ["// SPDX-License-Identifier: MIT OR Apache-2.0",
         "// @generated by tools/gen_tables.py. Do not edit by hand.",
         f"// CRFB DSD{m['rate']} order {n}; input u[i] = ((i % 97) - 48) / 128, 8192 samples.",
         "// Bits MSB-first, 1 = +1.",
         "pub const %s_RATE: u32 = %d;" % (prefix, m["rate"]),
         "pub const %s_ORDER: usize = %d;" % (prefix, n),
         "pub const %s_BITS: [u8; %d] = [" % (prefix, len(by))]
    for i in range(0, len(by), 16):
        o.append("    " + ", ".join(f"0x{b:02x}" for b in by[i:i + 16]) + ",")
    o.append("];")
    o.append("")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    decims = [design_decimator(k) for k in (1, 2, 4)]
    hbs = [design_halfband(r) for r in (176400, 352800, 705600, 1411200, 2822400, 5644800, 11289600)]
    steeps = [design_steep(f) for f in (44100, 88200, 176400)]
    mods = [design_modulator(r, n) for r in (64, 128, 256) for n in MOD_ORDERS]
    import json
    with open(STATE_SCALE) as fh:
        scale = json.load(fh)
    amods = [design_audio_modulator(r, n, scale) for r in (64, 128, 256) for n in MOD_ORDERS]
    for d in decims:
        print(f"{d['name']}: {len(d['taps'])} taps, centre {d['center']}", file=sys.stderr)
    for f in hbs + steeps:
        print(f"{f['name']}: delay {f['delay']}, phases "
              f"{[len(t) for _, t in f['phases']]}", file=sys.stderr)
    for m in mods:
        print(f"MOD DSD{m['rate']} O{m['order']}: osr {m['osr']:.2f} umax {m['umax']:.4f} "
              f"agree-with-simulateDSM {m['agree']}/20000", file=sys.stderr)
    for m in amods:
        print(f"MOD DSD{m['rate']} A{m['order']}: H_inf {m['hinf']} pole error {m['pole_err']:.1e}",
              file=sys.stderr)
    rs = emit(decims, hbs, steeps, mods, amods)
    vec = emit_vector(next(m for m in mods if m["rate"] == 256 and m["order"] == 7))
    avec = emit_vector(next(m for m in amods if m["rate"] == 128 and m["order"] == 6),
                       "CRFB_AUDIO_REF")
    if args.check:
        ok = (open(OUT_RS).read() == rs and open(OUT_VEC).read() == vec
              and open(OUT_VEC_AUDIO).read() == avec)
        print("tables up to date" if ok else "tables differ", file=sys.stderr)
        sys.exit(0 if ok else 1)
    os.makedirs(os.path.dirname(OUT_VEC), exist_ok=True)
    with open(OUT_RS, "w") as fh:
        fh.write(rs)
    with open(OUT_VEC, "w") as fh:
        fh.write(vec)
    with open(OUT_VEC_AUDIO, "w") as fh:
        fh.write(avec)


if __name__ == "__main__":
    main()
