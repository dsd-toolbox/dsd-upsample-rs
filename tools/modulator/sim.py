# SPDX-License-Identifier: MIT OR Apache-2.0
"""Study driver: simulate candidate NTFs (dsm.c) and measure them with tools/measure.

The modulator is fed directly at the DSD rate (no interpolators), so these numbers are
the modulator alone; the final candidates are measured again through the whole CLI.
"""
import ctypes
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "measure"))
sys.path.insert(0, HERE)
import analyse  # noqa: E402
import decode  # noqa: E402
import design as D  # noqa: E402

BASE = 44100
INF = float("inf")


class Dsm(ctypes.Structure):
    _fields_ = [("n", ctypes.c_int), ("a", ctypes.c_double * 8), ("g", ctypes.c_double * 4),
                ("b", ctypes.c_double * 9), ("c", ctypes.c_double * 8),
                ("x", ctypes.c_double * 8), ("k", ctypes.c_double * 8), ("ff", ctypes.c_int),
                ("clip", ctypes.c_double * 8),
                ("blow", ctypes.c_double), ("xmax", ctypes.c_double * 8),
                ("ymax", ctypes.c_double), ("clipped", ctypes.c_int64),
                ("resets", ctypes.c_int64), ("blowups", ctypes.c_int64),
                ("limited", ctypes.c_int64), ("run", ctypes.c_int),
                ("reset_run", ctypes.c_int), ("limit", ctypes.c_double),
                ("rng", ctypes.c_uint64), ("phase", ctypes.c_double)]


def lib():
    so = os.path.join(os.environ.get("DSM_BUILD", HERE), "dsm.so")
    src = os.path.join(HERE, "dsm.c")
    if not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src):
        subprocess.check_call(["gcc", "-O2", "-ffp-contract=off", "-fno-fast-math", "-shared",
                               "-fPIC", "-o", so, src, "-lm"])
    L = ctypes.CDLL(so)
    L.dsm_run.argtypes = [ctypes.POINTER(Dsm), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    L.dsm_gen.argtypes = [ctypes.POINTER(Dsm), ctypes.c_int, ctypes.c_double, ctypes.c_double,
                          ctypes.c_double, ctypes.c_int64, ctypes.c_double]
    L.dsm_gen.restype = ctypes.c_int64
    return L


LIB = None


def new(d, clip=None, blow=None, limit=INF, reset_run=64, seed=1):
    """State for a design dict (a, g, b, c). Unscaled designs: blow defaults to 1e3."""
    s = Dsm()
    n = len(d["a"])
    s.n = n
    for i in range(n):
        s.a[i] = d["a"][i]
        s.c[i] = d["c"][i]
        s.clip[i] = INF if clip is None else (clip[i] if np.ndim(clip) else clip)
    for i in range(n // 2):
        s.g[i] = d["g"][i]
    for i in range(n + 1):
        s.b[i] = d["b"][i]
    if "k" in d:
        s.ff = 1
        for i in range(n):
            s.k[i] = d["k"][i]
    s.blow = (1e9 if "k" in d else 1e3) if blow is None else blow
    s.limit = limit
    s.reset_run = reset_run
    s.rng = seed
    return s


def run(s, u, want_bits=True):
    global LIB
    LIB = LIB or lib()
    u = np.ascontiguousarray(u, dtype=np.float64)
    bits = np.empty(len(u), np.uint8) if want_bits else None
    LIB.dsm_run(ctypes.byref(s), u.ctypes.data, bits.ctypes.data if want_bits else None, len(u))
    return bits


def gen(s, kind, amp, fn, aux, n, ramp0=-1.0):
    global LIB
    LIB = LIB or lib()
    return LIB.dsm_gen(ctypes.byref(s), kind, amp, fn, aux, int(n), ramp0)


def coherent(f0, n=1 << 18, fs=352800):
    return round(f0 * n / fs) * fs / n


def tone_bits(d, rate, amp, f0=1000.0, settle=0.3, **kw):
    """Bits for a coherent tone, after `settle` s; long enough for analyse.tone."""
    fs = BASE * rate
    r = fs // 352800
    n = int(settle * fs) // r * r + ((1 << 18) + 600) * r
    t = np.arange(n)
    u = amp * np.sin(2 * np.pi * coherent(f0) * t / fs)
    s = new(d, **kw)
    bits = run(s, u)
    return bits, s, int(settle * fs) // r * r


def measure_tone(d, rate, level_sacd_db, f0=1000.0, **kw):
    fs = BASE * rate
    amp = 0.5 * 10 ** (level_sacd_db / 20)
    bits, s, skip = tone_bits(d, rate, amp, f0, **kw)
    y = decode.decode_bits(bits, fs, 352800)[skip // (fs // 352800):]
    t = analyse.tone(y, 352800, coherent(f0))
    t["blowups"] = int(s.blowups)
    t["clipped"] = int(s.clipped)
    t["xmax"] = [float(v) for v in s.xmax[:s.n]]
    return t


def measure_noise(d, rate, amp=0.5e-3, f0=1000.0, **kw):
    """Idle/ultrasonic noise with a -60 dB SACD tone: (analyse.ultrasonic dict)."""
    fs = BASE * rate
    out_fs = 705600 if rate <= 128 else 1411200
    r = fs // out_fs
    npts = analyse.points(out_fs, 1 << 20)
    n = int(0.3 * fs) // r * r + (npts * 2 + 600) * r
    t = np.arange(n)
    u = amp * np.sin(2 * np.pi * coherent(f0) * t / fs)
    s = new(d, **kw)
    bits = run(s, u)
    y = decode.decode_bits(bits, fs, out_fs)[int(0.3 * fs) // r:]
    return analyse.ultrasonic(y, out_fs)


def stable_secs(d, rate, kind, amp, fn=0.0, aux=0.0, secs=5.0, **kw):
    """Run a built-in input; returns (blowups, ymax, xmax list)."""
    s = new(d, **kw)
    gen(s, kind, amp, fn, aux, int(secs * BASE * rate))
    return int(s.blowups), float(s.ymax), [float(v) for v in s.xmax[:s.n]], s


KINDS = {"dc": 0, "sine": 1, "square": 2, "noise": 3, "rand": 4, "sinedc": 5, "twotone": 6}


def ramp_limit(d, rate, kind="dc", f=0.0, aux=0.0, secs=20.0, lo=0.3, top=0.9, seed=1):
    """Amplitude at which a slow amplitude ramp (lo..top over secs) first blows up
    (top if it never does). f in Hz for sine/square/twotone, in samples for noise/rand."""
    fs = BASE * rate
    s = new(d, seed=seed)
    n = int(secs * fs)
    k = KINDS[kind]
    fn = f if k in (3, 4) else f / fs
    i = gen(s, k, top, fn, aux / fs if k == 6 else aux, n, lo / top)
    return lo + (top - lo) * i / n


def noise_floor(d, rate, **kw):
    """In-band noise (20 Hz-20 kHz, dBFS) with a -60 dB SACD 1 kHz tone, tone excluded,
    and the ultrasonic figures."""
    u = measure_noise(d, rate, **kw)
    t = measure_tone(d, rate, -60.0, **kw)
    return {"n20_20k_dbfs": t["noise_dbfs"], "u22_96_dbfs": u["u22_96_dbfs"],
            "u100_192_dbfs": u["u100_192_dbfs"], "peak192_hz": u["peak192_hz"],
            "peak192_dbfs_hz": u["peak192_dbfs_hz"]}
