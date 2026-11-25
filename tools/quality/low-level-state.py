#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Does the noise under a low-level tone depend on how the tone starts? DR(A) in sliding windows.

    low-level-state.py CLI IN_RATE MULT GAIN_DB [LEVEL_DB_SACD ...]   (with the Python of dsd-measure)

Prints one line per (level, start): the DR(A) of each 0.743 s window, every 1 s, over 12 s,
measured as dsd-measure 0.1.2 measures it (its decoder and analyser; level-corrected to its
convention). DR = 60 + noise re a -60 dB SACD tone, for any tone level.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

from dsd_measure import analyse as an
from dsd_measure import decode as dec
from dsd_measure import signals as sg
from dsd_measure.dsf import read_dsf
from dsd_measure.levels import REF_DBFS
from dsd_measure.measure import REF_FS, REF_NFFT, nfft_for
from dsd_measure.wavio import write_wav

CLI, R, MULT, GAIN = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
LEVELS = [float(v) for v in sys.argv[5:]] or [-60.0]
G = 10 ** ((6.0206 - GAIN) / 20)
f0 = sg.coherent_freq(1000, REF_FS, REF_NFFT)
T = 12.0


def starts(L):
    lv = REF_DBFS + L
    n = int(T * R)
    t = np.arange(n) / R
    a = 10 ** (lv / 20)
    ramp = np.minimum(1.0, t / 0.5)
    pre = sg.sine(f0, lv + 6, R, int(1.5 * R))
    return {
        "abrupt phase 0": a * np.sin(2 * np.pi * f0 * t),
        "abrupt phase 90": a * np.cos(2 * np.pi * f0 * t),
        "0.5 s ramp": a * ramp * np.sin(2 * np.pi * f0 * t),
        "after 1.5 s at +6 dB": np.concatenate([pre, a * np.sin(2 * np.pi * f0 * t[: n - len(pre)])]),
        "after 1 s silence": np.concatenate([np.zeros(R), a * np.sin(2 * np.pi * f0 * t[: n - R])]),
    }


tmp = tempfile.mkdtemp(prefix="regime-")
n = nfft_for(REF_FS)
try:
    for L in LEVELS:
        for name, x in starts(L).items():
            wav, dsf = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.dsf")
            write_wav(wav, x, R, "pcm32")
            subprocess.run([CLI, wav, dsf, "--rate", str(MULT), "--gain", f"{GAIN:g}"], check=True, capture_output=True)
            bits, rate = read_dsf(dsf)
            y = dec.decode(np.asarray(bits)[0], rate, REF_FS, passband=20000.0) * G
            drs = []
            for s in np.arange(1.0, T - 0.8, 1.0):
                w = y[int(s * REF_FS): int(s * REF_FS) + n]
                d = an.dynamic_range(w, REF_FS, f0, n)
                # DR re the -60 tone: noise re 0 dB SACD, the same for any tone level
                drs.append(d["dr_a_db"])
            print(f"{R} DSD{MULT} gain {GAIN:g} level {L:g} | {name:22s} | " + " ".join(f"{v:6.1f}" for v in drs), flush=True)
finally:
    subprocess.run(["rm", "-rf", tmp])
