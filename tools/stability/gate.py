#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Acceptance gate of the modulator and of the default gain: limited samples, clipped
states and resets of each combination of order, output rate and input limit on the 60 s
set, through the command-line tool. Counters only (no decoding). One JSON file per
(candidate, signal, group); a finished one is skipped, so a run can be resumed.

    python tools/stability/gate.py run --work DIR --cands 128:6:default,256:8:default [--louder] [--hot] [--jobs 4]
    python tools/stability/gate.py table --work DIR
    python tools/stability/gate.py headroom --work DIR [--jobs 4]

A candidate is rate:order:limit; limit `default` passes no --limit. The set, at the
default gain:
- the 29 PCM signals of the stability study (docs/modulator-design.md), 64-bit float WAV
  at 88.2 or 352.8 kHz, every sample within full scale;
- 23 signals through the 48 kHz-family resampler, of the same kinds: random full-scale
  samples, squares at 1 kHz, 10 kHz, a quarter and half of the sample rate, steps and
  impulses at 48, 96 and 384 kHz, and a full-scale 20 kHz sine at 96 and 384 kHz;
- three holds at 0 dB SACD (1, 10 and 20 kHz, 60 s, 32-bit WAV at -6.02 dBFS converted
  with --gain 6.0206, as tools/measure_dsdup.py makes them);
- for DSD128 and DSD256, fifteen DSD tones from `dsd-upsample gen`, at DSD64, DSD128 and
  DSD256: 1 and 19 kHz at 0 dB SACD, and 1, 10 and 19 kHz held at +3.1 dB SACD, the Super
  Audio CD peak level.
Three groups. Legal: PCM whose true peak is at most +6 dBTP, and the DSD tones; a
candidate passes only with nothing limited, clipped or reset on them. Holds: they need a
gain 6 dB above the default, so the limiter may touch them (it does where a tone starts);
nothing may clip or reset. Beyond: the PCM
signals whose true peak is above +6 dBTP (BEYOND: random full-scale samples at four rates
and white noise peaking at full scale); the limiter may work on them, and nothing may clip or reset.
--louder runs the PCM signals again with --gain -3, 3 dB above the default (the default
of earlier builds): limiting is expected, a clipped state or a reset fails the candidate.
--hot adds the study's 10 hot signals with --gain 3, 9 dB above the default.
`headroom` finds, per signal, the highest --gain at which nothing is limited (a search
in steps down to 0.01 dB) and prints the peak at the modulator input that follows from
it: dBTP for PCM, dB SACD for DSD.

Needs NumPy and the measurement tools (tools/measure); `--bin` defaults to
target/release/dsd-upsample.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "measure"))
import dsdio  # noqa: E402
import signals  # noqa: E402

SECONDS = 60.0
LEGAL = ["csine2_1k", "csine2_5k", "csine2_10k", "csine4_1k", "csine4_5k", "csine4_10k",
         "dc+0.5", "dc+0.75", "dc+1.0", "dc-1.0",
         "white_0", "white_-3", "pink_0", "pink_-3", "rand_pm1_88", "rand_pm1_352",
         "sq_1k_88", "sq_10k_88", "sq_fs4_88", "sq_fs2_88",
         "sq_1k_352", "sq_10k_352", "sq_fs4_352", "sq_fs2_352",
         "sine20k_352", "step_88", "step_352", "imp_88", "imp_352"]
RESAMPLED = [f"{s}_{k}" for k in (48, 96, 384)
             for s in ("rand_pm1", "sq_1k", "sq_10k", "sq_fs4", "sq_fs2", "step", "imp")]
RESAMPLED += ["sine20k_96", "sine20k_384"]
HOT = ["csine4_1k", "csine4_10k", "dc+1.0", "white_0", "pink_0", "rand_pm1_352",
       "sq_10k_88", "sq_fs4_352", "sq_fs2_352", "sine20k_352"]
HOLDS = ["hold_1k", "hold_10k", "hold_20k"]
DSDIN = [f"dsd{m}_{t}" for m in (64, 128, 256)
         for t in ("1k_0", "19k_0", "1k_+3.1", "10k_+3.1", "19k_+3.1")]
# PCM within full scale whose true peak is above +6 dBTP (see `headroom`): not legal input.
# Random full-scale samples at 352.8 kHz stay below it in these 60 s (+5.09 dBTP).
BEYOND = ["white_0"] + [f"rand_pm1_{k}" for k in (88, 48, 96, 384)]
LIMIT_DB = 20 * np.log10(0.51 / 0.5)  # the default input limit above 0 dB SACD


