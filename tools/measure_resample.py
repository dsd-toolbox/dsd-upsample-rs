#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Measurements of the 48 kHz-family resampler for docs/measurements.md and
docs/resampler-design.md: the same test signals from a 48 kHz-family source and from its
44.1 kHz-family partner, converted by the CLI and decoded with the reference decoder of
tools/measure/.

    python tools/measure_resample.py --bin target/release/dsd-upsample --work DIR [--jobs 4]

Prints Markdown tables. Conventions:
- Sources are mono f64 WAV (no quantisation), 3 s silence, 2 s ramp, then the steady part
  (tools/measure/signals.py); the analysis skips the first 5.5 s.
- The CLI runs at its defaults except --gain +6.0206 dB, so 0 dBFS in the WAV is 100 %
  modulation, and a level of -6.02 dBFS is 0 dB SACD. Tables give levels in dB re 0 dB
  SACD (named "dB SACD") unless they say dBFS.
- SINAD: 1 kHz tone, 20 Hz-20 kHz (tools/measure/analyse.py `tone`).
- Flatness: the 32-tone multitone of tools/measure (17.6 Hz to 21.4 kHz) at 0 dB SACD
  composite peak; each tone's level out minus its level in. The 17.5 and 21.5 Hz tones are
  left out (12 bins apart, their line sums overlap), so the band is 28.3 Hz to 17.0 kHz
  plus the 21.4 kHz tone in the transition band.
- Edges: single tones (exact-phase sines) near and beyond the band edges of each 48 kHz-family
  rate; the tone's level out (attenuation), the output's level at that frequency with
  digital silence in (the floor); for stopband tones, the level at the frequency the tone
  would alias to (the new rate minus the tone, between 20 kHz and the new Nyquist
  frequency, never in the audio band) against the silence floor there; and the in-band
  (20 Hz-20 kHz) residual, against the residual of digital silence and of negligible
  non-zero inputs.
- IMD: CCIF 19 + 20 kHz and SMPTE 60 Hz + 7 kHz 4:1, composite peak 0 dB SACD.
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "measure"))
import analyse  # noqa: E402
import dsdio  # noqa: E402
import signals  # noqa: E402

SACD0 = signals.SACD0  # -6.02 dBFS
GAIN = "6.0206"
STEADY = 4.0
SKIP = 5.5
PAIRS = ((48000, 44100), (96000, 88200), (192000, 176400), (384000, 352800))
RATES = (64, 128, 256)


def src(work, name, fs, **kw):
    path = os.path.join(work, f"{name}-{fs}.wav")
    if not os.path.exists(path):
        kw = {k: v for k, v in kw.items() if k != "floor_at"}
        if kw["sig"] == "noise":
            # Gaussian noise of the given rms level (dB SACD), fixed seed
            n = len(signals.make("silence", fs, steady=STEADY))
            rms = 0.5 / np.sqrt(2) * 10 ** (kw["level"] / 20)
            x = rms * np.random.default_rng(1).standard_normal(n)
        elif kw["sig"] == "xsine":
            # exact phase: (f n) mod fs in integers, so the argument stays below 2 pi. With
            # t = n / fs the rounding of 2 pi f t adds in-band spurs of about -220 dB SACD
            # to a 23 kHz tone after 9 s, which a removed tone would otherwise leave behind.
            # The frequency is the analysis bin centre signals.coherent() gives,
            # q x 352800 / 2^20 Hz, so the phase is (q x 352800 x n) mod (fs x 2^20).
            q = int(round(kw["freq"] / (signals.ANALYSIS_FS / (1 << 20))))
            m = fs * (1 << 20)
            n0, nr = int(signals.SILENCE * fs), int(signals.RAMP * fs)
            k = np.arange(nr + int(STEADY * fs), dtype=np.int64)
            ph = ((q * signals.ANALYSIS_FS) % m) * k % m
            x = 10 ** (kw["level"] / 20) * np.sin(2 * np.pi * (ph / m))
            x[:nr] *= np.arange(nr) / nr
            x = np.concatenate([np.zeros(n0), x])
        else:
            x = signals.make(fs=fs, steady=STEADY, **kw)
        dsdio.write_wav(path + ".tmp", x[:, None], fs, "f64")
        os.replace(path + ".tmp", path)
    return path


