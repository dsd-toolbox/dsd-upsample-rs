# SPDX-License-Identifier: MIT OR Apache-2.0
"""State scaling for the audio-band modulator tables: the largest value of every
integrator state over a set of bounded inputs at the default input limit, as a power of
two. gen_tables.py divides each state by 2**exp, so the scaled states stay within +-0.75
in normal operation and the library's state clip (1.5) is only reached by a diverging
loop. Powers of two keep the scaled recurrence bit-identical to the unscaled one.

    python tools/modulator/scale.py tools/modulator/state_scale.json [--secs 60] [--jobs 8]
"""
import argparse
import json
import math
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as D  # noqa: E402
import hold  # noqa: E402
import sim  # noqa: E402

LEVEL = 0.51
TARGET = 0.75
SKIP = ("rand4",)  # beyond the bandwidth the interpolators can deliver; see the study


def one(job):
    rate, order, secs = job
    d = D.audio_design(rate, order)
    xmax = [0.0] * order
    used = []
    for name, kind, f in hold.SIGNALS:
        if name in SKIP:
            continue
        s = sim.new(d)
        noise = kind in ("rand", "noise")
        ff = f * (rate // 64) if noise else f / (sim.BASE * rate)
        sim.gen(s, sim.KINDS[kind], LEVEL, ff, 0.0, int(secs * sim.BASE * rate))
        if s.blowups:
            continue
        used.append(name)
        xmax = [max(a, float(b)) for a, b in zip(xmax, s.xmax[:order])]
    exp = [int(math.ceil(math.log2(v / TARGET))) for v in xmax]
    return f"{rate}:{order}", dict(hinf=D.AUDIO_HINF[(rate, order)], level=LEVEL, secs=secs,
                                   signals=used, xmax=xmax, exp=exp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--secs", type=float, default=60.0)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    jobs = [(r, o, a.secs) for (r, o) in sorted(D.AUDIO_HINF)]
    with Pool(a.jobs) as pool:
        res = dict(pool.map(one, jobs))
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    main()
