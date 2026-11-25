#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""SINAD and ultrasonic noise of candidates of the acceptance gate (gate.py), through the
command-line tool. One JSON line per candidate.

    python tools/stability/gate_metrics.py OUT.jsonl --work DIR 128:6:default 256:8:default ...

Conditions: 1 kHz tone, 64-bit float WAV at 88.2 kHz converted with --gain 6.0206 (WAV
full scale = 100 % modulation). SINAD at -3 and 0 dB SACD from 20 Hz to 20 kHz (reference
decoder of tools/measure, 2^18-point FFT at 352.8 kHz). Noise from 22 to 96 kHz and from
100 to 192 kHz with the tone at -60 dB SACD, in dBFS with 100 % modulation = 0 dBFS.

The cost of the default gain, for the same source converted at the default (-6 dB) and at
--gain -3 (the default of earlier builds): SINAD of a 1 kHz tone at 0 dBFS (64-bit float
WAV at 88.2 kHz, so the tone reaches the modulator at -6 or -3 dB SACD), and, for DSD128
and DSD256, of a 1 kHz DSD64 tone at 0 dB SACD from `dsd-upsample gen`. The limited,
clipped and reset counts of each run are recorded with it.
Candidates are rate:order:limit as in gate.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "measure"))
import analyse  # noqa: E402
import decode  # noqa: E402
import dsdio  # noqa: E402
import signals  # noqa: E402


def wav(work, level, steady):
    p = os.path.join(work, f"tone{level:+.2f}.wav")
    if not os.path.exists(p):
        x = signals.make("sine", 88200, level=level, freq=1000.0, steady=steady)
        dsdio.write_wav(p, x, 88200, "f64")
    return p


def conv(binary, work, src, c, gain="6.0206"):
    """Converts with --gain `gain` (None: the default gain)."""
    dst = os.path.join(work, f"out-{os.getpid()}.dsf")
    cmd = [binary, src, dst, "--rate", c[0], "--order", c[1], "--single-thread"]
    if gain is not None:
        cmd += ["--gain", gain]
    if c[2] != "default":
        cmd += ["--limit", c[2]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    k = re.findall(r"limited (\d+) clipped (\d+) resets (\d+)", r.stderr)[0]
    bits, fs = dsdio.read_dsd(dst, 0)
    os.remove(dst)
    return bits, fs, dict(zip(("limited", "clipped", "resets"), map(int, k)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("cands", nargs="+")
    ap.add_argument("--work", required=True)
    ap.add_argument("--bin", default=os.path.join(HERE, "..", "..", "target", "release", "dsd-upsample"))
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    with open(a.out, "a") as fo:
        for spec in a.cands:
            c = spec.split(":")
            out = {"cand": spec}
            for lv in (-3.0, 0.0):
                bits, fs, k = conv(a.bin, a.work, wav(a.work, signals.SACD0 + lv, 4.0), c)
                y = decode.decode_bits(bits, fs, 352800)[int(5.5 * 352800):-35280]
                t = analyse.tone(y, 352800, signals.coherent(1000.0))
                out[f"sinad{lv:+.0f}"] = t["sinad_db"]
                out[f"counters{lv:+.0f}"] = k
            bits, fs, k = conv(a.bin, a.work, wav(a.work, signals.SACD0 - 60, 6.0), c)
            hi = 705600 if int(c[0]) <= 128 else 1411200
            u = analyse.ultrasonic(decode.decode_bits(bits, fs, hi)[int(5.5 * hi):], hi)
            out.update(u22_96=u["u22_96_dbfs"], u100_192=u["u100_192_dbfs"], counters_60=k)
            # the same source at the default gain and at --gain -3
            srcs = [("pcm", wav(a.work, 0.0, 4.0))]
            if c[0] != "64":
                d = os.path.join(a.work, "dsd64-1k-0.dsf")
                if not os.path.exists(d):
                    subprocess.run([a.bin, "gen", d, "--rate", "64", "--freq", "1000", "--level", "0",
                                    "--seconds", "8"], check=True, capture_output=True)
                srcs.append(("dsd64", d))
            for kind, src in srcs:
                for name, gain in (("default", None), ("m3", "-3")):
                    bits, fs, k = conv(a.bin, a.work, src, c, gain)
                    y = decode.decode_bits(bits, fs, 352800)[int(5.5 * 352800):-35280]
                    t = analyse.tone(y, 352800, signals.coherent(1000.0))
                    out[f"sinad_{kind}_{name}"] = t["sinad_db"]
                    out[f"counters_{kind}_{name}"] = k
            fo.write(json.dumps(out) + "\n")
            fo.flush()
            print(f"{spec}: SINAD {out['sinad-3']:.1f} / {out['sinad+0']:.1f} dB, 22-96 kHz "
                  f"{out['u22_96']:.1f} dBFS, 100-192 kHz {out['u100_192']:.1f} dBFS; 0 dBFS PCM at "
                  f"the default gain / --gain -3: {out['sinad_pcm_default']:.1f} / "
                  f"{out['sinad_pcm_m3']:.1f} dB", flush=True)


if __name__ == "__main__":
    main()
