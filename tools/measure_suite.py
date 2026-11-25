#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Measurement suite for docs/measurements.md: builds the test signals, converts them with
the CLI and measures the output with measure.py. Prints the Markdown tables, each followed
by the command that produced it.

    python tools/measure_suite.py [--bin target/release/dsd-upsample] [--work DIR] [--only SECTION,...]
    python tools/measure_suite.py --doc docs/measurements.md    (rewrites its tables)

Every table is at the CLI's defaults (order and input limit, read from its --help), with,
where it matters, the other orders as labelled extra rows. Sections (signals are f64 WAV at 352.8 kHz unless stated; levels in dB SACD, WAV full
scale = 0 dB SACD; PCM sources are converted at --gain 0 so the stated level is the
modulator input):

- levels: 1 kHz at 0, -6, -20, -60, -120 dB to DSD64, DSD128 and DSD256; orders 5, 7, 8 at -6 dB
  (not order 8 at DSD128, which the library refuses);
- dsd64: DSD64 sources from `dsd-upsample gen` at 0, -6, -20, -60, -120 dB (gen's order-7
  modulator at every one of these levels; it switches to a second-order one only above
  0 dB SACD), converted at the default gain to DSD128 and DSD256; each row names the
  source's modulator and its own in-band noise;
- ccif: 19 + 20 kHz, each -6.02 dB, so the composite peaks at 0 dB SACD;
- idle: digital silence and DC at -40, -60, -80 dB, without and with --dither;
- overload: 1 kHz from 0 to +6 dB to DSD256;
- limits: the default order at DSD256 with --limit 0.6, 0.55 and the default limit;
- cutoff: a DSD64 source at -6 dB to DSD256 with each DSD64 decimator (--cutoff).
"""
import argparse
import os
import re
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure  # noqa: E402

FS = 352800
SECONDS = 3.4
N = 1 << 20
DEFAULT_ORDER = {}  # per rate, and DEFAULT_LIMIT: from the CLI's --help (set_defaults)
DEFAULT_LIMIT = None
SECTIONS = ("levels", "dsd64", "ccif", "idle", "overload", "limits", "cutoff")


def set_defaults(binary):
    global DEFAULT_LIMIT
    from measure_dsdup import cli_defaults
    d = cli_defaults(binary)
    DEFAULT_ORDER.update({r: d["order"] for r in (64, 128, 256)})
    DEFAULT_LIMIT = d["limit"]


def write_wav_f64(path, x):
    data = x.astype("<f8").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, FS, FS * 8, 8, 64)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


def tone(freqs, level_db, seconds=SECONDS, dc=0.0):
    t = np.arange(int(seconds * FS)) / FS
    a = 10 ** (level_db / 20)
    x = sum(a * np.sin(2 * np.pi * f * t) for f in freqs) + dc
    return x


def convert(binary, src, dst, *args):
    r = subprocess.run([binary, src, dst, *args], capture_output=True, text=True, check=True)
    c = [tuple(map(int, m)) for m in
         re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", r.stderr)]
    return c[0] if c else (0, 0, 0)


def analyse(path):
    bits, rate = measure.read_dsd(path, 0)
    y = measure.decimate(bits, rate)
    return y[int(0.2 * measure.PCM):]


def order_label(mult, order):
    return f"{order} (default)" if DEFAULT_ORDER[mult] == order else str(order)


def footer(section):
    print(f"\nProduced by `python tools/measure_suite.py --only {section}`.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="target/release/dsd-upsample")
    ap.add_argument("--work", default="target/measure")
    ap.add_argument("--only", help="comma-separated sections: " + ", ".join(SECTIONS))
    ap.add_argument("--doc", help="replace the <!-- suite:SECTION --> blocks of this file")
    a = ap.parse_args()
    set_defaults(a.bin)
    only = set(a.only.split(",")) if a.only else set(SECTIONS)
    os.makedirs(a.work, exist_ok=True)
    if not a.doc:
        run_sections(a, only)
        return
    import contextlib
    import io
    with open(a.doc) as f:
        doc = f.read()
    for sec in SECTIONS:
        if sec not in only or f"<!-- suite:{sec} -->" not in doc:
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_sections(a, {sec})
        body = "\n".join(l for l in buf.getvalue().strip().splitlines() if not l.startswith("## "))
        doc = re.sub(rf"<!-- suite:{sec} -->.*?<!-- /suite -->",
                     lambda m: f"<!-- suite:{sec} -->\n{body.strip()}\n<!-- /suite -->", doc, flags=re.S)
    with open(a.doc, "w") as f:
        f.write(doc)


def run_sections(a, only):
    w = lambda name: os.path.join(a.work, name)  # noqa: E731

    def sine(lv):
        src = w(f"sine{lv}.wav")
        if not os.path.exists(src):
            write_wav_f64(src, tone([1000.0], lv))
        return src

    def gen64(lv):
        src = w(f"dsd64-{lv}.dsf")
        if not os.path.exists(src):
            subprocess.run([a.bin, "gen", src, "--rate", "64", "--freq", "1000", "--level",
                            str(lv), "--seconds", str(SECONDS)], check=True, capture_output=True)
        return src

    if "levels" in only:
        print("## Level sweep, 1 kHz, f64 PCM source (modulator and interpolators)\n")
        print("| Level (dB SACD) | Output rate | Order | Level out (dB SACD) | SNR 20k (dB) | THD+N (dB) | Noise 20-20k (dB SACD) | 20-50k (dB SACD) | 50-100k (dB SACD) |")
        print("|---|---|---|---|---|---|---|---|---|")
        cases = []
        for mult in (64, 128, 256):
            for lv in (0, -6, -20, -60, -120):
                cases.append((lv, mult, DEFAULT_ORDER[mult]))
            # every other order the rate accepts (order 8 is refused at DSD128)
            cases += [(-6, mult, o) for o in (5, 6, 7, 8)
                      if o != DEFAULT_ORDER[mult] and (mult, o) != (128, 8)]
        for lv, mult, order in cases:
            out = w(f"sine{lv}-{mult}-{order}.dsf")
            convert(a.bin, sine(lv), out, "--rate", str(mult), "--gain", "0", "--order", str(order))
            r = measure.bands(analyse(out), 1000.0, N)
            print(f"| {lv} | DSD{mult} | {order_label(mult, order)} | {r['level']:.1f} | {r['snr']:.1f} | "
                  f"{r['thdn']:.1f} | {r['n20k']:.1f} | {r['n50k']:.1f} | {r['n100k']:.1f} |")
        footer("levels")

    def gen_name(lv):
        # dsd-upsample gen: the order-7 modulator up to 0 dB SACD, a second-order one above
        return "gen, order 7" if lv <= 0 else "gen, 2nd order"

    floors = {}

    def src_floor(lv):
        if lv not in floors:
            floors[lv] = measure.bands(analyse(gen64(lv)), 1000.0, N)["n20k"]
        return floors[lv]

    if "dsd64" in only:
        print("\n## Level sweep, 1 kHz, DSD64 source (dsd-upsample gen), default gain\n")
        print("| Source level, DSD64 (dB SACD) | Source (modulator) | Source noise 20-20k (dB SACD) | Output rate | Order | Level out (dB SACD) | SNR 20k (dB) | THD+N (dB) | Noise 20-20k (dB SACD) | 20-50k (dB SACD) | 50-100k (dB SACD) |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for lv in (0, -6, -20, -60, -120):
            src = gen64(lv)
            for mult in (128, 256):
                order = DEFAULT_ORDER[mult]
                out = w(f"dsd64-{lv}-{mult}-{order}.dsf")
                convert(a.bin, src, out, "--rate", str(mult), "--order", str(order))
                r = measure.bands(analyse(out), 1000.0, N)
                print(f"| {lv} | {gen_name(lv)} | {src_floor(lv):.1f} | DSD{mult} | "
                      f"{order_label(mult, order)} | {r['level']:.1f} | "
                      f"{r['snr']:.1f} | {r['thdn']:.1f} | {r['n20k']:.1f} | {r['n50k']:.1f} | "
                      f"{r['n100k']:.1f} |")
        footer("dsd64")

    if "ccif" in only:
        print("\n## CCIF IMD, 19 + 20 kHz, each -6.02 dB (composite peak 0 dB SACD)\n")
        print("| Output rate | Order | d2, 1 kHz (dB re one tone) | d3, 18 + 21 kHz (dB re one tone) |")
        print("|---|---|---|---|")
        src = w("ccif.wav")
        write_wav_f64(src, tone([19000.0, 20000.0], 20 * np.log10(0.5)))  # composite 0 dB SACD
        for mult in (64, 128, 256):
            for order in (DEFAULT_ORDER[mult], 7):
                out = w(f"ccif-{mult}-{order}.dsf")
                convert(a.bin, src, out, "--rate", str(mult), "--gain", "0", "--order", str(order))
                r = measure.imd_ccif(analyse(out), N)
                print(f"| DSD{mult} | {order_label(mult, order)} | {r['d2']:.1f} dB | {r['d3']:.1f} dB |")
        footer("ccif")

    if "idle" in only:
        print("\n## Idle tones: silence and DC\n")
        print("| Input (dB SACD) | Output rate | Order | Dither | Strongest line 20-20k | at | Noise 20-20k |")
        print("|---|---|---|---|---|---|---|")
        for name, dc in (("silence", 0.0), ("DC -40 dB", 10 ** (-40 / 20)),
                         ("DC -60 dB", 10 ** (-60 / 20)), ("DC -80 dB", 10 ** (-80 / 20))):
            src = w(f"idle-{name.replace(' ', '')}.wav")
            write_wav_f64(src, tone([], 0, dc=dc) + np.zeros(int(SECONDS * FS)))
            for mult in (128, 256):
                order = DEFAULT_ORDER[mult]
                for dith in ((False, True) if name == "DC -60 dB" else (False,)):
                    out = w(f"idle-{name.replace(' ', '')}-{mult}-{order}-{int(dith)}.dsf")
                    convert(a.bin, src, out, "--rate", str(mult), "--gain", "0", "--order",
                            str(order), *(["--dither"] if dith else []))
                    r = measure.idle(analyse(out), N)
                    print(f"| {name} | DSD{mult} | {order_label(mult, order)} | "
                          f"{'yes' if dith else 'no'} | {r['spur']:.1f} dB SACD | "
                          f"{r['spur_hz']:.0f} Hz | {r['n20k']:.1f} dB SACD |")
        footer("idle")

    if "overload" in only:
        print("\n## Overload, 1 kHz, DSD256\n")
        print("| Level (dB SACD), DSD256 output | Order, limit | Limited | Clipped-state samples | Resets | THD+N (dB) |")
        print("|---|---|---|---|---|---|")
        order = DEFAULT_ORDER[256]
        for lv in (0, 1, 2, 3, 4, 6):
            src = w(f"over{lv}.wav")
            if not os.path.exists(src):
                write_wav_f64(src, tone([1000.0], lv))
            out = w(f"over{lv}-{order}.dsf")
            args = ["--rate", "256", "--gain", "0", "--order", str(order)]
            li, clip, res = convert(a.bin, src, out, *args)
            r = measure.bands(analyse(out), 1000.0, N)
            ol = f"{order}, {DEFAULT_LIMIT} (defaults)"
            print(f"| +{lv} dB | {ol} | {li} | {clip} | {res} | {r['thdn']:.1f} |")
        footer("overload")

    if "limits" in only:
        print(f"\n## Input limit 0.6 versus lower limits, DSD256, order {DEFAULT_ORDER[256]}, THD+N\n")
        print(f"| Level (dB SACD), DSD256 output | THD+N (dB), limit 0.6 | 0.55 | {DEFAULT_LIMIT} |")
        print("|---|---|---|---|")
        for lv in (0, 1, 2, 3):
            src = w(f"over{lv}.wav")
            if not os.path.exists(src):
                write_wav_f64(src, tone([1000.0], lv))
            row = []
            for lim in ("0.6", "0.55", DEFAULT_LIMIT):
                out = w(f"lim{lv}-{lim}.dsf")
                convert(a.bin, src, out, "--rate", "256", "--gain", "0", "--order",
                        str(DEFAULT_ORDER[256]), "--limit", lim)
                row.append(f"{measure.bands(analyse(out), 1000.0, N)['thdn']:.1f}")
            print(f"| {'+' if lv else ''}{lv} dB | " + " | ".join(row) + " |")
        footer("limits")

    if "cutoff" in only:
        print("\n## DSD64 decimator choice, DSD64 source at -6 dB to DSD256\n")
        print("| First stage (DSD64 source at -6 dB SACD, DSD256 output) | Source (modulator) | Source noise 20-20k | Order | Noise 20-20k |")
        print("|---|---|---|---|---|")
        src = gen64(-6)
        order = DEFAULT_ORDER[256]
        for cut in (None, "30", "40", "wide"):
            out = w(f"cut-{cut}-{order}.dsf")
            convert(a.bin, src, out, "--rate", "256", "--order", str(order),
                    *(["--cutoff", cut] if cut else []))
            r = measure.bands(analyse(out), 1000.0, N)
            name = "140 dB Kaiser (default)" if cut is None else f"`--cutoff {cut}`"
            print(f"| {name} | {gen_name(-6)} | {src_floor(-6):.1f} dB SACD | {order_label(256, order)} | "
                  f"{r['n20k']:.1f} dB SACD |")
        footer("cutoff")


if __name__ == "__main__":
    main()
