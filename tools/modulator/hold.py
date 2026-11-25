# SPDX-License-Identifier: MIT OR Apache-2.0
"""Hold tests on the modulator alone: adversarial inputs bounded by a level, held for
`--secs` seconds each. Counts blow-ups (a state beyond 1000 in unscaled units) and records
the largest quantiser input and states. One JSON line per (candidate, level).

    python tools/modulator/hold.py OUT.jsonl --cands 128:8:1.4:20000,256:7:1.4:20000+90000
                                             --levels 0.5,0.52,0.55 [--secs 60] [--jobs 8]

A candidate is rate:order:H_inf:band[+f1+f2...]: Legendre zeros over 0..band; each +f
replaces one zero pair by a pair at f Hz.
"""
import argparse
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as D  # noqa: E402
import sim  # noqa: E402

# (name, kind, f): f in Hz, or in samples of hold for rand/noise (scaled with the rate so
# that the hold time is the same at every rate: given for DSD64)
SIGNALS = (("dc", "dc", 0.0), ("sine1k", "sine", 1000.0), ("sine10k", "sine", 10000.0),
           ("sine20k", "sine", 20000.0), ("sine50k", "sine", 50000.0),
           ("sq100", "square", 100.0), ("sq1k", "square", 1000.0), ("sq10k", "square", 10000.0),
           ("sq44k", "square", 44100.0), ("sq176k", "square", 176400.0),
           ("rand4", "rand", 4), ("rand16", "rand", 16), ("rand64", "rand", 64),
           ("rand1024", "rand", 1024), ("noise8", "noise", 8), ("noise64", "noise", 64))


def parse(spec):
    p = spec.split(":")
    rate, order, hinf = int(p[0]), int(p[1]), float(p[2])
    q = p[3].split("+")
    band, extra = float(q[0]), [float(x) for x in q[1:]]
    return rate, order, hinf, band, extra


def make(spec):
    rate, order, hinf, band, extra = parse(spec)
    deg = order - 2 * len(extra)
    freqs = D.legendre_zero_freqs(deg, band) + extra
    return rate, D.design(rate, order, hinf, freqs=freqs)


def one(job):
    spec, level, secs, seed = job
    rate, d = make(spec)
    out = dict(cand=spec, level=level, secs=secs, seed=seed, signals={})
    worst = 0
    for name, kind, f in SIGNALS:
        ff = f * (rate // 64) if kind in ("rand", "noise") else f
        s = sim.new(d, seed=seed)
        sim.gen(s, sim.KINDS[kind], level, ff if kind in ("rand", "noise") else ff / (sim.BASE * rate),
                0.0, int(secs * sim.BASE * rate))
        out["signals"][name] = dict(blowups=int(s.blowups), ymax=float(s.ymax),
                                    xmax=[float(v) for v in s.xmax[:s.n]])
        worst += int(s.blowups)
    out["blowups"] = worst
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cands", required=True)
    ap.add_argument("--levels", default="0.5,0.52,0.55")
    ap.add_argument("--secs", type=float, default=60.0)
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    jobs = [(c, float(lv), a.secs, int(sd)) for c in a.cands.split(",")
            for lv in a.levels.split(",") for sd in a.seeds.split(",")]
    with Pool(a.jobs) as pool, open(a.out, "a") as fh:
        for r in pool.imap_unordered(one, jobs):
            fh.write(json.dumps(r) + "\n")
            fh.flush()


if __name__ == "__main__":
    main()
