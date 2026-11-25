#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Archimago-style measurement matrix for dsd-upsample, with SoX-DSD as a black-box reference.

Thin project driver around the generic tools in tools/measure/: it renders the test
signals, runs the dsd-upsample CLI (orders 5-8, DSD64/128/256) and SoX-DSD (sdm-4/6/8,
clans-4..8, a few trellis settings) on them, analyses every output with the reference
decoder, and writes the tables and SVG plots for docs/measurements-dsd.md.

    python tools/measure_dsdup.py run --work DIR [--ours BIN] [--sox BIN] [--jobs N] [--only GROUP]
    python tools/measure_dsdup.py report --work DIR [--assets docs/assets/measurements]

Groups: main (all signals x all configs), sweep (IMD sweeps), stability (60 s holds),
ceiling (short tones near full scale), final (the defaults under hot input).
Results are JSON files under DIR/results; a step whose
result exists is skipped, so a run can be resumed. DSD outputs are deleted once
analysed (except with --keep).

dsd-upsample maps WAV full scale to 0 dB SACD; it runs at --gain +6.0206 so that, like
SoX, 0 dBFS in = 100 % modulation and the decoded level equals the input level.

Configuration names (the results directory per configuration):
- dsdup-oN-R: order N at the CLI's default input limit;
- trya-R-oN-lL: order N, limit L (the defaults under hot input).

Provenance: `run` writes DIR/meta.json with the version, source revision and SHA-256 of
both binaries, the Python package versions and the CPU, and refuses to add results made
with different binaries to the same DIR (--replace-ours: a new dsd-upsample build replaces
its own results and keeps SoX-DSD's). SoX-DSD runs with OMP_NUM_THREADS=1. Build it
with tools/measure/sox-dsd.Containerfile (mansr/sox at a pinned commit).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "measure"))
import analyse  # noqa: E402
import decode  # noqa: E402
import density  # noqa: E402
import dsdio  # noqa: E402
import signals  # noqa: E402

FS_IN = 88200
SACD0 = signals.SACD0  # -6.02 dBFS
PEAK = signals.PEAK  # -2.92 dBFS
GAIN = "6.0206"  # 20 log10(2)
SOX_SHIFT = 20 * np.log10(2.0)
RATES = (64, 128, 256)
ORDERS = (5, 6, 7, 8)


def orders(rate):
    """The modulator orders the library accepts at a DSD rate (order 8 is refused at DSD128)."""
    return tuple(o for o in ORDERS if not (rate == 128 and o == 8))
SOX_MODS = ("sdm-4", "sdm-6", "sdm-8", "clans-4", "clans-5", "clans-6", "clans-7", "clans-8")
# Trellis settings as used in Archimago's 2022 "perfect DAC" runs (per rate)
SOX_TRELLIS = {64: "clans-8", 128: "clans-7", 256: "clans-6"}

TRELLIS_SIGNALS = ("tone0", "dr", "silence", "mt0")
# main signals: id -> (generator kwargs, source rate, format, analyses)
MAIN = {
    "tone0": (dict(sig="sine", level=SACD0), ["tone"]),
    "tone-3": (dict(sig="sine", level=SACD0 - 3), ["tone"]),
    "tone-20": (dict(sig="sine", level=SACD0 - 20), ["tone"]),
    "tone-40": (dict(sig="sine", level=SACD0 - 40), ["tone"]),
    "tonepk": (dict(sig="sine", level=PEAK), ["tone"]),
    "dr": (dict(sig="sine", level=SACD0 - 60), ["dr"]),
    "silence": (dict(sig="silence"), ["noise"]),
    "jtest": (dict(sig="jtest", level=SACD0), ["jtest"]),
    "mt0": (dict(sig="multitone", level=SACD0), ["multitone"]),
    "mtpk": (dict(sig="multitone", level=PEAK), ["multitone"]),
    "smpte": (dict(sig="smpte", level=SACD0), ["smpte"]),
    "ccif": (dict(sig="ccif", level=SACD0), ["ccif"]),
}
SWEEP = {}
for c in (10000, 12000, 14000, 16000, 18000, 19500):
    SWEEP[f"ccif{c // 100}"] = (dict(sig="ccif", level=SACD0, f1=c - 500, f2=c + 500),
                                ["ccif"])
