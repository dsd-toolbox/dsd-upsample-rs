#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Overload behaviour of dsd-upsample on hot real-world material and intersample overs.

Project driver (local use; the music files are never committed):

    python tools/measure_dsdup_music.py --work DIR --ours BIN --music DIR [--jobs 2]

For each DSD64 file in --music (*.dsf) and each PCM file (*.wav, 44.1 kHz family):
- the peak level (group peaks): wideband (reference decoder to 352.8 kHz, flat to 116 kHz)
  and audio band (fast decoder, 4x oversampled true peak), in dB SACD;
- conversions at the CLI's defaults (group final; the order, limit and gain are read from
  `--help` and passed explicitly) and at every other order the rate accepts (group
  convert), to DSD128 and DSD256 (PCM also DSD64), with the limiter, clip and reset
  counters;
- a reference conversion of the same file at 6.02 dB below the default gain; the decoded
  outputs are compared (reference scaled by +6.02 dB, 20 Hz-20 kHz, 50 ms blocks) to
  locate and size the error the overload handling adds.
Also (group isp): an fs/4 tone at 0 dBFS sampled at 45 degrees (+3.01 dB true peak) at
44.1 and 88.2 kHz through the defaults.

Results are named after the file names in --music; to publish them without track names,
point --music at a folder of links named m1.dsf, m2.dsf, ...
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "measure"))
import analyse  # noqa: E402
import decode  # noqa: E402
import dsdio  # noqa: E402
import signals  # noqa: E402

SACD_REF = 0.5


def sacd_db(peak):
    return 20 * np.log10(max(peak, 1e-300) / SACD_REF)


def run_cli(binary, src, dst, args):
    r = subprocess.run(["nice", "-n", "19", binary, src, dst, *args], capture_output=True,
                       text=True)
    if r.returncode:
        raise RuntimeError(f"{src} {args}: {r.stderr[-800:]}")
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", r.stderr)
    return [dict(zip(("limited", "clipped", "resets"), map(int, m))) for m in k]


def read_any(path, ch):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic in (b"DSD ", b"FRM8"):
        return dsdio.read_dsd(path, ch)
    x, fs = dsdio.read_wav(path)
    return x[:, ch], fs


