#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Timing runner: each job line runs REPS times; wall time per run, best and median.

usage: bench.py JOBS.tsv RESULTS.jsonl [REPS]

JOBS.tsv lines: id<TAB>audio_seconds<TAB>cpus (or -)<TAB>command (shell words, no shell
features). Output files go where the command says; the runner deletes OUTDIR/* before
every run (OUTDIR from env, default ./out). Each result line records wall times, the
package temperature (max during the run) and, sampled every 0.5 s, the highest
scaling_cur_freq among the CPUs used, averaged over the run.
"""
import glob
import json
import os
import shlex
import statistics
import subprocess
import sys
import threading
import time

def find_temp():
    """Package temperature: coretemp temp1 (Intel) or k10temp temp1 (AMD), if present."""
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            name = open(os.path.join(d, "name")).read().strip()
        except OSError:
            continue
        if name in ("coretemp", "k10temp"):
            return os.path.join(d, "temp1_input")
    return "/nonexistent"


TEMP = find_temp()


def read_int(p):
    try:
        with open(p) as fh:
            return int(fh.read())
    except OSError:
        return None


def cpu_list(spec):
    if spec == "-":
        return list(range(os.cpu_count()))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def sampler(stop, cpus, acc):
    while not stop.is_set():
        t = read_int(TEMP)
        if t is not None:
            acc["tmax"] = max(acc.get("tmax", 0), t / 1000)
        fr = [read_int(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq") for c in cpus]
        fr = [f for f in fr if f]
        if fr:
            acc.setdefault("mhz", []).append(max(fr) / 1000)
        stop.wait(0.5)


def main():
    jobs, results = sys.argv[1], sys.argv[2]
    reps = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    outdir = os.environ.get("OUTDIR", "out")
    os.makedirs(outdir, exist_ok=True)
    for line in open(jobs):
        if not line.strip() or line.startswith("#"):
            continue
        jid, secs, cpus, cmd = line.rstrip("\n").split("\t")
        argv = shlex.split(cmd)
        if cpus != "-":
            argv = ["taskset", "-c", cpus] + argv
        walls, tmax, mhz = [], [], []
        t0 = read_int(TEMP)
        for _ in range(reps):
            for f in glob.glob(os.path.join(outdir, "*")):
                os.remove(f)
            acc, stop = {}, threading.Event()
            th = threading.Thread(target=sampler, args=(stop, cpu_list(cpus), acc))
            th.start()
            s = time.perf_counter()
            r = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            w = time.perf_counter() - s
            stop.set()
            th.join()
            if r.returncode != 0:
                sys.stderr.write(f"{jid}: exit {r.returncode}: {r.stderr.decode()[-400:]}\n")
                break
            walls.append(w)
            tmax.append(acc.get("tmax"))
            mhz.append(round(statistics.mean(acc["mhz"])) if acc.get("mhz") else None)
        rec = {
            "id": jid, "audio_s": float(secs), "cpus": cpus, "cmd": " ".join(argv),
            "walls": [round(w, 3) for w in walls], "temp_start_c": t0 and t0 / 1000,
            "temp_max_c": tmax, "busiest_cpu_mhz_mean": mhz,
            "load1": os.getloadavg()[0], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if len(walls) == reps:
            best, med = min(walls), statistics.median(walls)
            rec.update(best_s=round(best, 3), median_s=round(med, 3),
                       rtf_best=round(float(secs) / best, 2), rtf_median=round(float(secs) / med, 2))
        with open(results, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(jid, rec.get("rtf_best"), rec.get("rtf_median"), flush=True)
        for f in glob.glob(os.path.join(outdir, "*")):
            os.remove(f)


if __name__ == "__main__":
    main()
