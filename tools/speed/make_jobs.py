#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Write the job files (one per timing batch) for the speed runs into jobs/.

The CPU sets P and E are for an Intel Core i9-13900H (lscpu -e: logical CPUs 0-11 are the
P-cores, 12-19 the E-cores); change them for another CPU. Binaries: bin/v2/dsd-upsample,
and for the last file (earlier defaults) the earlier build at bin/v1/dsd-upsample.
"""
import os

P, E = "0-11", "12-19"  # i9-13900H: logical CPUs 0-11 = 6 P-cores x 2, 12-19 = 8 E-cores
S = 60  # seconds of audio per input file


def rates():
    out = []
    for src in ("dsd64", "pcm44100", "pcm88200", "pcm176400"):
        for r in ((128, 256) if src == "dsd64" else (64, 128, 256)):
            out.append((src, r))
    return out


def inp(src, ch):
    return f"sig/{src}_{ch}ch." + ("dsf" if src == "dsd64" else "wav")


def job(binv, src, ch, r, threads, cpus):
    # "audio" in the id: the noise-shaping band, kept so that ids match earlier result files
    jid = f"{binv}|{src}|{ch}ch|DSD{r}|audio|{threads}|{cpus}"
    cmd = f"bin/{binv}/dsd-upsample {inp(src, ch)} out/o.dsf --rate {r}"
    if threads == "single":
        cmd += " --single-thread"
    return f"{jid}\t{S}\t{cpus}\t{cmd}\n"


def write(name, lines):
    with open(os.path.join("jobs", name + ".tsv"), "w") as fh:
        fh.writelines(lines)


os.makedirs("jobs", exist_ok=True)
write("a_v2_all", [job("v2", s, c, r, "all", "-") for c in (2, 6) for s, r in rates()])
write("b1_v2_single_2ch", [job("v2", s, 2, r, "single", "-") for s, r in rates()])
r6 = rates()
write("b2_v2_single_6ch_lo", [job("v2", s, 6, r, "single", "-") for s, r in r6 if r < 256])
write("b3_v2_single_6ch_256", [job("v2", s, 6, r, "single", "-") for s, r in r6 if r == 256])
sub = [("dsd64", 128), ("dsd64", 256), ("pcm44100", 64), ("pcm44100", 128), ("pcm44100", 256)]
write("c_v2_pinned",
      [job("v2", s, c, r, "all", cp) for cp in (P, E) for c in (2, 6) for s, r in sub]
      + [job("v2", s, 2, r, "single", cp) for cp in (P, E)
         for s, r in (("dsd64", 256), ("pcm44100", 128), ("pcm44100", 256))])
batch = []
for src, r in (("dsd64", 256), ("pcm44100", 128)):
    ext = "dsf" if src == "dsd64" else "wav"
    files = " ".join(f"sig/batch/{src}_{i}.{ext}" for i in range(8))
    for jobs in (None, 8):
        jid = f"v2|batch8x{src}|2ch|DSD{r}|audio|jobs{jobs or 'default'}|-"
        cmd = f"bin/v2/dsd-upsample {files} --out-dir out --rate {r}"
        if jobs:
            cmd += f" --jobs {jobs}"
        batch.append(f"{jid}\t{8 * S}\t-\t{cmd}\n")
write("d_v2_batch", batch)
write("e_v1_xver",
      [job("v1", s, c, r, "all", "-") for c in (2, 6) for s, r in rates()]
      + [job("v1", s, 2, r, "single", "-")
         for s, r in (("dsd64", 256), ("pcm44100", 128), ("pcm44100", 256))]
      + [job("v2", s, 2, r, "single", "-")
         for s, r in (("dsd64", 256),)])
