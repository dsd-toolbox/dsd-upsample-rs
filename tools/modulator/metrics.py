# SPDX-License-Identifier: MIT OR Apache-2.0
"""In-band and ultrasonic figures of candidates (modulator alone), one JSON line each.

    python tools/modulator/metrics.py OUT.jsonl --cands 256:7:1.35:20000+90000,... [--jobs 8]
"""
import argparse
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hold  # noqa: E402
import sim  # noqa: E402


def one(spec):
    rate, d = hold.make(spec)
    out = dict(cand=spec)
    for lv in (-3.0, 0.0):
        t = sim.measure_tone(d, rate, lv)
        out[f"sinad{lv:+.0f}"] = None if t["blowups"] else t["sinad_db"]
    out.update(sim.noise_floor(d, rate))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cands", required=True)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    with Pool(a.jobs) as pool, open(a.out, "a") as fh:
        for r in pool.imap_unordered(one, a.cands.split(",")):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            f = lambda v: "   -- " if v is None else "%6.1f" % v  # noqa: E731
            print("%-28s S-3 %s S0 %s n20k %s u22-96 %s u100-192 %s" % (
                r["cand"], f(r["sinad-3"]), f(r["sinad+0"]), f(r["n20_20k_dbfs"]),
                f(r["u22_96_dbfs"]), f(r["u100_192_dbfs"])), flush=True)


if __name__ == "__main__":
    main()