def wide_peak(path, ch, rate, seg=1 << 26):
    """Peak of the reference decode (352.8 kHz), decoded in overlapping segments."""
    h, r = decode.design(rate, 352800)
    pad = (len(h) // r + 2) * r
    pk, buf, pos = 0.0, np.zeros(0, np.uint8), 0
    for blk in dsdio.iter_dsf(path, ch, blocks=seg // 8 // 4096):
        buf = np.concatenate([buf, blk])
        while len(buf) >= seg + 2 * pad:
            y = decode.decode_bits(buf[:seg + 2 * pad], rate, 352800)
            pk = max(pk, float(np.max(np.abs(y[pad // r:(seg + pad) // r]))))
            buf = buf[seg:]
    if len(buf) > pad:
        y = decode.decode_bits(buf, rate, 352800)
        pk = max(pk, float(np.max(np.abs(y[pad // r:len(buf) // r - pad // r]))))
    return pk


def peaks(path):
    out = []
    with open(path, "rb") as f:
        magic = f.read(4)
    for ch in (0, 1):
        if magic == b"DSD ":
            rate = dsdio.dsf_rate(path)
            w = wide_peak(path, ch, rate)
            band = decode.decode_fast(dsdio.iter_dsf(path, ch), rate, 88200)
            fs = 88200
        else:
            x, fs = dsdio.read_wav(path)
            band = x[:, ch].copy() * SACD_REF  # the CLI maps PCM full scale to 0 dB SACD
            del x
            w = float(np.max(np.abs(band)))
        tp = max((analyse.true_peak(band[a:a + (1 << 22) + 64], fs)["true_peak_dbfs"], a)
                 for a in range(0, len(band), 1 << 22))
        out.append({"channel": ch, "wideband_peak_dbsacd": sacd_db(w),
                    "audio_true_peak_dbsacd": tp[0] - 20 * np.log10(SACD_REF)})
    return out

def task_convert(work, ours, src, name, rate, order, keep_ref, limit=None, gain=None):
    res = os.path.join(work, "music", f"{name}-{rate}-{order}{'-l' + str(limit) if limit else ''}.json")
    if os.path.exists(res):
        return res, "skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    tmp = os.path.join(work, "music", "tmp")
    os.makedirs(tmp, exist_ok=True)
    a = os.path.join(tmp, f"{name}-{rate}-{order}.dsf")
    b = os.path.join(tmp, f"{name}-{rate}-{order}-ref.dsf")
    args = ["--rate", str(rate), "--order", str(order)]
    args += ["--limit", str(limit)] if limit else []
    a = a[:-4] + (f"-l{limit}" if limit else "") + ".dsf"
    b = b[:-8] + (f"-l{limit}" if limit else "") + "-ref.dsf"
    t0 = time.time()
    ca = run_cli(ours, src, a, args + ["--gain", f"{gain:g}"])
    cb = run_cli(ours, src, b, args + ["--gain", f"{gain - 6.0206:.4f}"])
    out = {"source": name, "rate": rate, "order": order, "limit": limit, "gain_db": gain,
           "counters": ca,
           "ref_counters": cb, "encode_s": time.time() - t0, "channels": []}
    for ch in (0, 1):
        ra = dsdio.dsf_rate(a)
        ya = decode.decode_fast(dsdio.iter_dsf(a, ch), ra, 88200)
        yb = decode.decode_fast(dsdio.iter_dsf(b, ch), ra, 88200) * 2.0
        c = analyse.compare(ya, yb, 88200)
        c["channel"] = ch
        c["limited_s"] = ca[ch]["limited"] / ra if ca and ch < len(ca) else None
        c["out_true_peak_dbsacd"] = analyse.true_peak(ya, 88200)["true_peak_dbfs"] + 6.0206
        out["channels"].append(c)
    for p in (a, b):
        os.remove(p)
    with open(res, "w") as f:
        json.dump(out, f)
    return res, "done"


def task_peaks(work, src, name):
    res = os.path.join(work, "music", f"{name}-peaks.json")
    if os.path.exists(res):
        return res, "skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    with open(res, "w") as f:
        json.dump({"source": name, "peaks": peaks(src)}, f)
    return res, "done"


def task_isp(work, ours, fs, rate, order, limit, gain):
    """fs/4 at 0 dBFS, 45 degrees: samples at +-full scale, true peak +3.01 dBFS."""
    sfx = f"-o{order}-l{limit}"
    res = os.path.join(work, "music", f"isp{fs}-{rate}{sfx}.json")
    if os.path.exists(res):
        return res, "skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    src = os.path.join(work, "music", f"isp{fs}.wav")
    if not os.path.exists(src):
        x = signals.frame(signals.tones([fs / 4], [np.sqrt(2.0)], [np.pi / 4]), fs, 15.0)
        tmpw = f"{src}.{os.getpid()}.tmp"
        dsdio.write_wav(tmpw, x, fs, "i32")
        os.replace(tmpw, src)
    dst = os.path.join(work, "music", f"isp{fs}-{rate}{sfx}.dsf")
    extra = ["--order", str(order), "--limit", str(limit), "--gain", f"{gain:g}"]
    cnt = run_cli(ours, src, dst, ["--rate", str(rate), *extra])
    bits, r = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    y = decode.decode_bits(bits, r, 352800)
    yy = y[int(5.5 * 352800):len(y) - int(0.1 * 352800)]
    t = analyse.tone(yy, 352800, fs / 4)
    with open(res, "w") as f:
        json.dump({"fs": fs, "rate": rate, "order": order, "limit": limit, "gain_db": gain,
                   "counters": cnt, "tone": t}, f)
    return res, "done"


def task_hot(work, ours, level, rate):
    """DSD64 tone from `dsd-upsample gen` at a hot level, converted at the defaults."""
    res = os.path.join(work, "music", f"hot{level:+.1f}-{rate}.json")
    if os.path.exists(res):
        return res, "skip"
    os.makedirs(os.path.dirname(res), exist_ok=True)
    src = os.path.join(work, "music", f"hot{level:+.1f}.dsf")
    out = {"level_sacd": level, "rate": rate}
    if not os.path.exists(src):
        r = subprocess.run(["nice", "-n", "19", ours, "gen", src + ".tmp.dsf", "--rate", "64",
                            "--freq", "1000", "--level", str(level),
                            "--seconds", "8.5", "--channels", "1"], capture_output=True,
                           text=True)
        if r.returncode:
            out["gen_error"] = r.stderr.strip()[-300:]
            with open(res, "w") as f:
                json.dump(out, f)
            return res, "gen refused"
        os.replace(src + ".tmp.dsf", src)
    b0, r0 = dsdio.read_dsd(src, 0)
    y0 = decode.decode_bits(b0, r0, 352800)[int(0.5 * 352800):-int(0.1 * 352800)]
    out["source_tone"] = analyse.tone(y0, 352800, 1000.0)
    dst = os.path.join(work, "music", f"hot{level:+.1f}-{rate}.dsf")
    out["counters"] = run_cli(ours, src, dst, ["--rate", str(rate)])
    bits, r = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    y = decode.decode_bits(bits, r, 352800)[int(0.5 * 352800):-int(0.1 * 352800)]
    out["tone"] = analyse.tone(y, 352800, 1000.0)
    with open(res, "w") as f:
        json.dump(out, f)
    return res, "done"


def write_meta(a, defaults):
    """music/meta.json: the build and environment behind the real-music rows; a results
    folder made with another build is refused."""
    import platform
    import matplotlib
    import scipy
    import measure_dsdup
    cpu = ""
    with open("/proc/cpuinfo") as f:
        cpu = next((l.split(":", 1)[1].strip() for l in f if l.startswith("model name")), "")
    meta = {"dsd_upsample": {"version": measure_dsdup.first_line([a.ours, "--version"]),
                             "rev": a.ours_rev, "sha256": measure_dsdup.sha256(a.ours),
                             "defaults": defaults},
            "analysis": {"python": platform.python_version(), "numpy": np.__version__,
                         "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
            "cpu": cpu, "date": time.strftime("%Y-%m-%d", time.gmtime())}
    path = os.path.join(a.work, "music", "meta.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
        for k in ("dsd_upsample", "analysis"):
            if old.get(k) != meta[k]:
                raise SystemExit(f"{path}: {k} differs from this run's; use a new --work")
        return
    with open(path, "w") as f:
        json.dump(meta, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True)
    ap.add_argument("--ours", default=os.path.join(HERE, "..", "target", "release", "dsd-upsample"))
    ap.add_argument("--music", required=True)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--only")
    ap.add_argument("--ours-rev", default="unknown", help="source revision of --ours (recorded)")
    a = ap.parse_args()
    groups = a.only.split(",") if a.only else ["isp", "peaks", "final", "convert"]
    sys.path.insert(0, HERE)
    import measure_dsdup
    d = measure_dsdup.cli_defaults(a.ours)
    o0, lim0, g0 = d["order"], d["limit"], d["gain_db"]
    write_meta(a, d)
    tasks = []
    srcs = sorted(glob.glob(os.path.join(a.music, "*.dsf")) +
                  glob.glob(os.path.join(a.music, "*.wav")))
    if "isp" in groups:
        for fs in (44100, 88200):
            for r in (64, 128, 256):
                tasks.append((task_isp, (a.work, a.ours, fs, r, o0, lim0, g0)))
    if "hot" in groups:
        for lv in (3.1, 4.0, 5.0, 6.0, 7.0):
            for r in (128, 256):
                tasks.append((task_hot, (a.work, a.ours, lv, r)))
    for s in srcs:
        name = os.path.splitext(os.path.basename(s))[0]
        rates = (128, 256) if s.endswith(".dsf") else (64, 128, 256)
        if "peaks" in groups:
            tasks.append((task_peaks, (a.work, s, name)))
        for r in rates:
            for o in measure_dsdup.orders(r):
                if ("final" in groups and o == o0) or ("convert" in groups and o != o0):
                    tasks.append((task_convert, (a.work, a.ours, s, name, r, o, False, lim0, g0)))
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(fn, *args) for fn, args in tasks]
        for i, fu in enumerate(as_completed(futs)):
            try:
                print(f"[{i + 1}/{len(futs)} {time.time() - t0:.0f}s]", *fu.result(), flush=True)
            except Exception as e:
                print(f"[{i + 1}/{len(futs)}] FAILED {e}", flush=True)


if __name__ == "__main__":
    main()
