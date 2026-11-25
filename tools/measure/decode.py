# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reference DSD decoder (Archimago's "perfect DAC" method): a 1-bit stream to PCM with a long linear-phase FIR.

The bits map to +-1 (100 % modulation = 1.0 = 0 dBFS, so 0 dB SACD reads -6.02 dBFS and
a PCM signal and its DSD encoding read the same level). One low-pass stage, decimating by
an integer factor straight from the DSD rate:

- Kaiser window, beta 20 (stopband below -190 dB), ``taps = 128 * factor + 1``;
- cutoff (-6 dB point) at 0.383 x the output rate: 135 kHz at 352.8 kHz output, 270 kHz
  at 705.6 kHz. Measured response: flat within 0.0001 dB to 0.33 x the output rate
  (116 kHz at 352.8 kHz, 233 kHz at 705.6 kHz), at most -189.8 dB from 0.44 x the output
  rate, so aliased noise can only land above 0.44 x the output rate (155 kHz at 352.8 kHz);
- 64-bit float arithmetic; the group delay is removed, so output sample 0 is input
  sample 0.

No other filter is applied. The decoder is independent of any modulator under test.

    python tools/measure/decode.py IN.dsf OUT.wav [--fs 352800] [--channel 0] [--fmt f32]
"""
import argparse
import os
import sys

import numpy as np
from scipy import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsdio  # noqa: E402

CUTOFF = 0.3827  # x output rate
BETA = 20.0
CHUNK = 1 << 24  # input samples per block


def design(rate, out_fs):
    if rate % out_fs:
        raise ValueError(f"{rate} Hz is not an integer multiple of {out_fs} Hz")
    r = rate // out_fs
    taps = 128 * r + 1
    h = signal.firwin(taps, CUTOFF * out_fs, fs=rate, window=("kaiser", BETA))
    return h, r


def decode_bits(bits, rate, out_fs=352800):
    """Decode a 0/1 bit array at `rate` to float64 PCM at out_fs (delay removed)."""
    h, r = design(rate, out_fs)
    taps = len(h)
    hist = -(-(taps - 1) // r) * r  # history length, a multiple of r
    n = len(bits) // r * r
    out = []
    prev = np.zeros(hist)  # before the file: the mean of an idle stream
    for a in range(0, n, CHUNK):
        b = min(n, a + CHUNK)
        x = bits[a:b].astype(np.float64) * 2.0 - 1.0
        z = signal.upfirdn(h, np.concatenate([prev, x]), down=r)
        m0 = hist // r
        out.append(z[m0:m0 + (b - a) // r])
        prev = np.concatenate([prev, x])[-hist:]
    y = np.concatenate(out)
    d = (taps - 1) // 2 // r
    return y[d:]


def decode_fast(bits, rate, out_fs=88200, chunk=1 << 24):
    """Fast audio-band decoder for long files (music), not for the -190 dB measurements.

    `bits` is a 0/1 array or an iterable of such arrays (see dsdio.iter_dsf).
    Stage 1: a 5th-order CIC (sinc^5) down to 705.6 kHz, integer arithmetic (aliasing into
    0-25 kHz below -150 dB, droop 0.06 dB at 20 kHz). Stage 2: Kaiser FIR (beta 12,
    1025 taps at 705.6 kHz, cutoff 28 kHz) to out_fs. Flat to about 25 kHz. Delay not
    removed: use it to compare outputs made by the same encoder pipeline."""
    mid = 705600
    if rate % mid or mid % out_fs:
        raise ValueError("rate must be a multiple of 705.6 kHz and out_fs divide it")
    r1 = rate // mid
    order = 5
    integ = np.zeros(order, np.int64)
    comb = np.zeros(order, np.int64)
    parts = []
    if isinstance(bits, np.ndarray):
        step = chunk // r1 * r1
        src = (bits[a:a + step] for a in range(0, len(bits) // r1 * r1, step))
    else:
        src = bits
    pend = np.zeros(0, np.uint8)
    for blk in src:
        blk = np.concatenate([pend, blk]) if len(pend) else blk
        n = len(blk) // r1 * r1
        pend = blk[n:]
        x = blk[:n].astype(np.int64) * 2 - 1
        if not n:
            continue
        for i in range(order):
            x = np.cumsum(x) + integ[i]
            integ[i] = x[-1]
        x = x[r1 - 1::r1]
        for i in range(order):
            prev = np.concatenate([[comb[i]], x[:-1]])
            comb[i] = x[-1]
            x = x - prev
        parts.append(x.astype(np.float64) / float(r1 ** order))
    y = np.concatenate(parts)
    r2 = mid // out_fs
    h = signal.firwin(128 * r2 + 1, 28000.0, fs=mid, window=("kaiser", 12.0))
    return signal.upfirdn(h, y, down=r2)

def decode_file(path, out_fs=352800, channel=0):
    """Return (pcm, out_fs, dsd_rate) for one channel of a DSF or DFF file."""
    bits, rate = dsdio.read_dsd(path, channel)
    return decode_bits(bits, rate, out_fs), out_fs, rate


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--fs", type=int, default=352800)
    ap.add_argument("--channel", type=int, default=0)
    ap.add_argument("--fmt", default="f32", choices=["f32", "f64"])
    a = ap.parse_args()
    y, fs, _ = decode_file(a.inp, a.fs, a.channel)
    dsdio.write_wav(a.out, y, fs, a.fmt)


if __name__ == "__main__":
    main()
