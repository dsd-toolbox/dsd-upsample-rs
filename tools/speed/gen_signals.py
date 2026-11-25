#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Music-like test signal for speed runs: pink noise plus tones, 24-bit WAV.

usage: gen_signals.py OUT.wav FS CHANNELS SECONDS
       gen_signals.py --all DIR   (every input of the speed runs, in DIR/sig; DSD64 files are
                                   made from the 176.4 kHz ones with DIR/bin/v2/dsd-upsample)

Per channel: pink noise (1/f spectrum, 20 Hz-20 kHz, independent seed per
channel) at -20 dBFS RMS, plus tones at 110, 440, 1000, 3150 and 9000 Hz
(each -26 dBFS, slow amplitude modulation so the level moves like music).
Peak normalised to -3 dBFS. Deterministic (fixed seeds).
"""
import os
import shutil
import struct
import subprocess
import sys

import numpy as np


def channel(fs, n, ch):
    rng = np.random.default_rng(1000 + ch)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / fs)
    shape = np.zeros_like(f)
    band = (f >= 20.0) & (f <= 20000.0)
    shape[band] = 1.0 / np.sqrt(f[band])
    pink = np.fft.irfft(spec * shape, n)
    pink *= 10 ** (-20 / 20) / np.sqrt(np.mean(pink**2))
    t = np.arange(n) / fs
    x = pink
    for k, hz in enumerate((110.0, 440.0, 1000.0, 3150.0, 9000.0)):
        env = 0.6 + 0.4 * np.sin(2 * np.pi * (0.13 + 0.07 * k + 0.05 * ch) * t)
        x = x + 10 ** (-26 / 20) * np.sqrt(2) * env * np.sin(2 * np.pi * hz * t + ch)
    return x


def write_all(root):
    sig = os.path.join(root, "sig")
    os.makedirs(os.path.join(sig, "batch"), exist_ok=True)
    for fs in (44100, 88200, 176400):
        for ch in (2, 6):
            write(os.path.join(sig, f"pcm{fs}_{ch}ch.wav"), fs, ch, 60.0)
    cli = os.path.join(root, "bin", "v2", "dsd-upsample")
    for ch in (2, 6):
        subprocess.run([cli, os.path.join(sig, f"pcm176400_{ch}ch.wav"),
                        os.path.join(sig, f"dsd64_{ch}ch.dsf"), "--rate", "64"], check=True)
    for i in range(8):
        shutil.copyfile(os.path.join(sig, "dsd64_2ch.dsf"), os.path.join(sig, "batch", f"dsd64_{i}.dsf"))
        shutil.copyfile(os.path.join(sig, "pcm44100_2ch.wav"),
                        os.path.join(sig, "batch", f"pcm44100_{i}.wav"))


def main():
    if sys.argv[1] == "--all":
        write_all(sys.argv[2])
        return
    write(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]))


def write(out, fs, chans, secs):
    n = int(round(fs * secs))
    data = np.stack([channel(fs, n, c) for c in range(chans)], axis=1)
    data *= 10 ** (-3 / 20) / np.max(np.abs(data))
    q = np.clip(np.round(data * 8388607.0), -8388608, 8388607).astype("<i4")
    raw = q.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    # WAVE_FORMAT_EXTENSIBLE, 24-bit PCM; mask: stereo 0x3, 5.1 0x3F.
    mask = {1: 0x4, 2: 0x3, 6: 0x3F}.get(chans, 0)
    ba = 3 * chans
    fmt = struct.pack("<HHIIHHHHIH14s", 0xFFFE, chans, fs, fs * ba, ba, 24, 22, 24, mask,
                      1, b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71")
    with open(out, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(raw)) + b"WAVE")
        fh.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        fh.write(b"data" + struct.pack("<I", len(raw)) + raw)


if __name__ == "__main__":
    main()
