#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Markdown tables from bench.py's results.jsonl: real-time factor, best / median of 5.

usage: report.py RESULTS.jsonl
"""
import json
import sys

P, E = "0-11", "12-19"
rows = {}
nlines = 0
for line in open(sys.argv[1]):
    nlines += 1
    r = json.loads(line)
    rows[r["id"]] = r


def cell(key):
    r = rows.get(key)
    if not r or "rtf_best" not in r:
        return "not run"
    return f"{r['rtf_best']:.1f} / {r['rtf_median']:.1f}"


SRC = {"dsd64": "DSD64 DSF", "pcm44100": "44.1 kHz PCM", "pcm88200": "88.2 kHz PCM",
       "pcm176400": "176.4 kHz PCM"}


def convs():
    for src in SRC:
        for r in ((128, 256) if src == "dsd64" else (64, 128, 256)):
            yield src, r


print("### All threads and one thread (no pinning)\n")
print("| Input | Output | Stereo, all threads | Stereo, one thread | 5.1, all threads | 5.1, one thread |")
print("|---|---|--:|--:|--:|--:|")
for src, r in convs():
    k = lambda ch, t: f"v2|{src}|{ch}ch|DSD{r}|audio|{t}|-"
    print(f"| {SRC[src]} | DSD{r} | {cell(k(2, 'all'))} | {cell(k(2, 'single'))} | "
          f"{cell(k(6, 'all'))} | {cell(k(6, 'single'))} |")

print("\n### P-cores only and E-cores only (taskset)\n")
print("| Input | Output | Threads | Stereo, P-cores | Stereo, E-cores | 5.1, P-cores | 5.1, E-cores |")
print("|---|---|---|--:|--:|--:|--:|")
for t in ("all", "single"):
    for src, r in convs():
        k = lambda ch, cp: f"v2|{src}|{ch}ch|DSD{r}|audio|{t}|{cp}"
        cells = [cell(k(2, P)), cell(k(2, E)), cell(k(6, P)), cell(k(6, E))]
        if all(c == "not run" for c in cells):
            continue
        print(f"| {SRC[src]} | DSD{r} | {'all' if t == 'all' else 'one'} | " + " | ".join(cells) + " |")

print("\n### Batch mode, 8 stereo files of 60 s, all cores\n")
print("| Input | Output | `--jobs` | Real-time factor (total audio / wall) |")
print("|---|---|---|--:|")
for src, r in (("dsd64", 256), ("pcm44100", 128)):
    for j in ("default", "8"):
        print(f"| {SRC[src]} | DSD{r} | {'default (5)' if j == 'default' else j} | "
              f"{cell(f'v2|batch8x{src}|2ch|DSD{r}|audio|jobs{j}|-')} |")

print("\n### Earlier build against the current one, same host, same session\n")
print("| Input | Output | Channels, threads | Earlier build | Current build |")
print("|---|---|---|--:|--:|")
for ch in (2, 6):
    for src, r in convs():
        print(f"| {SRC[src]} | DSD{r} | {'stereo' if ch == 2 else '5.1'}, all | "
              f"{cell(f'v1|{src}|{ch}ch|DSD{r}|audio|all|-')} | {cell(f'v2|{src}|{ch}ch|DSD{r}|audio|all|-')} |")
for src, r in (("dsd64", 256), ("pcm44100", 128), ("pcm44100", 256)):
    print(f"| {SRC[src]} | DSD{r} | stereo, one | "
          f"{cell(f'v1|{src}|2ch|DSD{r}|audio|single|-')} | {cell(f'v2|{src}|2ch|DSD{r}|audio|single|-')} |")

temps = [t for r in rows.values() for t in (r.get("temp_max_c") or []) if t]
mhz = [m for r in rows.values() for m in (r.get("busiest_cpu_mhz_mean") or []) if m]
print(f"\nPackage temperature during runs: {min(temps):.0f}-{max(temps):.0f} C; "
      f"mean clock of the busiest CPU: {min(mhz)}-{max(mhz)} MHz; {nlines} configurations x {max(len(r['walls']) for r in rows.values())} runs.")
