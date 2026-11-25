# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bit-level checks of a DSD stream: density of ones and run lengths.

For each sliding window of W bits (default 28) the count of ones is taken. Modulation in a
window is (2 x ones - W) / W, so 71.43 % modulation (the +3.1 dB SACD peak level) is 24 of
28 ones (or 4 of 28). Reported:

- the minimum and maximum count over all windows, and the per-second min/mean/max density;
- windows over the limit: more than 24 or fewer than 4 ones (beyond 71.43 %);
- windows at or over it, read literally as published (24 or more, 4 or fewer);
- saturated windows (all ones or all zeros) and the longest run of identical bits.

The rule as applied, and its public source, are stated in the documentation that uses
this tool.

    python tools/measure/density.py FILE.dsf [--channel 0] [--window 28] [--start S] [--end S]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsdio  # noqa: E402

CHUNK = 1 << 25


def analyse_bits(bits, rate, window=28, hi=24, lo=4):
    """Return a dict of density statistics for a 0/1 uint8 array at `rate`."""
    n = len(bits)
    sec = rate
    per_sec = []
    cmin, cmax = window, 0
    over = at_or_over = sat = 0
    longest, run, last = 0, 0, -1
    carry = np.zeros(0, np.uint8)
    for a in range(0, n, CHUNK):
        b = bits[a:a + CHUNK]
        # run lengths
        chg = np.flatnonzero(np.diff(b.astype(np.int8))) + 1
        if len(b):
            first_end = chg[0] if len(chg) else len(b)
            if b[0] == last:
                run += first_end
            else:
                longest = max(longest, run)
                run = first_end
            if len(chg):
                longest = max(longest, run)
                lens = np.diff(np.concatenate([chg, [len(b)]]))
                if len(lens) > 1:
                    longest = max(longest, int(np.max(lens[:-1])))
                run = int(lens[-1])
            last = int(b[-1])
        # window counts, windows ending inside this chunk
        x = np.concatenate([carry, b]).astype(np.int32)
        c = np.cumsum(x)
        cnt = c[window - 1:] - np.concatenate([[0], c[:-window]])
        carry = x[-(window - 1):].astype(np.uint8)
        if len(cnt):
            cmin = min(cmin, int(cnt.min()))
            cmax = max(cmax, int(cnt.max()))
            over += int(np.count_nonzero((cnt > hi) | (cnt < lo)))
            at_or_over += int(np.count_nonzero((cnt >= hi) | (cnt <= lo)))
            sat += int(np.count_nonzero((cnt == window) | (cnt == 0)))
    longest = max(longest, run)
    # per-second min / mean / max of the window density
    for s in range(0, n // sec):
        seg = bits[s * sec:(s + 1) * sec].astype(np.int32)
        c = np.cumsum(seg)
        cnt = c[window - 1:] - np.concatenate([[0], c[:-window]])
        per_sec.append([int(cnt.min()), float(seg.mean()), int(cnt.max())])
    total = max(1, n - window + 1)
    return {"window_bits": window, "limit_ones": [lo, hi], "min_ones": cmin, "max_ones": cmax,
            "max_modulation_pct": 100 * max(2 * cmax - window, window - 2 * cmin) / window,
            "windows_over": over, "windows_over_frac": over / total,
            "windows_at_or_over": at_or_over, "windows_at_or_over_frac": at_or_over / total,
            "windows_saturated": sat, "longest_run_bits": int(longest),
            "mean_density": float(bits.mean()) if n else None,
            "per_second_min_mean_max": per_sec, "rate": rate, "bits": int(n)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--channel", type=int, default=0)
    ap.add_argument("--window", type=int, default=28)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    a = ap.parse_args()
    bits, rate = dsdio.read_dsd(a.file, a.channel)
    e = len(bits) if a.end is None else int(a.end * rate)
    r = analyse_bits(bits[int(a.start * rate):e], rate, a.window)
    print(json.dumps(r))


if __name__ == "__main__":
    main()
