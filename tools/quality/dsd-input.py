#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""DSD64 input as a dsd-measure class B device.

    dsd-input.py IN.wav OUT.dsf RATE [OPTION ...]

dsd-measure feeds class B devices PCM only. This device turns the PCM test signal (44.1 kHz)
into DSD64 with dsd-measure's own reference modulator (the one that feeds its class A
devices), then runs the converter named by DSDUP_CLI on that file: `IN.dsf OUT.dsf --rate
RATE [OPTION ...]`. The figures therefore include the reference modulator's DSD64 stage; they are for
comparing two builds on the same input, not for absolute DSD64-to-DSD128 figures.

Runs with the Python of the dsd-measure installation (it imports dsd_measure).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from dsd_measure.dsf import write_dsf
from dsd_measure.encode import encode
from dsd_measure.wavio import read_wav

DSD64 = 2822400


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: dsd-input.py IN.wav OUT.dsf RATE [OPTION ...]")
    cli = os.environ.get("DSDUP_CLI")
    if not cli:
        sys.exit("set DSDUP_CLI to the dsd-upsample binary under test")
    src, out, rate, extra = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    x, fs = read_wav(src)
    bits = np.array([encode(c, fs, DSD64)[0] for c in x])
    with tempfile.TemporaryDirectory(prefix="dsd-input-") as d:
        mid = Path(d) / "dsd64.dsf"
        write_dsf(mid, bits, DSD64)
        r = subprocess.run([cli, str(mid), out, "--rate", rate, *extra], stdin=subprocess.DEVNULL)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
