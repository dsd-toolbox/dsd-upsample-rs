# SPDX-License-Identifier: MIT OR Apache-2.0
"""Prints the results of stab.py: tones, IMD, and per signal the counters and the error
beyond an ideal hard limiter.  python tools/stability/summ.py [STAB_WORK]"""
import glob
import json
import os
import sys

W = sys.argv[1] if len(sys.argv) > 1 else os.path.join("target", "stability")
R = os.path.join(W, "results")
cands = sorted(os.listdir(R), key=lambda c: (int(c.split("-")[0][3:]), c))


def load(c, tag):
    p = os.path.join(R, c, tag + ".json")
    return json.load(open(p)) if os.path.exists(p) else None


print("## Tones (1 kHz)")
print("cand | SINAD -3 dB SACD | THD+N 0 dB SACD | lim/clip/res at 0 dB SACD")
for c in cands:
    a, b = load(c, "tone1k-3"), load(c, "tone1k+0")
    sa = f"{a['tone']['sinad_db']:.1f}" if a else "-"
    sb = f"{-b['tone']['thdn_db']:.1f}" if b else "-"
    k = b["counters"] if b else {}
    print(f"{c} | {sa} | {sb} | {k.get('limited')}/{k.get('clipped')}/{k.get('resets')}")

print("\n## IMD at a 0 dB SACD peak")
for c in cands:
    row = []
    for sid in ("ccif_88", "ccif_352", "smpte_88", "multitone_88"):
        d = load(c, "imd_" + sid)
        if not d:
            row.append(f"{sid}: -")
            continue
        k = d["counters"]
        a = d["analysis"]
        keys = [x for x in a if any(s in x for s in ("d2", "d3", "imd_db", "dfr", "distortion"))]
        vals = ", ".join(f"{x}={a[x]:.1f}" for x in keys if isinstance(a[x], (int, float)))
        row.append(f"{sid}: L{k['limited']} C{k['clipped']} R{k['resets']} {vals}")
    print(c, " || ".join(row))

print("\n## Stability (60 s): limited / clipped / resets | excess re 0 dB SACD whole / worst 10 ms | rel whole/worst")
tags = sorted({os.path.basename(p)[:-5] for p in glob.glob(os.path.join(R, "*", "*.json"))
               if not os.path.basename(p).startswith(("tone", "imd_"))})
for t in tags:
    for c in cands:
        d = load(c, t)
        if not d:
            continue
        k = d["counters"]
        print(f"{t:22s} {c:18s} L{k['limited']:>10} C{k['clipped']:>9} R{k['resets']:>4} | "
              f"{d['excess_sacd_db']:7.1f} {d['excess_worst_window_sacd_db']:7.1f} | "
              f"{d['excess_db']:7.1f} {d['excess_worst_window_db']:7.1f} pk {d['mod_input_peak_sacd_db']:+.2f}")
