# SPDX-License-Identifier: MIT OR Apache-2.0
"""Counters only: every signal x candidate of stab.py, 60 s each, no decoding. Needs no
patched build (DSDUP_BIN may be the released CLI). Results: STAB_WORK/counts/."""
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stab  # noqa: E402

OUT = os.path.join(stab.WORK, "counts")


def one(t):
    name, hot, c = t
    tag = f"{'hot_' if hot else ''}{name}"
    res = os.path.join(OUT, stab.cname(c), tag + ".json")
    if os.path.exists(res):
        return res
    os.makedirs(os.path.dirname(res), exist_ok=True)
    dst = os.path.join(OUT, stab.cname(c), tag + ".dsf")
    p = stab.convert(stab.sig_path(name), dst, c, gain=3.0 if hot else None)
    _, se = p.communicate()
    if p.returncode:
        return f"FAIL {t} {se[-300:]}"
    os.remove(dst)
    k = stab.counters(se)
    with open(res, "w") as f:
        json.dump({"signal": name, "hot": hot, "cand": stab.cname(c), "counters": k}, f)
    return res


if __name__ == "__main__":
    tasks = [(n, h, c) for n, h in stab.SIGS for c in stab.CANDS]
    with Pool(int(os.environ.get("STAB_JOBS", "6"))) as pool:
        for r in pool.imap_unordered(one, tasks):
            print(r, flush=True)