for lv in (-60, -50, -40, -30, -20, -10, 0):
    SWEEP[f"smpte{lv}"] = (dict(sig="smpte", level=SACD0 + lv), ["smpte"])
HOLD_FREQS = (1000, 10000, 20000)
HOLD_LEVELS = (0.0, 1.5, 3.1, 4.1, 6.1)  # dB SACD


def src_rate(sid):
    return 44100 if sid.startswith("jtest") else FS_IN


def configs(group):
    out = []
    for r in RATES:
        for o in orders(r):
            out.append(f"dsdup-o{o}-{r}")
    if group in ("main", "ultra"):
        for r in RATES:
            for m in SOX_MODS:
                out.append(f"sox-{m}-{r}")
            out.append(f"sox-{SOX_TRELLIS[r]}t-{r}")
    if group == "sweep":
        out += [f"sox-sdm-8-{r}" for r in RATES] + [f"sox-clans-8-{r}" for r in RATES]
    return out


def cli_defaults(binary):
    """The CLI's default order, input limit and gain, read from its --help text."""
    out = subprocess.run([binary, "--help"], capture_output=True, text=True).stdout
    m = re.search(r"Defaults: --order (\d+), --limit ([0-9.]+), --gain (-?[0-9.]+)", out)
    if not m:
        raise SystemExit(f"{binary} --help: no 'Defaults: --order N, --limit L, --gain G' line")
    return {"order": int(m.group(1)), "limit": m.group(2), "gain_db": float(m.group(3))}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def first_line(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return ((r.stdout or r.stderr).strip().splitlines() or [""])[0]


def write_meta(work, bins, ours_rev, sox_source, replace_ours=False):
    """Record what made the results; refuse to mix binaries in one results directory."""
    import platform
    import matplotlib
    import scipy
    path = os.path.join(work, "meta.json")
    cpu = ""
    try:
        with open("/proc/cpuinfo") as f:
            cpu = next((l.split(":", 1)[1].strip() for l in f if l.startswith("model name")), "")
    except OSError:
        pass
    sox = shutil.which(bins["sox"]) or bins["sox"]
    meta = {
        "dsd_upsample": {"version": first_line([bins["ours"], "--version"]), "rev": ours_rev,
                         "sha256": sha256(bins["ours"]), "defaults": cli_defaults(bins["ours"])},
        "sox": {"version": first_line([sox, "--version"]).split(":")[-1].strip(),
                "source": sox_source, "sha256": sha256(sox), "env": "OMP_NUM_THREADS=1"},
        "analysis": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "cpu": cpu,
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
        if replace_ours and old.get("dsd_upsample") != meta["dsd_upsample"]:
            # a new dsd-upsample build: drop its results, keep SoX-DSD's and the PCM rows
            res = os.path.join(work, "results")
            for cfg in os.listdir(res) if os.path.isdir(res) else ():
                if cfg.startswith(("dsdup-", "trya-", "default-")):
                    shutil.rmtree(os.path.join(res, cfg))
            old["dsd_upsample"] = meta["dsd_upsample"]
            old["date_dsd_upsample"] = meta["date"]
            with open(path, "w") as f:
                json.dump(old, f, indent=1)
        for k in ("dsd_upsample", "sox", "analysis"):
            if old.get(k) != meta[k]:
                raise SystemExit(f"{path}: {k} differs from this run's; use a new --work"
                                 f"{' or --replace-ours' if k == 'dsd_upsample' else ''}\n"
                                 f"  was {old.get(k)}\n  now {meta[k]}")
        return old
    with open(path, "w") as f:
        json.dump(meta, f, indent=1)
    return meta


def parse_try(cfg):
    """(rate, order, limit) of a trya- configuration name."""
    _, rr, oo, ll = cfg.split("-")
    return int(rr), int(oo[1:]), float(ll[1:])


def encode(cfg, src, dst, bins, extra=(), adapter=True):
    """Run one encoder; returns (seconds, counters dict or None, command)."""
    if cfg.startswith("trya"):  # trya-RATE-oORDER-lLIMIT
        r, o, lim = parse_try(cfg)
        cmd = [bins["ours"], src, dst, "--rate", str(r), "--order", str(o), "--limit", str(lim),
               *(["--gain", GAIN] if adapter else []), "--single-thread", *extra]
    elif cfg.startswith("dsdup"):
        # dsdup-oN-R: order N at the CLI's default input limit
        m = re.match(r"\w+-o(\d)-(\d+)", cfg)
        cmd = [bins["ours"], src, dst, "--rate", m.group(2), "--order", m.group(1),
               "--gain", GAIN, "--single-thread", *extra]
    else:
        m = re.match(r"sox-(.+?)(t?)-(\d+)$", cfg)
        mod, trellis, mult = m.group(1), m.group(2), int(m.group(3))
        eff = ["sdm", "-f", mod] + (["-t", "32", "-n", "32"] if trellis else [])
        cmd = [bins["sox"], "-D", src, "-t", "dsf", dst, "rate", "-v", str(44100 * mult), *eff]
    env = dict(os.environ, OMP_NUM_THREADS="1")
    t0 = time.time()
    r = subprocess.run(["nice", "-n", "19", *cmd], capture_output=True, text=True, env=env)
    dt = time.time() - t0
    if r.returncode:
        raise RuntimeError(f"{cfg}: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", r.stderr)
    cnt = None
    if k:
        cnt = dict(zip(("limited", "clipped", "resets"), map(int, k[0])))
    return dt, cnt, " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))


def write_signal(work, sid, spec, fmt="i32", dither=None):
    kw = dict(spec)
    sig = kw.pop("sig")
    fs = src_rate(sid)
    path = os.path.join(work, "signals", f"{sid}-{fmt}.wav")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        x = signals.make(sig, fs, **kw)
        if dither is not None:
            x = x + signals.tpdf(len(x), int(fmt[1:]), dither)
        tmp = f"{path}.{os.getpid()}.tmp"
        dsdio.write_wav(tmp, x, fs, fmt)
        os.replace(tmp, path)
    return path


def run_analyses(y, fs, sid, kinds, skip=5.5):
    y = y[int(skip * fs):len(y) - int(0.1 * fs)]
    out = {}
    for k in kinds:
        if k == "tone":
            out[k] = analyse.tone(y, fs, 1000.0)
        elif k == "dr":
            out[k] = analyse.dr(y, fs, 1000.0, SACD0)
        elif k == "noise":
            out[k] = analyse.noise(y, fs)
        elif k == "jtest":
            out[k] = analyse.jtest(y, fs, 44100)
        elif k == "multitone":
            out[k] = analyse.multitone(y, fs)
        elif k == "smpte":
            out[k] = analyse.smpte(y, fs)
        elif k == "ccif":
            kw = SWEEP.get(sid, MAIN.get(sid))[0]
            out[k] = analyse.ccif(y, fs, kw.get("f1", 19000.0), kw.get("f2", 20000.0))
        elif k == "ultrasonic":
            out[k] = analyse.ultrasonic(y, fs)
    return out


def save_spectra(path, y, fs, sid, skip=5.5):
    """Spectra for plots, float32 dB: in-band view and, for high-rate decodes, ultrasonic."""
    y = y[int(skip * fs):len(y) - int(0.1 * fs)]
    d = {"fs": fs}
    if sid in ("mt0", "mtpk"):
        from scipy import signal as sg
        n = analyse.points(fs, 1 << 20)
        h = sg.firwin(int(fs / 88.2) | 1, 25000.0, fs=fs, window=("kaiser", 16.0))
        yl = sg.oaconvolve(y, h, mode="same")[len(h):-len(h)]
        p, f, _ = analyse.spectrum(yl, fs, n, 8, "rect")
        d["mt_f"], d["mt_db"] = f.astype(np.float32), analyse.amplitude_db(p, n, "rect").astype(np.float32)
    elif sid in ("silence", "jtest") or fs > 352800:
        n = analyse.points(fs, 1 << 20)
        p, f, enbw = analyse.spectrum(y, fs, n, 8)
        m = f <= 200000
        d["n_f"] = f[m].astype(np.float32)
        d["n_db"] = analyse.amplitude_db(p, n)[m].astype(np.float32)
        d["n_dbhz"] = (10 * np.log10(np.maximum(p[m] / enbw / analyse.FS_POWER, 1e-300))).astype(np.float32)
    else:
        n = analyse.points(fs, 1 << 18)
        p, f, _ = analyse.spectrum(y, fs, n)
        d["t_f"], d["t_db"] = f.astype(np.float32), analyse.amplitude_db(p, n).astype(np.float32)
    np.savez_compressed(path, **d)


def task_main(work, bins, cfg, sid, kinds, keep, spectra_cfgs):
    res = os.path.join(work, "results", cfg, f"{sid}.json")
    if os.path.exists(res):
        return cfg, sid, "skip"
    spec = (MAIN.get(sid) or SWEEP.get(sid))[0]
    os.makedirs(os.path.dirname(res), exist_ok=True)
    fmt = "i24" if sid == "jtest" else "i32"
    if cfg.startswith("sox"):
        # SoX-DSD encodes PCM full scale as 50 % modulation (measured), so its input is
        # raised by 6.02 dB; signals that would then exceed full scale cannot be run.
        spec = dict(spec)
        if spec.get("level") is not None:
            spec["level"] += SOX_SHIFT
            if spec["level"] > 1e-9:
                out = {"config": cfg, "signal": sid, "not_run":
                       "needs more than PCM full scale at the SoX input (0 dB SACD cap)"}
                with open(res, "w") as f:
                    json.dump(out, f)
                return cfg, sid, "not run"
        src = write_signal(work, sid + "-sox", spec, fmt)
    else:
        src = write_signal(work, sid, spec, fmt)
    out = {"config": cfg, "signal": sid, "source": os.path.basename(src)}
    if cfg == "pcm24":
        # the same signal as a 24-bit TPDF-dithered file, analysed at its own rate
        p = src if sid == "jtest" else write_signal(work, sid, spec, "i24", 7)
        x, fs = dsdio.read_wav(p)
        y = x[:, 0]
        out["analysis"] = run_analyses(y, fs, sid, kinds)
        if cfg in spectra_cfgs:
            save_spectra(res[:-5] + ".npz", y, fs, sid)
    else:
        dst = os.path.join(work, "dsd", cfg, f"{sid}.dsf")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        dt, cnt, cmd = encode(cfg, src, dst, bins)
        out.update({"encode_s": dt, "counters": cnt, "command": cmd})
        bits, rate = dsdio.read_dsd(dst, 0)
        y = decode.decode_bits(bits, rate, 352800)
        out["analysis"] = run_analyses(y, 352800, sid, kinds)
        if cfg in spectra_cfgs:
            save_spectra(res[:-5] + ".npz", y, 352800, sid)
        if sid in ("tone0", "silence", "dr"):
            hi = 705600 if rate <= 5644800 else 1411200
            yh = decode.decode_bits(bits, rate, hi)
            out["ultrasonic"] = run_analyses(yh, hi, sid, ["ultrasonic"])["ultrasonic"]
            out["ultrasonic_fs"] = hi
            save_spectra(res[:-5] + "-ultra.npz", yh, hi, sid)
        b = bits[int(5.5 * rate):]
        dn = density.analyse_bits(b, rate)
        dn.pop("per_second_min_mean_max")
        out["density"] = dn
        if not keep:
            os.remove(dst)
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return cfg, sid, "done"


def band_noise_blocks(y, fs, block):
    """In-band (20 Hz-20 kHz) noise in dBFS per block of `block` samples (2^14 BH7 FFT)."""
    out = []
    for a in range(0, len(y) - block + 1, block):
        n = 1 << 14
        p, f, _ = analyse.spectrum(y[a:a + block], fs, n, max(1, block // n))
        out.append(analyse.db(np.sum(p[analyse.band(f, 20, 20000)]) / analyse.FS_POWER))
    return out


def task_hold(work, bins, cfg, freq, lvl, limit):
    tag = f"hold{freq // 1000}k{lvl:+.1f}{'-l' + limit if limit else ''}"
    res = os.path.join(work, "results", cfg, f"{tag}.json")
    if os.path.exists(res):
        return cfg, tag, "skip"
    sid = f"hold{freq // 1000}k{lvl:+.1f}"
    level = SACD0 + lvl
    if cfg.startswith("sox"):
        level += SOX_SHIFT
        if level > 1e-9:
            return cfg, tag, "not run"
        sid += "-sox"
    src = write_signal(work, sid, dict(sig="hold", level=level, freq=freq, steady=60.0))
    dst = os.path.join(work, "dsd", cfg, f"{tag}.dsf")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.makedirs(os.path.dirname(res), exist_ok=True)
    extra = ("--limit", limit) if limit else ()
    dt, cnt, cmd = encode(cfg, src, dst, bins, extra)
    bits, rate = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    t_on, t_off = signals.SILENCE + signals.RAMP, signals.SILENCE + signals.RAMP + 60.0
    dn = density.analyse_bits(bits[int(t_on * rate):int(t_off * rate)], rate)
    out = {"config": cfg, "freq": freq, "level_sacd": lvl, "limit": limit, "counters": cnt,
           "encode_s": dt, "command": cmd, "density": dn}
    # THD+N drift: 0-10 s against 50-60 s of the hold; recovery after the tone stops
    fs = 352800
    seg = lambda a, b: decode.decode_bits(bits[int(a * rate):int(b * rate)], rate, fs)  # noqa: E731
    first = seg(t_on, t_on + 10)[int(0.5 * fs):]
    last = seg(t_off - 10, t_off)[int(0.5 * fs):]
    out["thdn_first"] = analyse.tone(first, fs, signals.coherent(freq))["thdn_db"]
    out["thdn_last"] = analyse.tone(last, fs, signals.coherent(freq))["thdn_db"]
    before = seg(0.2, signals.SILENCE)
    after = seg(t_off - 0.1, t_off + 10)
    blk = int(0.05 * fs)
    nb = band_noise_blocks(before[int(0.1 * fs):], fs, blk)
    na = band_noise_blocks(after[int(0.1 * fs):], fs, blk)
    ref = max(nb)
    rec = None
    for i in range(len(na)):
        if all(v <= ref + 3 for v in na[i:]):
            rec = i * 50
            break
    out.update({"idle_before_dbfs": float(np.mean(nb)), "idle_after_dbfs": float(np.mean(na[-20:])),
                "recovery_ms": rec, "idle_after_blocks": [float(v) for v in na[:40]]})
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return cfg, tag, "done"


CEIL_LEVELS = [x / 2 for x in range(-12, 3)]  # -6.0 .. +1.0 dB SACD
CEIL_FREQS = (1000, 10000, 20000)


def task_ceiling(work, bins, cfg, freq, lvl):
    """Short 1 kHz/10 kHz/20 kHz tone at lvl dB SACD (output level = input level adapter)."""
    tag = f"ceil{freq // 1000}k{lvl:+.1f}"
    res = os.path.join(work, "results", cfg, f"{tag}.json")
    if os.path.exists(res):
        return cfg, tag, "skip"
    src = write_signal(work, tag, dict(sig="sine", level=SACD0 + lvl, freq=freq, steady=3.0))
    dst = os.path.join(work, "dsd", cfg, f"{tag}.dsf")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.makedirs(os.path.dirname(res), exist_ok=True)
    dt, cnt, cmd = encode(cfg, src, dst, bins)
    bits, rate = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    y = decode.decode_bits(bits, rate, 352800)
    yy = y[int(5.5 * 352800):len(y) - int(0.1 * 352800)]
    t = analyse.tone(yy, 352800, signals.coherent(freq))
    dn = density.analyse_bits(bits[int(5.5 * rate):], rate)
    dn.pop("per_second_min_mean_max")
    out = {"config": cfg, "freq": freq, "level_sacd": lvl, "counters": cnt, "command": cmd,
           "tone": t, "density": dn}
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return cfg, tag, "done"


def task_default(work, bins, kind, rate_out, freq):
    """The CLI at its defaults (no --order, --limit or --gain): PCM peaking at 0 dBFS, or
    a DSD64 file from `dsd-upsample gen` peaking at +3.1 dB SACD (gen makes it with a
    second-order modulator: the source's own in-band noise is about 72 dB below the tone)."""
    tag = f"default-{kind}-{freq // 1000}k"
    cfg = f"default-{rate_out}"
    res = os.path.join(work, "results", cfg, f"{tag}.json")
    if os.path.exists(res):
        return cfg, tag, "skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    sig_dir = os.path.join(work, "signals")
    os.makedirs(sig_dir, exist_ok=True)
    out = {"config": cfg, "kind": kind, "freq": freq}
    if kind == "pcm0dbfs":
        src = write_signal(work, f"pcm0-{freq // 1000}k",
                           dict(sig="sine", level=0.0, freq=freq, steady=3.0))
    else:
        src = os.path.join(sig_dir, f"dsd64-p31-{freq // 1000}k.dsf")
        if not os.path.exists(src):
            tmp = f"{src}.{os.getpid()}.tmp.dsf"
            subprocess.run(["nice", "-n", "19", bins["ours"], "gen", tmp, "--rate", "64",
                            "--freq", str(int(freq)), "--level", "3.1",
                            "--seconds", "8.5", "--channels", "1"],
                           check=True, capture_output=True)
            os.replace(tmp, src)
        b0, r0 = dsdio.read_dsd(src, 0)
        y0 = decode.decode_bits(b0, r0, 352800)[int(0.5 * 352800):]
        out["source_tone"] = analyse.tone(y0[:len(y0) - int(0.1 * 352800)], 352800, freq)
        d0 = density.analyse_bits(b0, r0)
        d0.pop("per_second_min_mean_max")
        out["source_density"] = d0
    dst = os.path.join(work, "dsd", cfg, f"{tag}.dsf")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    cmd = [bins["ours"], src, dst, "--rate", str(rate_out)]
    r = subprocess.run(["nice", "-n", "19", *cmd], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1000:])
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", r.stderr)
    out["counters"] = dict(zip(("limited", "clipped", "resets"), map(int, k[0]))) if k else None
    out["command"] = " ".join([os.path.basename(cmd[0]), *[os.path.basename(c) for c in cmd[1:3]], *cmd[3:]])
    bits, rate = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    y = decode.decode_bits(bits, rate, 352800)
    skip = 5.5 if kind == "pcm0dbfs" else 0.5
    yy = y[int(skip * 352800):len(y) - int(0.1 * 352800)]
    out["tone"] = analyse.tone(yy, 352800, signals.coherent(freq) if kind == "pcm0dbfs" else freq)
    dn = density.analyse_bits(bits[int(skip * rate):], rate)
    dn.pop("per_second_min_mean_max")
    out["density"] = dn
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return cfg, tag, "done"


# the gain of the hot-input runs: 3 dB louder than the default gain of -6 dB, so that
# +3.1, +4.8 and +7.0 dB SACD before the gain drive the input limiter
HOT_GAIN = -3.0


def limit_of(cfg):
    return parse_try(cfg)[2]


def task_hotpcm(work, bins, cfg, lvl, freq):
    """Order and limit at --gain HOT_GAIN (fixed, so the conditions do not move with the
    default gain) on a hot PCM tone: a 64-bit float WAV at lvl dB re full scale (WAV full
    scale = 0 dB SACD), 60 s, then silence."""
    tag = f"hot{freq // 1000}k{lvl:+.1f}"
    res = os.path.join(work, "results", cfg, f"{tag}.json")
    if os.path.exists(res):
        return cfg, tag, "skip"
    sid = f"hotpcm{freq // 1000}k{lvl:+.1f}"
    src = write_signal(work, sid, dict(sig="hold", level=lvl, freq=freq, steady=60.0), "f64")
    dst = os.path.join(work, "dsd", cfg, f"{tag}.dsf")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.makedirs(os.path.dirname(res), exist_ok=True)
    dt, cnt, cmd = encode(cfg, src, dst, bins, extra=("--gain", f"{HOT_GAIN:g}"), adapter=False)
    bits, rate = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    out = hold_analysis(bits, rate, freq)
    # excess error against an ideal hard limiter: the same tone at HOT_GAIN, clipped at
    # the limit
    lim = limit_of(cfg)
    g = 10 ** (HOT_GAIN / 20)
    f0 = signals.coherent(freq)
    ex = []
    for t0 in (10.0, 60.0):
        n0, n1 = int(t0 * rate), int((t0 + 1.0) * rate)
        t = np.arange(n0, n1) / rate - (signals.SILENCE)
        # WAV full scale = 0.5 (0 dB SACD) at the modulator; limit in the same units
        ideal = np.clip(0.5 * g * 10 ** (lvl / 20) * np.sin(2 * np.pi * f0 * t), -lim, lim)
        e = analyse.excess(bits[n0:n1], rate, ideal)
        e["at_s"] = t0
        ex.append(e)
    out["excess"] = ex
    out.update({"config": cfg, "freq": freq, "level_before_gain_sacd": lvl, "gain_db": HOT_GAIN,
                "counters": cnt,
                "command": cmd, "limited_s": (cnt or {}).get("limited", 0) / rate})
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return cfg, tag, "done"


def hold_analysis(bits, rate, freq):
    t_on, t_off = signals.SILENCE + signals.RAMP, signals.SILENCE + signals.RAMP + 60.0
    dn = density.analyse_bits(bits[int(t_on * rate):int(t_off * rate)], rate)
    fs = 352800
    seg = lambda a, b: decode.decode_bits(bits[int(a * rate):int(b * rate)], rate, fs)  # noqa: E731
    first = seg(t_on, t_on + 10)[int(0.5 * fs):]
    last = seg(t_off - 10, t_off)[int(0.5 * fs):]
    out = {"density": dn,
           "tone_first": analyse.tone(first, fs, signals.coherent(freq)),
           "thdn_first": analyse.tone(first, fs, signals.coherent(freq))["thdn_db"],
           "thdn_last": analyse.tone(last, fs, signals.coherent(freq))["thdn_db"]}
    before = seg(0.2, signals.SILENCE)
    after = seg(t_off - 0.1, t_off + 10)
    blk = int(0.05 * fs)
    nb = band_noise_blocks(before[int(0.1 * fs):], fs, blk)
    na = band_noise_blocks(after[int(0.1 * fs):], fs, blk)
    out.update({"idle_before_dbfs": float(np.mean(nb)), "idle_after_dbfs": float(np.mean(na[-20:])),
                "idle_after_blocks": [float(v) for v in na[:40]]})
    return out


def cmd_run(a):
    bins = {"ours": a.ours, "sox": a.sox}
    work = a.work
    os.makedirs(work, exist_ok=True)
    meta = write_meta(work, bins, a.ours_rev, a.sox_source, a.replace_ours)
    spectra_cfgs = set(configs("main")) | {"pcm24"}
    tasks = []
    groups = a.only.split(",") if a.only else ["main", "sweep", "stability", "soxhold"]
    if "main" in groups:
        for sid, (_, kinds) in MAIN.items():
            for cfg in ["pcm24"] + configs("main"):
                if "t-" in cfg and sid not in TRELLIS_SIGNALS:
                    continue  # trellis is about 20x slower than real time: time-boxed
                tasks.append((task_main, (work, bins, cfg, sid, kinds, a.keep, spectra_cfgs)))
    if "sweep" in groups:
        for sid, (_, kinds) in SWEEP.items():
            for cfg in ["pcm24"] + configs("sweep"):
                tasks.append((task_main, (work, bins, cfg, sid, kinds, a.keep, set())))
    if "stability" in groups:
        for r in RATES:
            for o in orders(r):
                for fr in HOLD_FREQS:
                    for lv in HOLD_LEVELS:
                        for lim in (None, "1.0"):
                            tasks.append((task_hold, (work, bins, f"dsdup-o{o}-{r}", fr, lv, lim)))
    if "ceiling" in groups:
        for r in (128, 256, 64):
            for o in orders(r):
                for fr in CEIL_FREQS:
                    for lv in CEIL_LEVELS:
                        tasks.append((task_ceiling, (work, bins, f"dsdup-o{o}-{r}", fr, lv)))
        for kind in ("pcm0dbfs", "dsd64p31"):
            for r in ((64, 128, 256) if kind == "pcm0dbfs" else (128, 256)):
                for fr in CEIL_FREQS:
                    tasks.append((task_default, (work, bins, kind, r, fr)))
    if "final" in groups:
        # the defaults under hot input
        dflt = meta["dsd_upsample"]["defaults"]
        for r in RATES:
            cfg = f"trya-{r}-o{dflt['order']}-l{dflt['limit']}"
            for fr in CEIL_FREQS:
                tasks.append((task_hold, (work, bins, cfg, fr, 0.0, None)))
                for lv in (3.1, 4.8, 7.0):
                    tasks.append((task_hotpcm, (work, bins, cfg, lv, fr)))
    if "soxhold" in groups:
        for r in RATES:
            for m in ("sdm-8", "clans-8", "sdm-4", "clans-4"):
                for fr in HOLD_FREQS:
                    for lv in HOLD_LEVELS:
                        tasks.append((task_hold, (work, bins, f"sox-{m}-{r}", fr, lv, None)))
    if a.filter:
        def key(t):
            args = t[1]
            if t[0] is task_main:
                return f"{args[2]} {args[3]}"
            if t[0] in (task_ceiling, task_default, task_hotpcm):
                return f"{args[2]} {args[3]} {args[4]}"
            return f"{args[2]} hold {args[3]} {args[4]} {args[5]}"
        tasks = [t for t in tasks if re.search(a.filter, key(t))]
    # priority: ours at DSD128/256, ours at DSD64, ours stability and sweeps, SoX, trellis
    def prio(t):
        if t[0] in (task_ceiling, task_default, task_hotpcm):
            return -1
        cfg = str(t[1][2])
        if cfg.startswith("dsdup"):
            return (0 if not cfg.endswith("-64") else 1) + (2 if t[0] is task_hold else 0)
        if cfg == "pcm24":
            return 0
        return 6 if "t-" in cfg else 5 if t[0] is task_hold else 4
    tasks.sort(key=prio)
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(fn, *args) for fn, args in tasks]
        for fu in as_completed(futs):
            done += 1
            try:
                cfg, sid, st = fu.result()
                print(f"[{done}/{len(futs)} {time.time() - t0:.0f}s] {cfg} {sid} {st}", flush=True)
            except Exception as e:  # keep going; the failure is logged
                print(f"[{done}/{len(futs)}] FAILED {e}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--ours", default=os.path.join(HERE, "..", "target", "release", "dsd-upsample"))
    r.add_argument("--sox", default="sox", help="SoX-DSD binary (default: sox on PATH)")
    r.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    r.add_argument("--only")
    r.add_argument("--filter")
    r.add_argument("--keep", action="store_true")
    r.add_argument("--ours-rev", default=None,
                   help="source revision of --ours (default: git rev-parse HEAD of this tree)")
    r.add_argument("--replace-ours", action="store_true",
                   help="--ours is a new build: delete its earlier results in --work, keep SoX-DSD's")
    r.add_argument("--sox-source", default="mansr/sox 0be259eaa9ce3f3fa587a3ef0cf2c0b9c73167a2, "
                   "static build, tools/measure/sox-dsd.Containerfile",
                   help="where the SoX-DSD binary was built from (recorded in meta.json)")
    p = sub.add_parser("report")
    p.add_argument("--work", required=True)
    p.add_argument("--assets", default=os.path.join(HERE, "..", "docs", "assets", "measurements"))
    p.add_argument("--doc", help="fill the <!-- table:NAME --> blocks of this Markdown file")
    a = ap.parse_args()
    if a.cmd == "run":
        if a.ours_rev is None:
            r = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True)
            a.ours_rev = r.stdout.strip() or "unknown"
        cmd_run(a)
    else:
        import measure_dsdup_report
        if a.doc:
            measure_dsdup_report.fill(a.doc, a.work, a.assets)
        else:
            measure_dsdup_report.report(a.work, a.assets)


if __name__ == "__main__":
    main()
