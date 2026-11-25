# SPDX-License-Identifier: MIT OR Apache-2.0
"""FFT analysers for decoded DSD or PCM test files: numbers in, JSON out.

Levels are dBFS re a full-scale sine (a sine of peak amplitude 1.0 reads 0 dBFS; for DSD,
100 % modulation is 1.0, so 0 dB SACD is -6.02 dBFS). Power spectra are one-sided and
normalised so that the bins of one spectral line sum to the line's power (A^2 / 2); noise
densities are divided by the window's effective noise bandwidth (dBFS/Hz).

Windows: 7-term Blackman-Harris (H.-H. Albrecht, ICASSP 2001; sidelobes below -180 dB)
for spectra, rectangular for the coherent multitone. Averages are power averages of
segments spread evenly over the analysed part (overlapping if the file is short).

Analysers (``--test``), each returning a dict:
  tone        THD (harmonics 2-9 up to 20 kHz), THD+N and SINAD (notch: 20 Hz-20 kHz minus
              the fundamental), unweighted and A-weighted; 2^18 points, 1 average
  dr          dynamic range, -60 dB method (AES17): 60 + tone level - residual level, both
              in dB re the stated reference; 2^18 points, 1 average
  noise       noise floor: 20 Hz-20 kHz unweighted and A-weighted, 20-40 kHz, then 48 kHz
              bands; density at 1 and 20 kHz; 2^20 points, 8 averages
  ultrasonic  20 kHz bands to the Nyquist frequency, 22-96, 20-100 and 100-192 kHz totals,
              the peak of the density smoothed over 1 kHz (hump level and frequency);
              2^20 points, 8 averages
  jtest       carrier at fs_in/4, sidebands at +-odd multiples of fs_in/192: the largest
              relative to the carrier and the count above -130 dBFS; 2^20 points, 8 averages
  multitone   32-tone distortion-free range: lowest tone minus the highest in-between bin
              (20 Hz-20 kHz), 25 kHz linear-phase low-pass first, rectangular window,
              2^20 points, 8 averages (and 1)
  smpte       sidebands 7 kHz +- n x 60 Hz (n = 1-4) relative to 7 kHz; IMD+N
  ccif        products f2-f1, 2(f2-f1), 3(f2-f1), 2f1-f2, 2f2-f1 relative to the sum of the
              two tones; IMD+N

    python tools/measure/analyse.py FILE --test tone --freq 1000 [--skip 5.5] [--fs 352800]

FILE is a DSF or DFF (decoded first with decode.py at --fs) or a PCM WAV (analysed at its
own rate; FFT sizes scale with the rate so the bin width stays fs/2^18 of 352.8 kHz).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decode  # noqa: E402
import dsdio  # noqa: E402

REF_FS = 352800
FS_POWER = 0.5  # power of a full-scale sine
BH7 = [0.27105140069342, 0.43329793923448, 0.21812299954311, 0.06592544638803,
       0.01081174209837, 0.00077658482522, 0.00001388721735]
LOBE = 10  # bins either side summed for a spectral line (BH7 main lobe is +-7)
HERE = os.path.dirname(os.path.abspath(__file__))


def db(p):
    return 10 * np.log10(max(float(p), 1e-300))


def window(kind, n):
    if kind == "rect":
        return np.ones(n)
    k = np.arange(n)
    w = np.zeros(n)
    for i, a in enumerate(BH7):
        w += ((-1) ** i) * a * np.cos(2 * np.pi * i * k / n)
    return w


def points(fs, n_ref):
    """FFT length at fs with the same bin width as n_ref points at 352.8 kHz."""
    n = int(round(n_ref * fs / REF_FS))
    if n & (n - 1):
        raise ValueError(f"{fs} Hz gives a non power-of-two FFT length {n}")
    return n


def spectrum(y, fs, n, avgs=1, kind="bh7"):
    """Averaged one-sided power spectrum. Returns (p, f, enbw_hz)."""
    if len(y) < n:
        raise ValueError(f"need {n} samples, have {len(y)}")
    w = window(kind, n)
    if avgs == 1:
        starts = [0]
    else:
        starts = np.linspace(0, len(y) - n, avgs).astype(int)
    p = np.zeros(n // 2 + 1)
    for s in starts:
        X = np.fft.rfft(y[s:s + n] * w)
        p += np.abs(X) ** 2
    p *= 2.0 / (len(starts) * n * np.sum(w ** 2))
    p[0] /= 2
    f = np.fft.rfftfreq(n, 1 / fs)
    enbw = fs * np.sum(w ** 2) / np.sum(w) ** 2
    return p, f, enbw


def amplitude_db(p, n, kind="bh7"):
    """Convert a power spectrum to the usual FFT-plot view, dBFS per bin, where a coherent
    sine of peak amplitude A shows its peak bin at 20 log10 A."""
    w = window(kind, n)
    k = 2 * n * np.sum(w ** 2) / np.sum(w) ** 2
    return 10 * np.log10(np.maximum(p * k, 1e-300))


def a_weight(f):
    """IEC 61672 A-weighting as a power factor."""
    f2 = np.asarray(f, dtype=np.float64) ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2)
                                     * (f2 + 737.9 ** 2)) * (f2 + 12194.0 ** 2))
    with np.errstate(divide="ignore"):
        g = 20 * np.log10(np.maximum(ra, 1e-300)) + 2.00
    return 10 ** (g / 10)


def line_mask(f, f0, df):
    c = int(round(f0 / df))
    m = np.zeros(len(f), bool)
    m[max(0, c - LOBE):c + LOBE + 1] = True
    return m


def line_power(p, f, f0):
    df = f[1] - f[0]
    return float(np.sum(p[line_mask(f, f0, df)]))


def band(f, lo, hi):
    return (f >= lo) & (f < hi)


def tone(y, fs, f0):
    """1 kHz-style single-tone analysis (footprint test 8)."""
    n = points(fs, 1 << 18)
    p, f, _ = spectrum(y, fs, n)
    df = f[1] - f[0]
    fund = line_mask(f, f0, df)
    sig = float(np.sum(p[fund]))
    harm = []
    hmask = np.zeros(len(f), bool)
    for h in range(2, 10):
        if h * f0 > 20000:
            break
        m = line_mask(f, h * f0, df)
        hmask |= m
        harm.append((h, float(np.sum(p[m]))))
    thd = sum(v for _, v in harm)
    inb = band(f, 20, 20000)
    resid = np.sum(p[inb & ~fund])
    aw = a_weight(f)
    resid_a = np.sum((p * aw)[inb & ~fund])
    noise = np.sum(p[inb & ~fund & ~hmask])
    worst = max(harm, key=lambda t: t[1]) if harm else (0, 0.0)
    thdn = db(resid / sig)
    return {"level_dbfs": db(sig / FS_POWER), "thd_db": db(thd / sig),
            "thd_pct": 100 * np.sqrt(thd / sig), "thdn_db": thdn,
            "thdn_pct": 100 * np.sqrt(resid / sig), "thdn_a_db": db(resid_a / sig),
            "sinad_db": -thdn, "noise_dbfs": db(noise / FS_POWER),
            "worst_harmonic": worst[0], "worst_harmonic_db": db(worst[1] / sig) if harm else None,
            "fft_points": n, "averages": 1, "window": "bh7", "fs": fs}


def dr(y, fs, f0, ref_dbfs=0.0):
    """Dynamic range, -60 dB method. ref_dbfs is the 0 dB reference in dBFS
    (-6.02 for 0 dB SACD): the result is 60 + (tone - residual) with the tone 60 dB down."""
    n = points(fs, 1 << 18)
    p, f, _ = spectrum(y, fs, n)
    df = f[1] - f[0]
    fund = line_mask(f, f0, df)
    inb = band(f, 20, 20000)
    sig = float(np.sum(p[fund]))
    r = float(np.sum(p[inb & ~fund]))
    ra = float(np.sum((p * a_weight(f))[inb & ~fund]))
    tone_db = db(sig / FS_POWER) - ref_dbfs
    return {"tone_db": tone_db, "residual_dbfs": db(r / FS_POWER),
            "residual_a_dbfs": db(ra / FS_POWER),
            "dr_db": 60 + tone_db - (db(r / FS_POWER) - ref_dbfs),
            "dr_a_db": 60 + tone_db - (db(ra / FS_POWER) - ref_dbfs),
            "reference_dbfs": ref_dbfs, "fft_points": n, "averages": 1, "fs": fs}


def noise(y, fs):
    """Noise floor of an idle (silence) output (footprint test 6)."""
    n = points(fs, 1 << 20)
    p, f, enbw = spectrum(y, fs, n, 8)
    ny = fs / 2
    out = {"fft_points": n, "averages": 8, "window": "bh7", "fs": fs}
    out["n20_20k_dbfs"] = db(np.sum(p[band(f, 20, 20000)]) / FS_POWER)
    out["n20_20k_a_dbfs"] = db(np.sum((p * a_weight(f))[band(f, 20, 20000)]) / FS_POWER)
    edges = [20000, 40000] + list(range(88000, int(ny) + 48000, 48000))
    bands = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        hi = min(hi, ny)
        if lo >= hi:
            break
        bands.append({"lo_hz": lo, "hi_hz": hi, "dbfs": db(np.sum(p[band(f, lo, hi)]) / FS_POWER)})
    out["bands"] = bands
    for fc in (1000, 20000):
        m = band(f, fc - 50, fc + 50)
        out[f"density_{fc // 1000}k_dbfs_hz"] = db(np.mean(p[m]) / enbw / FS_POWER)
    return out


def ultrasonic(y, fs):
    """Ultrasonic noise (footprint test 19)."""
    n = points(fs, 1 << 20)
    p, f, enbw = spectrum(y, fs, n, 8)
    ny = fs / 2
    dens = p / enbw / FS_POWER
    k = max(1, int(round(1000 / (f[1] - f[0]))))
    c = np.concatenate([[0.0], np.cumsum(dens)])
    lo = np.clip(np.arange(len(dens)) - k // 2, 0, len(dens))
    hi = np.clip(lo + k, 0, len(dens))
    sm = (c[hi] - c[lo]) / (hi - lo)
    m = band(f, 20000, ny - 1000)
    i = np.flatnonzero(m)[np.argmax(sm[m])]
    m2 = band(f, 20000, min(192000, ny - 1000))
    i2 = np.flatnonzero(m2)[np.argmax(sm[m2])]
    out = {"fft_points": n, "averages": 8, "window": "bh7", "fs": fs,
           "peak_hz": float(f[i]), "peak_dbfs_hz": db(sm[i]),
           "peak192_hz": float(f[i2]), "peak192_dbfs_hz": db(sm[i2]),
           "u22_96_dbfs": db(np.sum(p[band(f, 22000, 96000)]) / FS_POWER),
           "u20_100_dbfs": db(np.sum(p[band(f, 20000, 100000)]) / FS_POWER),
           "u100_192_dbfs": db(np.sum(p[band(f, 100000, min(192000, ny))]) / FS_POWER)
           if ny > 100000 else None,
           "n20_20k_dbfs": db(np.sum(p[band(f, 20, 20000)]) / FS_POWER)}
    out["bands20k"] = [{"lo_hz": lo, "dbfs": db(np.sum(p[band(f, lo, lo + 20000)]) / FS_POWER)}
                       for lo in range(20000, int(ny) - 19999, 20000)]
    return out


def jtest(y, fs, fs_in):
    """J-Test (footprint test 12): file-level, arithmetic only."""
    n = points(fs, 1 << 20)
    p, f, _ = spectrum(y, fs, n, 8)
    fc = fs_in / 4
    fj = fs_in / 192
    car = line_power(p, f, fc)
    sides = []
    k = 1
    while k * fj < 2000:
        for s in (-1, 1):
            fr = fc + s * k * fj
            sides.append((fr, line_power(p, f, fr)))
        k += 2
    big = max(sides, key=lambda t: t[1])
    return {"carrier_dbfs": db(car / FS_POWER), "largest_sideband_hz": big[0],
            "largest_sideband_dbc": db(big[1] / car),
            "sidebands_above_m130": sum(1 for _, v in sides if db(v / FS_POWER) > -130),
            "noise_9_13k_dbfs": db(np.sum(p[band(f, 9000, 13000)
                                          & ~line_mask(f, fc, f[1] - f[0])]) / FS_POWER),
            "fft_points": n, "averages": 8, "window": "bh7", "fs": fs}


def multitone(y, fs, table=None):
    """32-tone distortion-free range (footprint test 11)."""
    if table is None:
        with open(os.path.join(HERE, "multitone32.json")) as fh:
            table = json.load(fh)
    n = points(fs, table["fft_points"])
    bins = np.round(np.array(table["freqs_hz"]) / (fs / n)).astype(int)
    # Rectangular-window sidelobes would spread a DSD stream's ultrasonic noise over every
    # bin, so the signal is first low-passed at 25 kHz (linear phase, Kaiser beta 16,
    # stopband below -160 dB from 26 kHz); the tones (up to 21.4 kHz) pass unchanged.
    from scipy import signal as sg
    h = sg.firwin(int(fs / 88.2) | 1, 25000.0, fs=fs, window=("kaiser", 16.0))
    y = sg.oaconvolve(y, h, mode="same")[len(h):-len(h)]
    out = {"fft_points": n, "window": "rect", "prefilter_hz": 25000, "fs": fs}
    for avgs in (8, 1):
        p, f, _ = spectrum(y, fs, n, avgs, "rect")
        tone_db = np.array([db(p[b] / FS_POWER) for b in bins])
        inb = band(f, 20, 20000)
        tonem = np.zeros(len(f), bool)
        tonem[bins] = True
        res = p[inb & ~tonem]
        top = db(np.max(res) / FS_POWER)
        # residual per tone gap: mean of the bins between neighbouring tones
        gaps = []
        for a, b in zip(bins[:-1], bins[1:]):
            seg = p[a + 1:b]
            gaps.append(db(np.mean(seg) / FS_POWER))
        key = f"avg{avgs}"
        out[key] = {"dfr_db": float(np.min(tone_db) - top), "highest_residual_dbfs": top,
                    "lowest_tone_dbfs": float(np.min(tone_db)),
                    "mean_residual_dbfs": db(np.mean(res) / FS_POWER),
                    "tdn_db": db(np.sum(res) / np.sum(p[bins])),
                    "gap_residual_dbfs": gaps}
    out["dfr_db"] = out["avg8"]["dfr_db"]
    out["averages"] = 8
    return out


def smpte(y, fs, f1=None, f2=None):
    """SMPTE IMD, 60 Hz + 7 kHz 4:1 (footprint test 10)."""
    n = points(fs, 1 << 18)
    p, f, _ = spectrum(y, fs, n)
    df = f[1] - f[0]
    g = REF_FS / (1 << 18)
    lo = round((f1 or 60.0) / g) * g
    hi = round((f2 or 7000.0) / g) * g
    ref = line_power(p, f, hi)
    sb = sum(line_power(p, f, hi + s * k * lo) for k in range(1, 5) for s in (-1, 1))
    tm = line_mask(f, lo, df) | line_mask(f, hi, df)
    inb = band(f, 20, 20000)
    tonep = line_power(p, f, lo) + ref
    return {"imd_db": db(sb / ref), "imd_pct": 100 * np.sqrt(sb / ref),
            "imdn_db": db(np.sum(p[inb & ~tm]) / tonep), "fft_points": n, "averages": 1,
            "fs": fs}


def ccif(y, fs, f1=19000.0, f2=20000.0):
    """CCIF two-tone IMD (footprint test 10)."""
    n = points(fs, 1 << 18)
    p, f, _ = spectrum(y, fs, n)
    df = f[1] - f[0]
    g = REF_FS / (1 << 18)
    f1, f2 = round(f1 / g) * g, round(f2 / g) * g
    d = f2 - f1
    tonep = line_power(p, f, f1) + line_power(p, f, f2)
    prods = {"d2": [d], "d2b": [2 * d], "d3b": [3 * d], "d3": [2 * f1 - f2, 2 * f2 - f1]}
    out = {k: db(sum(line_power(p, f, v) for v in fr) / tonep) for k, fr in prods.items()}
    tot = sum(line_power(p, f, v) for fr in prods.values() for v in fr)
    tm = line_mask(f, f1, df) | line_mask(f, f2, df)
    out.update({"imd_db": db(tot / tonep), "imd_pct": 100 * np.sqrt(tot / tonep),
                "imdn_db": db(np.sum(p[band(f, 20, 20000) & ~tm]) / tonep),
                "f1_hz": f1, "f2_hz": f2, "fft_points": n, "averages": 1, "fs": fs})
    return out


def true_peak(y, fs, oversample=4):
    """Peak magnitude after 4x band-limited oversampling (dBFS re 1.0 and the sample index)."""
    from scipy import signal as sg
    z = sg.resample_poly(y, oversample, 1, window=("kaiser", 10.0))
    i = int(np.argmax(np.abs(z)))
    return {"true_peak_dbfs": 20 * np.log10(max(abs(z[i]), 1e-300)),
            "at_s": i / (fs * oversample), "sample_peak_dbfs": 20 * np.log10(max(np.max(np.abs(y)), 1e-300))}


def compare(a, b, fs, block_s=0.05, band_hz=20000.0, edge_s=0.5):
    """Error of `a` against the reference `b` (same timing and scale), both low-passed to
    band_hz, the first and last edge_s seconds left out: overall error re signal (dB), and per block the error level (dBFS) and the
    error relative to the reference block (dB); the worst blocks are listed."""
    from scipy import signal as sg
    h = sg.firwin(1001, band_hz, fs=fs, window=("kaiser", 12.0))
    n = min(len(a), len(b))
    a = sg.oaconvolve(a[:n], h, mode="same")
    b = sg.oaconvolve(b[:n], h, mode="same")
    k = int(edge_s * fs)  # decoder start-up and flush are not compared
    a, b = a[k:n - k], b[k:n - k]
    n = len(a)
    e = a - b
    blk = int(block_s * fs)
    m = n // blk
    eb = np.sum(e[:m * blk].reshape(m, blk) ** 2, axis=1) / blk
    sb = np.sum(b[:m * blk].reshape(m, blk) ** 2, axis=1) / blk
    ed = 10 * np.log10(np.maximum(eb, 1e-300) / FS_POWER)
    rel = 10 * np.log10(np.maximum(eb, 1e-300) / np.maximum(sb, 1e-300))
    worst = np.argsort(ed)[::-1][:5]
    return {"error_re_signal_db": db(np.sum(e ** 2) / np.sum(b ** 2)),
            "error_dbfs": db(np.mean(e ** 2) / FS_POWER),
            "block_error_dbfs_median": float(np.median(ed)),
            "block_error_dbfs_max": float(np.max(ed)),
            "block_error_rel_db_max": float(np.max(rel)),
            "worst_blocks": [{"at_s": float(i * block_s), "error_dbfs": float(ed[i]),
                              "rel_db": float(rel[i])} for i in worst],
            "blocks_over_m100dbfs": int(np.count_nonzero(ed > -100)),
            "block_error_dbfs": [round(float(v), 2) for v in ed],
            "block_rel_db": [round(float(v), 2) for v in rel],
            "block_s": block_s, "band_hz": band_hz}


def excess(bits, rate, ideal, out_fs=352800, band_hz=20000.0, window_s=0.01):
    """Error of a DSD stream against an ideal float signal at the same (DSD) rate and time
    base: both go through the same reference decoder and a 20 Hz-20 kHz band limit, and
    the error is given relative to the ideal signal's power, overall and for the worst
    window (dB). Used to measure what a modulator adds beyond, for example, the
    distortion of an ideal limiter (ideal = the clipped input)."""
    from scipy import signal as sg
    h, r = decode.design(rate, out_fs)
    y = decode.decode_bits(bits, rate, out_fs)
    z = sg.upfirdn(h, ideal, down=r)[(len(h) - 1) // 2 // r:][:len(y)]
    y = y[:len(z)]
    hb = sg.firwin(2001, band_hz, fs=out_fs, window=("kaiser", 14.0))
    hp = sg.firwin(2001, 20.0, fs=out_fs, window=("kaiser", 14.0), pass_zero=False)
    bl = lambda v: sg.fftconvolve(sg.fftconvolve(v, hb, mode="same"), hp, mode="same")  # noqa: E731
    yb, s = bl(y), bl(z)
    k = 4000  # filter edges
    yb, s = yb[k:-k], s[k:-k]
    # remove a constant gain and sub-sample delay difference (least squares on s and ds/dt)
    ds = np.gradient(s)
    A = np.stack([s, ds], axis=1)
    (ga, de), *_ = np.linalg.lstsq(A, yb, rcond=None)
    e = yb - ga * s - de * ds
    w = int(window_s * out_fs)
    m = len(e) // w
    ew = np.sum(e[:m * w].reshape(m, w) ** 2, axis=1)
    sw = np.sum(s[:m * w].reshape(m, w) ** 2, axis=1)
    i = int(np.argmax(ew / np.maximum(sw, 1e-300)))
    return {"excess_db": db(np.sum(e ** 2) / np.sum(s ** 2)),
            "excess_worst_window_db": db(ew[i] / sw[i]), "window_s": window_s,
            "excess_dbfs": db(np.mean(e ** 2) / FS_POWER),
            "fit_gain_db": 20 * np.log10(abs(ga)), "fit_delay_ns": float(de / ga / out_fs * 1e9)}


def load(path, fs=REF_FS, channel=0):
    """Samples and rate of a file: DSD is decoded at fs, WAV is read as is."""
    with open(path, "rb") as fh:
        magic = fh.read(4)
    if magic in (b"DSD ", b"FRM8"):
        y, rate, _ = decode.decode_file(path, fs, channel)
        return y, rate
    x, rate = dsdio.read_wav(path)
    return x[:, channel], rate


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--test", required=True,
                    choices=["tone", "dr", "noise", "ultrasonic", "jtest", "multitone",
                             "smpte", "ccif"])
    ap.add_argument("--freq", type=float, default=1000.0)
    ap.add_argument("--f1", type=float, default=19000.0)
    ap.add_argument("--f2", type=float, default=20000.0)
    ap.add_argument("--fs", type=int, default=REF_FS, help="decode rate for DSD input")
    ap.add_argument("--fs-in", type=int, default=44100, help="J-Test source rate")
    ap.add_argument("--ref", type=float, default=-20 * np.log10(2), help="0 dB reference, dBFS")
    ap.add_argument("--skip", type=float, default=5.5, help="seconds discarded at the start")
    ap.add_argument("--channel", type=int, default=0)
    a = ap.parse_args()
    y, fs = load(a.file, a.fs, a.channel)
    y = y[int(a.skip * fs):len(y) - int(0.1 * fs)]
    sig = {"tone": lambda: tone(y, fs, a.freq), "dr": lambda: dr(y, fs, a.freq, a.ref),
           "noise": lambda: noise(y, fs), "ultrasonic": lambda: ultrasonic(y, fs),
           "jtest": lambda: jtest(y, fs, a.fs_in), "multitone": lambda: multitone(y, fs),
           "smpte": lambda: smpte(y, fs), "ccif": lambda: ccif(y, fs, a.f1, a.f2)}
    print(json.dumps(sig[a.test](), indent=1))


if __name__ == "__main__":
    main()