def square(fs, f, n):
    t = np.arange(n)
    if f == fs / 2:
        return np.where(t % 2 == 0, 1.0, -1.0)
    if f == fs / 4:
        return np.where((t // 2) % 2 == 0, 1.0, -1.0)
    return np.where(np.sin(2 * np.pi * f * (t + 0.5) / fs) >= 0, 1.0, -1.0)


def pink(n, rng):
    w = rng.standard_normal(n)
    W = np.fft.rfft(w)
    f = np.arange(len(W))
    W[1:] /= np.sqrt(f[1:])
    W[0] = 0
    return np.fft.irfft(W, n)


def make(name):
    """(fs, x) of a stability-study signal; full scale = 1.0 (legal: |x| <= 1)."""
    fs = {"352": 352800, "48": 48000, "96": 96000, "384": 384000}.get(name.rsplit("_", 1)[-1], 88200)
    n = int(SECONDS * fs)
    t = np.arange(n) / fs
    rng = np.random.default_rng(sum(map(ord, name)) * 7919)
    m = re.match(r"csine(\d)_(\d+)k", name)
    if m:
        k, f = int(m.group(1)), 1000.0 * int(m.group(2))
        return fs, np.clip(k * np.sin(2 * np.pi * f * t), -1, 1)
    m = re.match(r"dc([+-][\d.]+)", name)
    if m:
        return fs, np.full(n, float(m.group(1)))
    m = re.match(r"(white|pink)_(-?\d+)", name)
    if m:
        x = rng.uniform(-1, 1, n) if m.group(1) == "white" else pink(n, rng)
        x = x / np.max(np.abs(x))
        return fs, x * 10 ** (int(m.group(2)) / 20)
    if name.startswith("rand_pm1"):
        return fs, np.where(rng.random(n) < 0.5, -1.0, 1.0)
    m = re.match(r"sq_(\w+?)_(88|352|48|96|384)$", name)
    if m:
        s = m.group(1)
        f = {"fs4": fs / 4, "fs2": fs / 2}.get(s) or 1000.0 * int(s[:-1])
        return fs, square(fs, f, n)
    if name.startswith("sine20k"):
        return fs, np.sin(2 * np.pi * 20000.0 * t)
    if name.startswith("step"):  # full-scale steps: +1 for 0.5 s, -1 for 0.5 s
        return fs, np.where((np.arange(n) // (fs // 2)) % 2 == 0, 1.0, -1.0)
    if name.startswith("imp"):  # single-sample full-scale impulses, 100 per second
        x = np.zeros(n)
        x[::int(fs // 100)] = 1.0
        return fs, x
    raise ValueError(name)


def cname(c):
    return f"dsd{c[0]}-o{c[1]}-l{c[2]}"


def is_dsd(name):
    return name.startswith("dsd")


def source(work, binary, name):
    """Path of a signal file, made on first use."""
    ext = ".dsf" if is_dsd(name) else ".wav"
    p = os.path.join(work, "signals", name + ext)
    if os.path.exists(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp{ext}"
    if name.startswith("hold_"):
        f = 1000.0 * int(name[5:-1])
        x = signals.make("hold", 88200, level=signals.SACD0, freq=f, steady=60.0)
        dsdio.write_wav(tmp, x, 88200, "i32")
    elif is_dsd(name):
        m, f, lv = name.split("_")
        subprocess.run([binary, "gen", tmp, "--rate", m[3:], "--freq", str(1000 * int(f[:-1])),
                        "--level", str(float(lv)), "--seconds", "60"], check=True,
                       capture_output=True)
    else:
        fs, x = make(name)
        dsdio.write_wav(tmp, x, fs, "f64")
    os.replace(tmp, p)
    return p


def convert(binary, src, dst, args):
    """Counters of one conversion (first channel), or the error text."""
    p = subprocess.run([binary, src, dst, *args], capture_output=True, text=True)
    if p.returncode:
        return p.stderr[-300:]
    os.remove(dst)
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", p.stderr)
    return dict(zip(("limited", "clipped", "resets"), map(int, k[0])))


def one(t):
    work, binary, name, group, c = t
    tag = {"louder": "louder_", "hot": "hot_"}.get(group, "") + name
    res = os.path.join(work, "counts", cname(c), tag + ".json")
    if os.path.exists(res):
        return f"{cname(c)} {tag} skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    dst = os.path.join(work, "counts", cname(c), tag + ".dsf")
    args = ["--rate", str(c[0]), "--order", str(c[1]), "--single-thread"]
    if c[2] != "default":
        args += ["--limit", c[2]]
    if group == "hot":
        args += ["--gain", "3"]
    elif group == "louder":
        args += ["--gain", "-3"]
    elif name.startswith("hold_"):
        args += ["--gain", "6.0206"]
    cnt = convert(binary, source(work, binary, name), dst, args)
    if isinstance(cnt, str):
        return f"FAIL {cname(c)} {tag}: {cnt}"
    with open(res + ".tmp", "w") as f:
        json.dump({"signal": name, "group": group, "cand": cname(c), "counters": cnt,
                   "command": "dsd-upsample IN OUT " + " ".join(args)}, f)
    os.replace(res + ".tmp", res)
    return f"{cname(c)} {tag} {cnt}"


def group_of(name):
    if name.startswith("hold_"):
        return "hold"
    return "beyond" if name in BEYOND else "legal"


def run(a):
    cands = []
    for x in a.cands.split(","):
        p = x.split(":")
        cands.append((int(p[0]), int(p[1]), p[2]))
    pcm = LEGAL + RESAMPLED
    tasks = []
    for c in cands:
        tasks += [(a.work, a.bin, n, group_of(n), c) for n in pcm + HOLDS]
        if c[0] != 64:
            tasks += [(a.work, a.bin, n, "legal", c) for n in DSDIN]
        if a.louder:
            tasks += [(a.work, a.bin, n, "louder", c) for n in pcm]
        if a.hot:
            tasks += [(a.work, a.bin, n, "hot", c) for n in HOT]
    for n in pcm + HOLDS + DSDIN:
        source(a.work, a.bin, n)
    with Pool(a.jobs) as pool:
        for r in pool.imap_unordered(one, tasks):
            print(r, flush=True)


def group_now(d):
    """The group of a result: by the signal's name for the runs at the default gain."""
    if d["group"] in ("louder", "hot") or is_dsd(d["signal"]):
        return d["group"]
    return group_of(d["signal"])


def table(a):
    rows = {}
    for p in glob.glob(os.path.join(a.work, "counts", "*", "*.json")):
        with open(p) as f:
            d = json.load(f)
        rows.setdefault(d["cand"], []).append(d)

    def key(c):
        p = c.split("-")
        return int(p[0][3:]), int(p[1][1:]), p[2]
    groups = ("legal", "hold", "beyond", "louder", "hot")
    print("| Candidate | Legal signals | Legal: limited / clipped / resets | Holds at 0 dB SACD: "
          "limited / clipped / resets | Beyond +6 dBTP: limited / "
          "clipped / resets | Louder (--gain -3): limited / clipped / resets | Hot (--gain 3): "
          "limited / clipped / resets | Passes | Signals that fail |")
    print("|---|--:|--:|--:|--:|--:|--:|---|---|")
    for c in sorted(rows, key=key):
        cell, bad = [], []
        for grp in groups:
            g = [d for d in rows[c] if group_now(d) == grp]
            if not g:
                cell.append("not run")
                continue
            k = [sum(d["counters"][x] for d in g) for x in ("limited", "clipped", "resets")]
            cell.append(f"{k[0]:,} / {k[1]:,} / {k[2]:,}")
            for d in g:
                n = d["counters"]
                if n["clipped"] or n["resets"] or (grp == "legal" and n["limited"]):
                    bad.append(f"{grp} {d['signal']} {n['limited']}/{n['clipped']}/{n['resets']}")
        n = sum(1 for d in rows[c] if group_now(d) == "legal")
        # the hot group does not decide
        ok = not [b for b in bad if not b.startswith("hot")]
        print(f"| {c} | {n} | {' | '.join(cell)} | {'yes' if ok else 'no'} | "
              f"{', '.join(sorted(bad)) or 'none'} |")


def headroom_one(t):
    work, binary, name = t
    res = os.path.join(work, "headroom", name + ".json")
    if os.path.exists(res):
        with open(res) as f:
            return json.load(f)
    os.makedirs(os.path.dirname(res), exist_ok=True)
    dst = os.path.join(work, "headroom", name + ".dsf")
    rate = "256" if name.startswith("dsd256") else "128" if is_dsd(name) else "64"
    src = source(work, binary, name)

    def clean(centi):  # nothing limited at a gain of centi/100 dB
        cnt = convert(binary, src, dst, ["--rate", rate, "--order", "5", "--single-thread",
                                         "--gain", f"{centi / 100:.2f}"])
        if isinstance(cnt, str):
            raise RuntimeError(cnt)
        return cnt["limited"] == 0
    lo, hi = -2400, 2400  # clean at lo, limited at hi
    if not clean(lo) or clean(hi):
        raise RuntimeError(f"{name}: outside the search range")
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if clean(mid):
            lo = mid
        else:
            hi = mid
    out = {"signal": name, "gain_db": lo / 100, "peak_db": LIMIT_DB - lo / 100}
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return out


def headroom(a):
    names = LEGAL + RESAMPLED + DSDIN
    for n in names:
        source(a.work, a.bin, n)
    with Pool(a.jobs) as pool:
        rows = pool.map(headroom_one, [(a.work, a.bin, n) for n in names])
    print("| Signal | Highest gain with nothing limited (dB) | Peak at the modulator input "
          "(dBTP for PCM, dB SACD for DSD) | Group |")
    print("|---|--:|--:|---|")
    for r in sorted(rows, key=lambda r: -r["peak_db"]):
        g = "legal" if is_dsd(r["signal"]) else group_of(r["signal"])
        print(f"| {r['signal']} | {r['gain_db']:+.2f} | {r['peak_db']:+.2f} | {g} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--cands", required=True)
    r.add_argument("--bin", default=os.path.join(HERE, "..", "..", "target", "release", "dsd-upsample"))
    r.add_argument("--louder", action="store_true")
    r.add_argument("--hot", action="store_true")
    r.add_argument("--jobs", type=int, default=4)
    t = sub.add_parser("table")
    t.add_argument("--work", required=True)
    h = sub.add_parser("headroom")
    h.add_argument("--work", required=True)
    h.add_argument("--bin", default=r.get_default("bin"))
    h.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    {"run": run, "table": table, "headroom": headroom}[a.cmd](a)


if __name__ == "__main__":
    main()
