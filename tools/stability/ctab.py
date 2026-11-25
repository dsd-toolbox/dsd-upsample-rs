# SPDX-License-Identifier: MIT OR Apache-2.0
"""Clipped states / resets per candidate from counts.py, legal and hot signals apart.
python tools/stability/ctab.py STAB_WORK/counts"""
import json, glob, os, sys
rows = {}
for p in glob.glob(sys.argv[1] + "/*/*.json"):
    d = json.load(open(p)); rows.setdefault(d["cand"], {})[("hot_" if d["hot"] else "") + d["signal"]] = d["counters"]
def key(c):
    a = c.split("-"); return (int(a[0][3:]), int(a[1][1:]), float(a[2][1:]))
for c in sorted(rows, key=key):
    r = rows[c]
    leg = {s: k for s, k in r.items() if not s.startswith("hot_")}
    hot = {s: k for s, k in r.items() if s.startswith("hot_")}
    bl = {s: "%d/%d" % (k["clipped"], k["resets"]) for s, k in leg.items() if k["clipped"] or k["resets"]}
    bh = {s[4:]: "%d/%d" % (k["clipped"], k["resets"]) for s, k in hot.items() if k["clipped"] or k["resets"]}
    print("%-18s legal %2d run, bad %s | hot %2d run, bad %s" % (c, len(leg), bl or "none", len(hot), bh or "none"))
