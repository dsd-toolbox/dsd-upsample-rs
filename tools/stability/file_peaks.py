#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Peak at the modulator input of audio files, with a build that records it (peak.patch).

    git apply tools/stability/peak.patch
    cargo build --release --target-dir target-peak -p dsd-upsample-cli
    git apply -R tools/stability/peak.patch
    python tools/stability/file_peaks.py OUT.tsv FILE... [--bin target-peak/release/dsd-upsample] [--jobs 4]

Every file is converted with --gain 0 and order 5 (PCM to DSD64, DSD64 to DSD128, DSD128
and DSD256 to DSD256; the peak does not depend on the order, and on the gate's signals it
differs by at most 0.05 dB between output rates) and the output is discarded. One line per file: path, input rate, the peak over all channels as a fraction of
100 % modulation, and in dB re 0.5: dBTP for PCM (full scale is 0.5 at a gain of 0 dB), dB
SACD for DSD. A file is limited at a gain of G dB when its peak in dB exceeds 0.17 - G
(the default limit, 0.51). The patched build is never shipped; without the patch the tool
reports the limited samples but not the peak.
"""
import argparse
import math
import os
import re
import subprocess
import tempfile
from multiprocessing import Pool


def run(binary, path, tmp, rate):
    p = subprocess.run([binary, path, os.path.join(tmp, f"p-{os.getpid()}.dsf"), "--rate", rate,
                        "--order", "5", "--gain", "0", "--single-thread"],
                       capture_output=True, text=True)
    m = re.search(r"(\d+) Hz -> ", p.stderr)
    if p.returncode or not m:
        return None, p.stderr.strip()[-200:]
    return int(m.group(1)), float(re.findall(r"peak ([\d.]+)", p.stderr)[0])


def one(t):
    binary, path, tmp = t
    rate, pk = run(binary, path, tmp, "64")  # PCM; DSD input is refused at this rate
    if rate is None:
        rate, pk = run(binary, path, tmp, "128")
        if rate is not None and rate > 2822400:
            rate, pk = run(binary, path, tmp, "256")
    if rate is None:
        return f"{path}\tFAIL\t{pk}"
    db = 20 * math.log10(pk / 0.5) if pk > 0 else float("-inf")
    return f"{path}\t{rate}\t{pk:.6f}\t{db:+.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--bin", default="target-peak/release/dsd-upsample")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(a.out))) as tmp, \
            Pool(a.jobs) as pool, open(a.out, "a") as fo:
        for line in pool.imap_unordered(one, [(a.bin, f, tmp) for f in a.files]):
            fo.write(line + "\n")
            fo.flush()
            print(line, flush=True)


if __name__ == "__main__":
    main()
