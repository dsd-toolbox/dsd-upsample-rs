#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Measure a DSD file (DSF or DFF): level, SNR, THD+N at a test tone, band noise.

    python tools/measure.py FILE [--freq 1000] [--skip 0.2] [--seconds 2.9] [--channel 0]

Method: the 1-bit stream (+-1) is decimated to 352.8 kHz with a long Kaiser FIR
(reference filter, far longer than anything in the library), then analysed with one FFT
of 2^20 points and a 7-term Blackman-Harris window (sidelobes below -180 dB; H.-H.
Albrecht, "A family of cosine-sum windows for high-resolution measurements", ICASSP 2001).
Levels are in dB relative to 0 dB SACD (a sine of amplitude 0.5, i.e. 50 % modulation).

- noise figures exclude the fundamental and harmonics 2..10 (each +-10 bins);
- THD+N is everything from 20 Hz to 20 kHz except the fundamental, relative to it.
"""
import argparse
import struct
import sys

import numpy as np
from scipy import signal

PCM = 352800
REF = 10 * np.log10(0.5 ** 2 / 2)
BH7 = [0.27105140069342, 0.43329793923448, 0.21812299954311, 0.06592544638803,
       0.01081174209837, 0.00077658482522, 0.00001388721735]


def read_dsd(path, channel):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"DSD ":
        ch, rate, bits, samples, block = struct.unpack_from("<IIIQI", data, 52)
        lsb = bits == 1
        start = 92
        nblk = (len(data) - start) // (block * ch)
        raw = np.frombuffer(data, dtype=np.uint8, count=nblk * block * ch, offset=start)
        raw = raw.reshape(nblk, ch, block)[:, channel, :].reshape(-1)
        b = np.unpackbits(raw, bitorder="little" if lsb else "big")[:samples]
        return b, rate
    if data[:4] == b"FRM8":
        pos, rate, ch = 16, None, None
        while pos + 12 <= len(data):
            cid = data[pos:pos + 4]
            size = struct.unpack_from(">Q", data, pos + 4)[0]
            body = pos + 12
            if cid == b"PROP":
                p = body + 4
                while p < body + size:
                    sid = data[p:p + 4]
                    ss = struct.unpack_from(">Q", data, p + 4)[0]
                    if sid == b"FS  ":
                        rate = struct.unpack_from(">I", data, p + 12)[0]
                    if sid == b"CHNL":
                        ch = struct.unpack_from(">H", data, p + 12)[0]
                    p += 12 + ss + (ss & 1)
            if cid == b"DSD ":
                raw = np.frombuffer(data, dtype=np.uint8, count=size, offset=body)
                raw = raw[: len(raw) // ch * ch].reshape(-1, ch)[:, channel]
                return np.unpackbits(raw, bitorder="big"), rate
            pos = body + size + (size & 1)
    sys.exit("not a DSF or DFF file")


def decimate(bits, rate):
    x = bits.astype(np.float64) * 2.0 - 1.0
    r = rate // PCM
    # reference low-pass: 100 kHz cutoff, Kaiser beta 20 (stopband well below -180 dB)
    taps = 64 * r + 1
    h = signal.firwin(taps, 110000.0, fs=rate, window=("kaiser", 20.0))
    y = signal.upfirdn(h, x, down=r)
    d = (taps - 1) // 2 // r
    return y[d:]


def bands(y, f0, n):
    w = np.zeros(n)
    k = np.arange(n)
    for i, a in enumerate(BH7):
        w += ((-1) ** i) * a * np.cos(2 * np.pi * i * k / n)
    seg = y[:n] - np.mean(y[:n])
    X = np.fft.rfft(seg * w)
    p = 2 * np.abs(X) ** 2 / (n * np.sum(w ** 2))
    f = np.fft.rfftfreq(n, 1 / PCM)
    df = PCM / n
    lobe = 10

    def mask_tones(m, harmonics):
        m = m.copy()
        for h in range(1, harmonics + 1):
            c = int(round(h * f0 / df))
            m[max(0, c - lobe):c + lobe + 1] = False
        return m

    def band(lo, hi):
        return (f >= lo) & (f < hi)

    fund = np.zeros_like(f, dtype=bool)
    c = int(round(f0 / df))
    fund[c - lobe:c + lobe + 1] = True
    sig = np.sum(p[fund])
    out = {}
    out["level"] = 10 * np.log10(sig) - REF
    for lo, hi, name in ((20, 20000, "n20k"), (20000, 50000, "n50k"), (50000, 100000, "n100k")):
        m = mask_tones(band(lo, hi), 10)
        out[name] = 10 * np.log10(max(np.sum(p[m]), 1e-300)) - REF
    thdn = np.sum(p[band(20, 20000) & ~fund])
    out["thdn"] = 10 * np.log10(max(thdn, 1e-300) / sig)
    out["snr"] = out["level"] - out["n20k"]
    return out


def spectrum(y, n):
    """Power per bin (one-sided, sine of amplitude A gives A^2/2 summed over its lobe) and
    the bin frequencies, 7-term Blackman-Harris window."""
    w = np.zeros(n)
    k = np.arange(n)
    for i, a in enumerate(BH7):
        w += ((-1) ** i) * a * np.cos(2 * np.pi * i * k / n)
    seg = y[:n] - np.mean(y[:n])
    X = np.fft.rfft(seg * w)
    p = 2 * np.abs(X) ** 2 / (n * np.sum(w ** 2))
    return p, np.fft.rfftfreq(n, 1 / PCM)


def line(p, f, f0, lobe=10):
    """Level of a spectral line at f0 in dB SACD."""
    c = int(round(f0 / (f[1] - f[0])))
    return 10 * np.log10(max(np.sum(p[max(0, c - lobe):c + lobe + 1]), 1e-300)) - REF


def imd_ccif(y, n, f1=19000.0, f2=20000.0):
    """CCIF two-tone IMD: second-order product (f2 - f1) and third-order products
    (2 f1 - f2, 2 f2 - f1), each relative to the level of one tone, in dB."""
    p, f = spectrum(y, n)
    ref = line(p, f, f1)
    d2 = line(p, f, f2 - f1) - ref
    d3 = 10 * np.log10(10 ** ((line(p, f, 2 * f1 - f2) - ref) / 10)
                       + 10 ** ((line(p, f, 2 * f2 - f1) - ref) / 10))
    return {"tone": ref, "d2": d2, "d3": d3}


def idle(y, n):
    """Idle-tone check: the strongest spectral line in 20 Hz-20 kHz (summed over its
    window lobe, dB SACD) and the total noise there (dB SACD)."""
    p, f = spectrum(y, n)
    df = f[1] - f[0]
    band = (f >= 20) & (f < 20000)
    idx = np.flatnonzero(band)
    # strongest lobe: largest sum over +-10 bins
    cs = np.convolve(p, np.ones(21), mode="same")
    k = idx[np.argmax(cs[idx])]
    return {"spur": 10 * np.log10(max(cs[k], 1e-300)) - REF, "spur_hz": k * df,
            "n20k": 10 * np.log10(max(np.sum(p[band]), 1e-300)) - REF}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--freq", type=float, default=1000.0)
    ap.add_argument("--skip", type=float, default=0.2)
    ap.add_argument("--channel", type=int, default=0)
    a = ap.parse_args()
    bits, rate = read_dsd(a.file, a.channel)
    y = decimate(bits, rate)
    n = 1 << 20
    s = int(a.skip * PCM)
    if len(y) < s + n:
        sys.exit(f"need at least {(s + n) / PCM:.2f} s of audio")
    r = bands(y[s:], a.freq, n)
    print(f"{a.file}: DSD{rate // 44100}, tone {a.freq:.0f} Hz")
    print(f"  level      {r['level']:8.2f} dB SACD")
    print(f"  SNR 20k    {r['snr']:8.2f} dB (noise excl. harmonics)")
    print(f"  THD+N      {r['thdn']:8.2f} dB")
    print(f"  noise 20-20k   {r['n20k']:8.2f} dB SACD")
    print(f"  noise 20-50k   {r['n50k']:8.2f} dB SACD")
    print(f"  noise 50-100k  {r['n100k']:8.2f} dB SACD")


if __name__ == "__main__":
    main()
