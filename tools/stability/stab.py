# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stability study: adversarial PCM signals through the command-line tool, 60 s each.

Every signal of LEGAL (PCM within full scale, at --gain -3, the default gain when the study
was made and now the louder setting, 3 dB above the default) and HOT (the same kind of
signal with --gain 3) is converted with each candidate; the modulator's clip and
reset counters are read from the CLI, and the error left in the audio band beyond an ideal
hard limiter is measured with the reference decoder of tools/measure. Also: a 1 kHz tone at
-3 and 0 dB SACD and CCIF, SMPTE and multitone signals at a 0 dB SACD peak.

The error measurement needs the modulator input, which a build with dump.patch writes to the
file named by DSDUP_DUMP_U (see README.md). Environment:

  STAB_CANDS    candidates, RATE:ORDER:LIMIT, comma-separated (default: the defaults at
                every rate, 64:6:0.51,128:6:0.51,256:6:0.51)
  DSDUP_BIN     the patched CLI (default target-dump/release/dsd-upsample)
  STAB_WORK     work folder (default target/stability)
  STAB_SECONDS  length of each stability signal (default 60)
  STAB_JOBS     parallel conversions (default 5)
  STAB_ONLY     only these signals, comma-separated
"""
import json
import os
import re
import subprocess
import sys
import threading

import numpy as np
from scipy import signal as sg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "measure"))
import analyse  # noqa: E402
import decode  # noqa: E402
import dsdio  # noqa: E402
import signals  # noqa: E402

ROOT = os.path.join(HERE, "..", "..")
BIN = os.environ.get("DSDUP_BIN", os.path.join(ROOT, "target-dump", "release", "dsd-upsample"))
WORK = os.environ.get("STAB_WORK", os.path.join(ROOT, "target", "stability"))
SECONDS = float(os.environ.get("STAB_SECONDS", "60"))
OUT_FS = 352800
SACD0_POWER = 0.5 ** 2 / 2  # a sine at 0 dB SACD (50 % modulation)



def parse_cands(text):
    """RATE:ORDER:LIMIT entries -> (rate, order, limit) tuples."""
    out = []
    for x in text.split(","):
        f = x.split(":")
        if len(f) != 3:
            raise SystemExit(f"bad candidate {x!r}: RATE:ORDER:LIMIT")
        out.append((int(f[0]), int(f[1]), float(f[2])))
    return out


CANDS = parse_cands(os.environ.get("STAB_CANDS", "64:6:0.51,128:6:0.51,256:6:0.51"))


def cname(c):
    return f"dsd{c[0]}-o{c[1]}-l{c[2]:g}"


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
    """Returns (fs, x) for a signal id; full scale = 1.0 (legal: |x| <= 1)."""
    base = name
    fs = 352800 if base.endswith("_352") else 88200
    n = int(SECONDS * fs)
    t = np.arange(n) / fs
    rng = np.random.default_rng(sum(map(ord, base)) * 7919)
    m = re.match(r"csine(\d)_(\d+)k", base)
    if m:
        k, f = int(m.group(1)), 1000.0 * int(m.group(2))
        return fs, np.clip(k * np.sin(2 * np.pi * f * t), -1, 1)
    m = re.match(r"dc([+-][\d.]+)", base)
    if m:
        return fs, np.full(n, float(m.group(1)))
    m = re.match(r"(white|pink)_(-?\d+)", base)
    if m:
        x = rng.uniform(-1, 1, n) if m.group(1) == "white" else pink(n, rng)
        x = x / np.max(np.abs(x))
        return fs, x * 10 ** (int(m.group(2)) / 20)
    if base.startswith("rand_pm1"):
        return fs, np.where(rng.random(n) < 0.5, -1.0, 1.0)
    m = re.match(r"sq_(\w+?)_(88|352)", base)
    if m:
        s = m.group(1)
        f = {"fs4": fs / 4, "fs2": fs / 2}.get(s) or 1000.0 * int(s[:-1])
        return fs, square(fs, f, n)
    if base.startswith("sine20k"):
        return fs, np.sin(2 * np.pi * 20000.0 * t)
    if base.startswith("step"):
        # full-scale steps: +1 for 0.5 s, -1 for 0.5 s (1 Hz square)
        return fs, np.where((np.arange(n) // (fs // 2)) % 2 == 0, 1.0, -1.0)
    if base.startswith("imp"):
        x = np.zeros(n)
        x[::int(fs // 100)] = 1.0  # single-sample full-scale impulses, 100 per second
        return fs, x
    raise ValueError(name)


LEGAL = ["csine2_1k", "csine2_5k", "csine2_10k", "csine4_1k", "csine4_5k", "csine4_10k",
         "dc+0.5", "dc+0.75", "dc+1.0", "dc-1.0",
         "white_0", "white_-3", "pink_0", "pink_-3", "rand_pm1_88", "rand_pm1_352",
         "sq_1k_88", "sq_10k_88", "sq_fs4_88", "sq_fs2_88",
         "sq_1k_352", "sq_10k_352", "sq_fs4_352", "sq_fs2_352",
         "sine20k_352", "step_88", "step_352", "imp_88", "imp_352"]
HOT = ["csine4_1k", "csine4_10k", "dc+1.0", "white_0", "pink_0", "rand_pm1_352",
       "sq_10k_88", "sq_fs4_352", "sq_fs2_352", "sine20k_352"]
SIGS = [(s, False) for s in LEGAL] + [(s, True) for s in HOT]


def sig_path(name):
    p = os.path.join(WORK, "signals", f"{name}.wav")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fs, x = make(name)
        tmp = f"{p}.{os.getpid()}.tmp"
        dsdio.write_wav(tmp, x, fs, "f64")
        os.replace(tmp, p)
    return p


class FloatDecoder:
    """decode.decode_bits for a float stream fed in pieces (same filter, same blocking)."""

    def __init__(self, rate):
        self.h, self.r = decode.design(rate, OUT_FS)
        taps = len(self.h)
        self.hist = -(-(taps - 1) // self.r) * self.r
        self.prev = np.zeros(self.hist)
        self.pend = np.zeros(0)
        self.out = []

    def push(self, x):
        x = np.concatenate([self.pend, x]) if len(self.pend) else x
        n = len(x) // self.r * self.r
        self.pend = x[n:]
        x = x[:n]
        if not n:
            return
        cat = np.concatenate([self.prev, x])
        z = sg.upfirdn(self.h, cat, down=self.r)
        m0 = self.hist // self.r
        self.out.append(z[m0:m0 + n // self.r])
        self.prev = cat[-self.hist:]

    def result(self):
        y = np.concatenate(self.out)
        return y[(len(self.h) - 1) // 2 // self.r:]


def excess_dec(y, z, window_s=0.01, band_hz=20000.0):
    """analyse.excess after decoding (same band limit, fit and windows), plus absolute
    levels re a 0 dB SACD sine."""
    n = min(len(y), len(z))
    y, z = y[:n], z[:n]
    out_fs = OUT_FS
    hb = sg.firwin(2001, band_hz, fs=out_fs, window=("kaiser", 14.0))
    hp = sg.firwin(2001, 20.0, fs=out_fs, window=("kaiser", 14.0), pass_zero=False)
    bl = lambda v: sg.fftconvolve(sg.fftconvolve(v, hb, mode="same"), hp, mode="same")  # noqa
    yb, s = bl(y), bl(z)
    k = 4000
    yb, s = yb[k:-k], s[k:-k]
    ds = np.gradient(s)
    A = np.stack([s, ds], axis=1)
    (ga, de), *_ = np.linalg.lstsq(A, yb, rcond=None)
    e = yb - ga * s - de * ds
    w = int(window_s * out_fs)
    m = len(e) // w
    ew = np.sum(e[:m * w].reshape(m, w) ** 2, axis=1)
    sw = np.sum(s[:m * w].reshape(m, w) ** 2, axis=1)
    i = int(np.argmax(ew / np.maximum(sw, 1e-300)))
    j = int(np.argmax(ew))
    db = analyse.db
    return {"excess_db": db(np.sum(e ** 2) / np.sum(s ** 2)),
            "excess_worst_window_db": db(ew[i] / sw[i]),
            "excess_sacd_db": db(np.mean(e ** 2) / SACD0_POWER),
            "excess_worst_window_sacd_db": db(ew[j] / w / SACD0_POWER),
            "worst_window_at_s": (j * w + k) / out_fs,
            "signal_inband_sacd_db": db(np.mean(s ** 2) / SACD0_POWER),
            "fit_gain_db": float(20 * np.log10(abs(ga)))}


def convert(src, dst, cand, gain=None, dump=None, extra=()):
    rate, order, lim = cand
    cmd = [BIN, src, dst, "--rate", str(rate), "--order", str(order), "--limit", str(lim),
           "--single-thread", *extra]
    # the study's gain: -3 dB, the default when it was made (the default is now -6 dB)
    cmd += ["--gain", str(-3.0 if gain is None else gain)]
    env = dict(os.environ)
    if dump:
        env["DSDUP_DUMP_U"] = dump
    return subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            text=True, env=env)


def counters(stderr):
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", stderr)
    if not k:
        return {"limited": 0, "clipped": 0, "resets": 0}
    return dict(zip(("limited", "clipped", "resets"), map(int, k[0])))


def task_stab(name, hot, cand):
    tag = f"{'hot_' if hot else ''}{name}"
    res = os.path.join(WORK, "results", cname(cand), f"{tag}.json")
    if os.path.exists(res):
        return res
    os.makedirs(os.path.dirname(res), exist_ok=True)
    src = sig_path(name)
    tmpd = os.path.join(WORK, "tmp", f"{cname(cand)}-{tag}")
    os.makedirs(tmpd, exist_ok=True)
    fifo = os.path.join(tmpd, "u.fifo")
    dst = os.path.join(tmpd, "out.dsf")
    if os.path.exists(fifo):
        os.remove(fifo)
    os.mkfifo(fifo)
    rate = 44100 * cand[0]
    lim = cand[2]
    p = convert(src, dst, cand, gain=3.0 if hot else None, dump=fifo)
    err = {}

    def watch():
        err["stderr"] = p.stderr.read()
        p.wait()
        if not opened.is_set():  # unblock our open() if the CLI never opened the fifo
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                os.close(fd)
            except OSError:
                pass

    opened = threading.Event()
    th = threading.Thread(target=watch)
    th.start()
    dec = FloatDecoder(rate)
    peak = 0.0
    with open(fifo, "rb", buffering=0) as fh:
        opened.set()
        pend = b""
        while True:
            b = fh.read(1 << 23)
            if not b:
                break
            b = pend + b
            n = len(b) // 8 * 8
            pend = b[n:]
            u = np.frombuffer(b[:n], dtype="<f8")
            peak = max(peak, float(np.max(np.abs(u))) if len(u) else 0.0)
            dec.push(np.clip(u, -lim, lim))
    th.join()
    if p.returncode:
        raise RuntimeError(f"{tag} {cname(cand)}: {err.get('stderr', '')[-500:]}")
    z = dec.result()
    bits, r = dsdio.read_dsd(dst, 0)
    y = decode.decode_bits(bits, r, OUT_FS)
    del bits
    out = {"signal": name, "hot": hot, "cand": cname(cand), "seconds": SECONDS,
           "counters": counters(err["stderr"]), "mod_input_peak": peak,
           "mod_input_peak_sacd_db": 20 * np.log10(max(peak, 1e-30) / 0.5)}
    out.update(excess_dec(y, z))
    for f in (dst, fifo):
        os.remove(f)
    os.rmdir(tmpd)
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return res


def task_tone(cand, level_sacd):
    """1 kHz tone at level_sacd dB SACD after the study's -3 dB gain: PCM level
    = level_sacd + 3.01 dBFS (f64 WAV, may exceed full scale)."""
    tag = f"tone1k{level_sacd:+.0f}"
    res = os.path.join(WORK, "results", cname(cand), f"{tag}.json")
    if os.path.exists(res):
        return res
    os.makedirs(os.path.dirname(res), exist_ok=True)
    sid = f"tone1k_{level_sacd:+.0f}"
    p = os.path.join(WORK, "signals", f"{sid}.wav")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        a_db = level_sacd + 3.0  # x * 0.5 * 10**(-3/20) = 0.5 * 10**(L/20)
        x = signals.make("sine", 88200, level=a_db, freq=1000.0, steady=10.0)
        tmp = f"{p}.{os.getpid()}.tmp"
        dsdio.write_wav(tmp, x, 88200, "f64")
        os.replace(tmp, p)
    tmpd = os.path.join(WORK, "tmp", f"{cname(cand)}-{tag}")
    os.makedirs(tmpd, exist_ok=True)
    dst = os.path.join(tmpd, "out.dsf")
    pr = convert(p, dst, cand)
    _, se = pr.communicate()
    if pr.returncode:
        raise RuntimeError(se[-500:])
    bits, r = dsdio.read_dsd(dst, 0)
    y = decode.decode_bits(bits, r, OUT_FS)
    yy = y[int(5.5 * OUT_FS):len(y) - int(0.1 * OUT_FS)]
    out = {"cand": cname(cand), "level_sacd": level_sacd, "counters": counters(se),
           "tone": analyse.tone(yy, OUT_FS, signals.coherent(1000.0))}
    os.remove(dst)
    os.rmdir(tmpd)
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return res


IMD = {"ccif_88": dict(sig="ccif", f1=19000.0, f2=20000.0),
       "ccif_352": dict(sig="ccif", f1=19000.0, f2=20000.0),
       "smpte_88": dict(sig="smpte"), "multitone_88": dict(sig="multitone")}


def task_imd(cand, sid):
    """HF-rich legal content at a 0 dB SACD PEAK after the study's -3 dB gain (PCM peak
    +3.0 dBFS, f64 WAV): limited/clipped counts and IMD."""
    res = os.path.join(WORK, "results", cname(cand), f"imd_{sid}.json")
    if os.path.exists(res):
        return res
    os.makedirs(os.path.dirname(res), exist_ok=True)
    fs = 352800 if sid.endswith("_352") else 88200
    p = os.path.join(WORK, "signals", f"imd_{sid}.wav")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        x = signals.make(level=3.0, fs=fs, steady=10.0, **IMD[sid])
        tmp = f"{p}.{os.getpid()}.tmp"
        dsdio.write_wav(tmp, x, fs, "f64")
        os.replace(tmp, p)
    tmpd = os.path.join(WORK, "tmp", f"{cname(cand)}-imd{sid}")
    os.makedirs(tmpd, exist_ok=True)
    dst = os.path.join(tmpd, "out.dsf")
    pr = convert(p, dst, cand)
    _, se = pr.communicate()
    if pr.returncode:
        raise RuntimeError(se[-500:])
    bits, r = dsdio.read_dsd(dst, 0)
    y = decode.decode_bits(bits, r, OUT_FS)
    yy = y[int(5.5 * OUT_FS):len(y) - int(0.1 * OUT_FS)]
    kind = IMD[sid]["sig"]
    if kind == "ccif":
        a = analyse.ccif(yy, OUT_FS, 19000.0, 20000.0)
    elif kind == "smpte":
        a = analyse.smpte(yy, OUT_FS)
    else:
        a = analyse.multitone(yy, OUT_FS)
    out = {"cand": cname(cand), "signal": sid, "counters": counters(se), "analysis": a}
    os.remove(dst)
    os.rmdir(tmpd)
    with open(res + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(res + ".tmp", res)
    return res


def run_task(t):
    try:
        if t[0] == "stab":
            return task_stab(*t[1:])
        if t[0] == "imd":
            return task_imd(*t[1:])
        return task_tone(*t[1:])
    except Exception as e:  # noqa
        return f"FAIL {t}: {e}"


def main():
    from multiprocessing import Pool
    jobs = int(os.environ.get("STAB_JOBS", "5"))
    only = os.environ.get("STAB_ONLY")
    tasks = []
    for c in CANDS:
        for lv in (-3.0, 0.0):
            tasks.append(("tone", c, lv))
    for c in CANDS:
        for sid in IMD:
            tasks.append(("imd", c, sid))
    for name, hot in SIGS:
        if only and name not in only.split(","):
            continue
        for c in CANDS:
            tasks.append(("stab", name, hot, c))
    # quick tone and IMD tasks first, then the 60 s runs in the order of STAB_CANDS
    pri = {c: i for i, c in enumerate(CANDS)}
    tasks.sort(key=lambda t: (t[0] == "stab", pri[t[-1] if t[0] == "stab" else t[1]]))
    for name, _ in SIGS:
        sig_path(name)
    with Pool(jobs) as pool:
        for r in pool.imap_unordered(run_task, tasks):
            print(r, flush=True)


if __name__ == "__main__":
    main()
