# SPDX-License-Identifier: MIT OR Apache-2.0
"""Design-space sweep: order x H_inf x zero band per DSD rate. One JSON line per candidate.

    python tools/modulator/sweep.py OUT.jsonl [--rates 128,256] [--jobs 8]
"""
import argparse
import itertools
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as D  # noqa: E402
import sim  # noqa: E402

RAMPS = (("dc", 0.0), ("sine", 1000.0), ("sine", 20000.0), ("square", 1000.0), ("rand", 64))


def one(job):
    rate, order, hinf, band, secs = job
    d = D.design(rate, order, hinf, band)
    out = dict(rate=rate, order=order, hinf=hinf, band=band, l1norm=d["l1norm"])
    lim = {}
    for kind, f in RAMPS:
        lim[f"{kind}{f:g}"] = min(sim.ramp_limit(d, rate, kind, f, secs=secs, seed=sd)
                                  for sd in (1, 2))
    out["ramp"] = lim
    out["stable_to"] = min(lim.values())
    for lv in (-3.0, 0.0):
        if 0.5 * 10 ** (lv / 20) < out["stable_to"] - 0.02:
            t = sim.measure_tone(d, rate, lv)
            out[f"sinad{lv:+.0f}"] = t["sinad_db"] if not t["blowups"] else None
        else:
            out[f"sinad{lv:+.0f}"] = None
    out.update(sim.noise_floor(d, rate))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--rates", default="128,256")
    ap.add_argument("--orders", default="5,6,7,8")
    ap.add_argument("--hinf", default="1.2,1.25,1.3,1.35,1.4,1.45,1.5")
    ap.add_argument("--bands", default="20000,22050,24000,30000,40000")
    ap.add_argument("--secs", type=float, default=20.0)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    jobs = [(r, o, h, b, a.secs) for r, o, h, b in itertools.product(
        [int(x) for x in a.rates.split(",")], [int(x) for x in a.orders.split(",")],
        [float(x) for x in a.hinf.split(",")], [float(x) for x in a.bands.split(",")])]
    jobs.sort(key=lambda j: -j[0])
    with Pool(a.jobs) as pool, open(a.out, "a") as fh:
        for r in pool.imap_unordered(one, jobs):
            fh.write(json.dumps(r) + "\n")
            fh.flush()


if __name__ == "__main__":
    main()