def convert(binary, wav, mult):
    out = wav[:-4] + f"-dsd{mult}.dsf"
    if not os.path.exists(out):
        r = subprocess.run([binary, wav, out + ".tmp.dsf", "--rate", str(mult), "--gain", GAIN,
                            "--single-thread"], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        os.replace(out + ".tmp.dsf", out)
    return out


def alias_of(f, fs):
    """Where a tone at f (Hz) in a source at fs lands after the 147/160 rate change if the
    filter let it through: mirrored about the new rate's Nyquist frequency. None for tones
    in the passband or transition band (they are not aliased)."""
    partner = fs * 147 // 160
    return partner - f if partner / 2 < f < fs / 2 else None


def decoded(path):
    y, fs = analyse.load(path)
    return y[int(SKIP * fs):], fs


def job(args):
    """One conversion and its analyses; returns (key, result dict)."""
    binary, work, kind, name, fs, mult, kw = args
    key = f"{kind}:{name}:{fs}:{mult}"
    cache = os.path.join(work, key.replace(":", "_") + ".json")
    if os.path.exists(cache):
        with open(cache) as fh:
            return key, json.load(fh)
    wav = src(work, name, fs, **kw)
    dsf = convert(binary, wav, mult)
    y, rate = decoded(dsf)
    res = {}
    if kind == "tone":
        res = analyse.tone(y, rate, signals.coherent(kw.get("freq", 1000.0)))
    elif kind == "ccif":
        res = analyse.ccif(y, rate)
    elif kind == "smpte":
        res = analyse.smpte(y, rate)
    elif kind == "flat":
        t = signals.multitone_table()
        n = analyse.points(rate, 1 << 20)
        p, f, _ = analyse.spectrum(y, rate, n, 8)
        a_in = 10 ** (SACD0 / 20) * t["unit_peak_amplitude"]
        # tones whose line masks overlap a neighbour's (17.5 and 21.5 Hz, 12 bins apart)
        # leak into each other; they are left out
        fr = np.array(t["freqs_hz"])
        gap = np.diff(fr) / (f[1] - f[0])
        clear = np.ones(len(fr), bool)
        clear[:-1] &= gap > 2 * analyse.LOBE + 1
        clear[1:] &= gap > 2 * analyse.LOBE + 1
        res = {"freqs": [float(v) for v in fr[clear]],
               "gain_db": [10 * np.log10(analyse.line_power(p, f, v) / (a_in ** 2 / 2))
                           for v in fr[clear]]}
    elif kind == "edge":
        n = analyse.points(rate, 1 << 20)
        p, f, _ = analyse.spectrum(y, rate, n, 8)
        fr = kw.get("freq")
        out = {}
        # the output's own level at the given frequencies (the floor a removed tone is
        # measured against), dB re 0 dB SACD
        out["floor_db_sacd"] = {str(v): 10 * np.log10(analyse.line_power(p, f, signals.coherent(v))
                                                      / 0.125)
                                for v in kw.get("floor_at", ())}
        # ... and at the frequency each of them would alias to
        out["floor_alias_db_sacd"] = {
            str(v): 10 * np.log10(analyse.line_power(p, f, alias_of(signals.coherent(v), fs))
                                  / 0.125)
            for v in kw.get("floor_at", ()) if alias_of(signals.coherent(v), fs)}
        if fr and alias_of(signals.coherent(fr), fs):
            al = alias_of(signals.coherent(fr), fs)
            out["alias_hz"] = al
            out["alias_db_sacd"] = 10 * np.log10(analyse.line_power(p, f, al) / 0.125 + 1e-300)
        if fr:
            fr = signals.coherent(fr)
            a_in = 10 ** (SACD0 / 20)  # gains are re a 0 dB SACD tone
            out["tone_gain_db"] = 10 * np.log10(analyse.line_power(p, f, fr) / (a_in ** 2 / 2)
                                                + 1e-300)
            keep = ~analyse.line_mask(f, fr, f[1] - f[0])
        else:
            keep = np.ones(len(f), bool)
        inb = analyse.band(f, 20, 20000) & keep
        # dB re 0 dB SACD (power of a sine of amplitude 0.5)
        out["inband_db_sacd"] = 10 * np.log10(np.sum(p[inb]) / 0.125)
        res = out
    for k in ("bins",):
        res.pop(k, None)
    with open(cache, "w") as fh:
        json.dump(res, fh)
    os.remove(dsf)
    return key, res


def jobs(binary, work):
    out = []
    for hi, lo in PAIRS:
        for fs in (hi, lo):
            for mult in RATES:
                for lv in (0, -3):
                    out.append((binary, work, "tone", f"sine{lv}", fs, mult,
                                dict(sig="sine", level=SACD0 + lv)))
                out.append((binary, work, "ccif", "ccif", fs, mult,
                            dict(sig="ccif", level=SACD0)))
                out.append((binary, work, "smpte", "smpte", fs, mult,
                            dict(sig="smpte", level=SACD0)))
            out.append((binary, work, "flat", "mt", fs, 128,
                        dict(sig="multitone", level=SACD0)))
    # edges, at DSD256 (lowest modulator noise): tones near and past each rate's band edge
    edge = {48000: (19990, 21000, 22000, 22100, 23000, 23990),
            96000: (19990, 39990, 42000, 44000, 44200, 47990),
            192000: (19990, 79990, 84000, 88000, 88300, 95990)}
    for fs, freqs in edge.items():
        out.append((binary, work, "edge", "silence", fs, 256,
                    dict(sig="silence", floor_at=freqs)))
        # a second floor: digital silence lets the modulator settle into patterns that can
        # sit below its noise with any real input, so white noise at -260 dB SACD too
        out.append((binary, work, "edge", "noise260", fs, 256,
                    dict(sig="noise", level=-260.0, floor_at=freqs)))
        for fr in freqs:
            out.append((binary, work, "edge", f"tone{fr}", fs, 256,
                        dict(sig="xsine", level=SACD0, freq=float(fr))))
    # controls: what a negligible but non-zero input does to the modulator by itself (a
    # 1 kHz tone at -215 dB SACD, white noise at -260 dB SACD), against digital silence,
    # from both families
    for fs in (48000, 44100):
        out.append((binary, work, "edge", "tiny1000", fs, 256,
                    dict(sig="sine", level=SACD0 - 215, freq=1000.0)))
        if fs == 44100:
            out.append((binary, work, "edge", "noise260", fs, 256,
                        dict(sig="noise", level=-260.0)))
    out.append((binary, work, "edge", "silence", 44100, 256, dict(sig="silence")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    js = jobs(os.path.abspath(a.bin), a.work)
    # sources first (serially: the jobs share them)
    for j in js:
        src(a.work, j[3], j[4], **j[6])
    with ProcessPoolExecutor(a.jobs) as ex:
        res = dict(ex.map(job, js))
    with open(os.path.join(a.work, "all.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    report(res)


def report(res):
    print("### SINAD, 1 kHz (dB; level in dB SACD, output rate per column)\n")
    print("| Source | Level | DSD64 | DSD128 | DSD256 |")
    print("|---|---|---|---|---|")
    for hi, lo in PAIRS:
        for lv in (0, -3):
            for fs in (hi, lo):
                v = [res[f"tone:sine{lv}:{fs}:{m}"]["sinad_db"] for m in RATES]
                print(f"| {fs / 1000:g} kHz | {lv} | " + " | ".join(f"{x:.1f}" for x in v) + " |")
            d = [res[f"tone:sine{lv}:{hi}:{m}"]["sinad_db"] - res[f"tone:sine{lv}:{lo}:{m}"]["sinad_db"]
                 for m in RATES]
            print(f"| difference | {lv} | " + " | ".join(f"{x:+.1f}" for x in d) + " |")
    print("\n### IMD at 0 dB SACD composite peak (dB re the tones)\n")
    print("| Source | Output | CCIF IMD | CCIF IMD+N | SMPTE IMD | SMPTE IMD+N |")
    print("|---|---|---|---|---|---|")
    for hi, lo in PAIRS:
        for fs in (hi, lo):
            for m in RATES:
                c, s = res[f"ccif:ccif:{fs}:{m}"], res[f"smpte:smpte:{fs}:{m}"]
                print(f"| {fs / 1000:g} kHz | DSD{m} | {c['imd_db']:.1f} | {c['imdn_db']:.1f} | "
                      f"{s['imd_db']:.1f} | {s['imdn_db']:.1f} |")
    print("\n### Flatness, 32-tone multitone to DSD128 (tone level out minus in, dB)\n")
    print("| Source | Tones 28.3 Hz-17.0 kHz, min / max | 21.4 kHz tone | Largest difference to the other family, tones to 17.0 kHz |")
    print("|---|---|---|---|")
    for hi, lo in PAIRS:
        for fs in (hi, lo):
            r = res[f"flat:mt:{fs}:128"]
            f, g = np.array(r["freqs"]), np.array(r["gain_db"])
            inb = f <= 20000
            other = np.array(res[f"flat:mt:{lo if fs == hi else hi}:128"]["gain_db"])
            print(f"| {fs / 1000:g} kHz | {g[inb].min():+.2e} / {g[inb].max():+.2e} | "
                  f"{g[~inb][-1]:+.2f} | {np.abs(g[inb] - other[inb]).max():.1e} |")
    print("\n### Band edges, tone at 0 dB SACD to DSD256\n")
    print("| Source | Tone (Hz) | Tone level out (dB re in) | Same frequency, silence in (dB SACD) | "
          "Alias frequency (Hz) | Level there (dB SACD) | Same frequency, silence in (dB SACD) | "
          "Same frequency, noise at -260 dB SACD in (dB SACD) | "
          "In-band residual 20 Hz-20 kHz, tone excluded (dB SACD) |")
    print("|---|---|---|---|---|---|---|---|---|")
    keys = [k for k in res if k.startswith("edge:")]
    def order(k):
        _, name, fs, _ = k.split(":")
        v = float(name[4:]) if name.startswith("tone") else (-1 if name == "silence" else 0)
        return (-int(fs) if int(fs) % 48000 else 0, int(fs), v)
    for k in sorted(keys, key=order):
        _, name, fs, _ = k.split(":")
        r = res[k]
        if name.startswith("tone"):
            tone = name[4:]
            tg = f"{r['tone_gain_db']:.1f}"
            fl = res[f"edge:silence:{fs}:256"]["floor_db_sacd"].get(str(int(tone)))
            fl = f"{fl:.1f}" if fl is not None else "-"
            if "alias_hz" in r:
                af = f"{r['alias_hz']:.0f}"
                al = f"{r['alias_db_sacd']:.1f}"
                afl = res[f"edge:silence:{fs}:256"]["floor_alias_db_sacd"].get(str(int(tone)))
                afl = f"{afl:.1f}" if afl is not None else "-"
                anl = res[f"edge:noise260:{fs}:256"]["floor_alias_db_sacd"].get(str(int(tone)))
                anl = f"{anl:.1f}" if anl is not None else "-"
            else:
                af = al = afl = anl = "-"
        else:
            tone = {"silence": "silence", "tiny1000": "1000 at -215 dB SACD",
                    "noise260": "white noise at -260 dB SACD"}[name]
            tg = fl = af = al = afl = anl = "-"
        print(f"| {int(fs) / 1000:g} kHz | {tone} | {tg} | {fl} | {af} | {al} | {afl} | {anl} | "
              f"{r['inband_db_sacd']:.1f} |")


if __name__ == "__main__":
    main()
