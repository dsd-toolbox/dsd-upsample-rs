#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""One build as a device for `dsd-measure null` (DSD file in, PCM WAV out).

    null-chain.py ROLE PATH IN.dsf OUT.wav [OPTION ...]

ROLE is `baseline` or `candidate`: the converter is $DSDUP_BASELINE_CLI or $DSDUP_CANDIDATE_CLI.
PATH names the conversion, as in suites/upconverter.toml; OPTIONs go to the converter:

- `pcm44100-dsd128` (any PCM rate, any DSD rate): IN, a DSD64 file, is decoded to 32-bit PCM at
  that rate by dsd-measure's reference decoder (48 kHz family: decoded at 88.2 kHz, then a
  80/147 polyphase resampler with a Kaiser window, beta 14). That PCM is the converter's input.
- `dsd64-dsd256`: IN itself is the converter's input.

The converter writes DSD at the rate named; the reference decoder turns it into 64-bit float
PCM at 352.8 kHz, low-passed at 24 kHz (LP_HZ), scaled by $DSDUP_BASELINE_LEVEL_DB or $DSDUP_CANDIDATE_LEVEL_DB (dB, default 0;
tools/quality/compare.py sets it to undo the gain the build applies, so two builds with different
default gains are compared at equal level), which `dsd-measure null` compares with the other build's. Everything except
the converter is the same for both builds, so the null measures the converters' difference.
Runs with the Python of the dsd-measure installation (it imports dsd_measure).
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import signal
from dsd_measure.decode import decode
from dsd_measure.dsf import read_dsf
from dsd_measure.wavio import write_wav

OUT_RATE = 352800
#: Low-pass applied to both builds' decoded output before the null test: linear phase, Kaiser beta
#: 14 (about 140 dB stopband), 2047 taps, -6 dB at 24 kHz, flat to 23 kHz. Without it the shaped
#: noise above the audio band (uncorrelated between two modulator runs, and at DSD64 and DSD128
#: louder than the audio band) dominates dsd-measure 0.1.2's full-band alignment, which then fails.
LP_HZ = 24000.0
LP_TAPS = 2047


def lowpass(y):
    h = signal.firwin(LP_TAPS, LP_HZ, fs=OUT_RATE, window=("kaiser", 14.0))
    return signal.fftconvolve(y, h[None, :], mode="same", axes=1)


def pcm_from_dsd(bits, rate, fs):
    if rate % fs == 0:
        return np.array([decode(c, rate, fs) for c in bits])
    y = np.array([decode(c, rate, 88200) for c in bits])
    g = np.gcd(88200, fs)
    return signal.resample_poly(y, fs // g, 88200 // g, axis=1, window=("kaiser", 14.0))


def main():
    if len(sys.argv) < 5:
        sys.exit("usage: null-chain.py baseline|candidate PATH IN.dsf OUT.wav [OPTION ...]")
    role, path, src, out = sys.argv[1:5]
    extra = sys.argv[5:]
    var = {"baseline": "DSDUP_BASELINE_CLI", "candidate": "DSDUP_CANDIDATE_CLI"}.get(role)
    if not var or not os.environ.get(var):
        sys.exit(f"null-chain.py: role must be baseline or candidate, with {var or 'its CLI variable'} set")
    cli = os.environ[var]
    level = float(os.environ.get(f"DSDUP_{role.upper()}_LEVEL_DB", "0"))
    m = re.fullmatch(r"(pcm(\d+)|dsd64)-dsd(64|128|256)", path)
    if not m:
        sys.exit(f"null-chain.py: unknown path {path!r}")
    with tempfile.TemporaryDirectory(prefix="null-chain-") as d:
        inp = src
        if m.group(2):
            bits, rate = read_dsf(src)
            fs = int(m.group(2))
            inp = str(Path(d) / "in.wav")
            write_wav(inp, pcm_from_dsd(bits.astype(np.float64), rate, fs), fs, "pcm32")
        dsd = Path(d) / "out.dsf"
        r = subprocess.run([cli, inp, str(dsd), "--rate", m.group(3), *extra], stdin=subprocess.DEVNULL)
        if r.returncode:
            sys.exit(r.returncode)
        bits, rate = read_dsf(dsd)
        y = lowpass(np.array([decode(c.astype(np.float64), rate, OUT_RATE) for c in bits])) * 10 ** (level / 20)
        write_wav(out, y, OUT_RATE, "float64")


if __name__ == "__main__":
    main()
