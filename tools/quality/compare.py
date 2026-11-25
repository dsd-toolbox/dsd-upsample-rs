#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Release test plan item 7: measure two builds with suites/upconverter.toml and compare them.

Run through tools/quality-compare.sh, which picks the Python of the dsd-measure installation.

    quality-compare.sh [--dry-run] [--profile quick|full] [--jobs N]
                       [--old-label TEXT] [--new-label TEXT] OLD-CLI NEW-CLI VERSION
    quality-compare.sh --repeat N [--profile quick|full] [--jobs N] CLI

Split across hosts: run with --only GLOB in one work folder per host (measures and null-tests the
matching devices, writes no page), then once with --merge DIR for each of those folders.

Exit status: 0 no regression, 1 a regression beyond repeatability, 2 the run failed.
"""
import argparse
import concurrent.futures as cf
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "suites" / "upconverter.toml"
OUR_KEYS = {"in_rates", "path", "part", "null_args", "level_ref_db"}  # device keys for this script, removed before dsd-measure sees them

#: The largest measured gain error (dB, dsd-measure's ``gain_error_db``) that the level correction
#: may leave. A larger one means the correction does not match the build's output level (a wrong
#: or misread default gain), and the run fails rather than compare figures at the wrong level.
GAIN_CHECK_DB = 0.1

#: The default gain sentence of the converter's ``--help`` ("Defaults: ..., --gain -6 (0 for PCM
#: output)"), the only source of a build's default gain. Every build since 0.1.0-rc1 prints it.
DEFAULT_GAIN_RE = re.compile(r"Defaults:[^\n]*?--gain (-?\d+(?:\.\d+)?) \(0 for PCM output\)")

#: The two parts of a comparison: the converter at equal explicit settings (the gate), then at each
#: build's own defaults (a default that moved shows here, and must be explained by a decision).
PARTS = {
    "explicit": "Part (a), equal explicit settings",
    "defaults": "Part (b), each build at its defaults",
}

#: metric -> (label, unit, results.json getter, direction: +1 when a higher value is the better figure)
METRICS = {
    "sinad_db": ("SINAD (= -THD+N)", "dB", lambda m: m["tone_0dbsacd"]["sinad_db"], +1),
    "thd_db": ("THD", "dB", lambda m: m["tone_0dbsacd"]["thd_db"], -1),
    "noise_a_dbfs": ("Noise floor, A-wtd", "dBFS", lambda m: m["noise"]["a_weighted_dbfs"], -1),
    "dr_a_db": ("Dynamic range, A-wtd", "dB", lambda m: m["dynamic_range"]["dr_a_db"], +1),
}


class Fail(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


_DEFAULT_GAIN = {}


def default_gain(cli):
    """The build's default gain for DSD output, in dB, as its ``--help`` states it.

    Fails when the help text has no such statement: a correction from a guessed gain would put
    every absolute figure of that build at the wrong level.
    """
    cli = str(Path(cli).resolve())
    if cli not in _DEFAULT_GAIN:
        r = subprocess.run([cli, "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        m = DEFAULT_GAIN_RE.findall(r.stdout + r.stderr)
        if len(m) != 1:
            raise Fail(f"{cli}: cannot read the default gain from --help (expected one 'Defaults: ... --gain DB "
                       f"(0 for PCM output)', found {len(m)}); the level correction needs it")
        _DEFAULT_GAIN[cli] = float(m[0])
    return _DEFAULT_GAIN[cli]


def converter_gain(cli, command):
    """(gain in dB, source) of one device run: the last ``--gain`` in its command, else the default."""
    import shlex
    words = shlex.split(command)
    given = [words[i + 1] for i, w in enumerate(words[:-1]) if w == "--gain"]
    if given:
        return float(given[-1]), "explicit"
    return default_gain(cli), "default (--help)"


def level_correction(cli, dev):
    """dsd-measure's ``gain_db`` for one build and device: the suite's ``level_ref_db`` minus the gain
    the converter applies, so that every build's report reads at dsd-measure's levels."""
    if "gain_db" in dev:
        raise Fail(f"{dev['name']}: the suite sets gain_db; set level_ref_db (the correction at a converter gain "
                   "of 0 dB) and let quality-compare.sh subtract each build's gain")
    g, src = converter_gain(cli, dev["command"])
    return round(dev["level_ref_db"] - g, 4), g, src


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    raise TypeError(v)


def one_device_suite(suite, dev, in_rate, profile):
    s = dict(suite, in_rate=in_rate, profile=profile)
    lines = ["[suite]"] + [f"{k} = {toml_value(v)}" for k, v in s.items()] + ["", "[[device]]"]
    lines += [f"{k} = {toml_value(v)}" for k, v in dev.items() if k not in OUR_KEYS]
    return "\n".join(lines) + "\n"


def safe(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")


class Runner:
    def __init__(self, args, cfg, work):
        self.args, self.cfg, self.work = args, cfg, work
        self.bin = Path(sys.executable).parent
        self.env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")
        self.profile = args.profile or cfg["suite"].get("profile", "quick")
        self._src, self._src_lock = None, __import__("threading").Lock()

    def dm(self, *a, env=None, log=None, rec=None):
        """Run dsd-measure; return its exit status. With rec (a path), write where it ran there: host, CPU,
        wall time and peak RSS (the largest process of the run, from wait4)."""
        cmd = [str(self.bin / "dsd-measure"), *map(str, a)]
        t0 = time.monotonic()
        with open(log, "w") if log else open(os.devnull, "w") as f:
            p = subprocess.Popen(cmd, cwd=ROOT, env=env or self.env, stdin=subprocess.DEVNULL, stdout=f,
                                 stderr=subprocess.STDOUT)
            _, status, ru = os.wait4(p.pid, 0)
            p.returncode = rc = os.waitstatus_to_exitcode(status)
        if rec:
            Path(rec).write_text(json.dumps({"host": platform.node(), "cpu": cpu(), "seconds": round(time.monotonic() - t0, 1),
                                             "peak_rss_bytes": ru.ru_maxrss * 1024}))
        return rc

    def selected(self, dev):
        """Is this device one this run measures (--only)?"""
        return not self.args.only or any(fnmatch.fnmatchcase(dev["name"], g) for g in self.args.only)

    def devices(self):
        """(in_rate, device) for every part, device and input rate it applies to.

        The suite's devices run at the converter's defaults; the explicit part appends
        quality.explicit_settings to each command (and to the null test's conversion).
        """
        q = self.cfg["quality"]
        out = []
        for part in PARTS:
            for r in q["in_rates"]:
                for d in self.cfg["device"]:
                    if r not in d.get("in_rates", q["in_rates"]):
                        continue
                    if part == "explicit":
                        extra = list(q["explicit_settings"])
                        d = dict(d, part=part, name=f"{d['name']} explicit", null_args=extra,
                                 command=d["command"] + " " + " ".join(extra))
                    else:
                        d = dict(d, part=part, null_args=[])
                    out.append((r, d))
        return out

    def probe(self, cli, in_rate, dev):
        """Does this build accept this conversion? A 0.2 s tone through the device's own command."""
        from dsd_measure.adapters import substitute
        from dsd_measure.wavio import write_wav
        d = self.work / "probe" / f"{safe(str(cli))}-{in_rate}-{safe(dev['name'])}"
        d.mkdir(parents=True, exist_ok=True)
        t = np.arange(int(0.2 * in_rate)) / in_rate
        write_wav(d / "in.wav", 0.25 * np.sin(2 * np.pi * 1000 * t), in_rate, "pcm32")
        import shlex
        cmd = [substitute(w, input=str(d / "in.wav"), output=str(d / "out.dsf")) for w in shlex.split(dev["command"])]
        r = subprocess.run(cmd, cwd=ROOT, env=dict(self.env, DSDUP_CLI=str(cli)), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True)
        shutil.rmtree(d)
        err = (r.stderr.strip().splitlines() or [""])[-1]
        return r.returncode == 0, err

    def measure(self, role, cli, in_rate, dev):
        d = self.work / role / str(in_rate)
        d.mkdir(parents=True, exist_ok=True)
        corr, gain, gain_src = level_correction(cli, dev)
        st = d / f"{safe(dev['name'])}.toml"
        st.write_text(one_device_suite(self.cfg["suite"], dict(dev, gain_db=corr), in_rate, self.profile))
        out = d / "report" / safe(dev["name"])  # one folder per device: runs in parallel never share one
        found = lambda: sorted(out.glob("*/results.json"))  # noqa: E731  (one device per run: its report folder)
        if self.args.resume and found():  # a report kept from an earlier run of the same command
            rc = 0
        else:
            if out.exists():
                shutil.rmtree(out)
            rc = self.dm("run", st, "-o", out, env=dict(self.env, DSDUP_CLI=str(cli)), log=d / f"{safe(dev['name'])}.log",
                         rec=d / f"{safe(dev['name'])}.host.json")
        res = (found() or [out / "missing"])[0]
        if rc not in (0, 1) or not res.exists():
            raise Fail(f"dsd-measure failed ({rc}) for {role} {dev['name']} at {in_rate} Hz: see {d / (safe(dev['name']) + '.log')}")
        m = json.loads(res.read_text())["metrics"]
        err = m.get("gain_error_db")
        if err is None or abs(err) > GAIN_CHECK_DB:
            raise Fail(f"{role} {dev['name']} at {in_rate} Hz: gain error {err} dB after a level correction of {corr:+.4f} dB "
                       f"(converter gain {gain:g} dB, {gain_src}); the correction does not match the output level")
        vals = {}
        for k, (_, _, get, _) in METRICS.items():
            try:
                vals[k] = float(get(m))
            except (KeyError, TypeError):
                vals[k] = None
        return {"metrics": vals, "rc": rc, "report": str(res.parent), "gain_db": gain, "gain_source": gain_src,
                "level_correction_db": corr, "gain_error_db": err, "ran": ran(d / f"{safe(dev['name'])}.host.json")}

    def null(self, tag, path, source, a_cli, b_cli, extra=()):
        """Null test of two builds along one path; each output is brought to a converter gain of 0 dB first
        (its explicit or default gain undone), so a moved default gain does not misalign the comparison."""
        out = self.work / "null" / tag
        out.parent.mkdir(parents=True, exist_ok=True)
        tail = "".join(" " + a for a in extra)
        dev = lambda role: f"{role}=tools/quality/null-chain.py {role} {path} {{input}} {{output}}{tail}"  # noqa: E731
        cmd = " ".join(["x", *extra])
        env = dict(self.env, DSDUP_BASELINE_CLI=str(a_cli), DSDUP_CANDIDATE_CLI=str(b_cli),
                   DSDUP_BASELINE_LEVEL_DB=repr(-converter_gain(a_cli, cmd)[0]),
                   DSDUP_CANDIDATE_LEVEL_DB=repr(-converter_gain(b_cli, cmd)[0]))
        res = out / "results.json"
        if self.args.resume and res.exists():  # kept from an earlier run (or merged with --merge)
            rc = 0
        else:
            if out.exists():
                shutil.rmtree(out)
            rc = self.dm("null", "--source", source(), "--device", dev("baseline"), "--device", dev("candidate"),
                         "-o", out, env=env, log=self.work / "null" / f"{tag}.log", rec=self.work / "null" / f"{tag}.host.json")
        if rc != 0 or not res.exists():
            raise Fail(f"dsd-measure null failed ({rc}) for {tag}: see {self.work / 'null' / (tag + '.log')}")
        v = json.loads(res.read_text())["pairs"][0]["verdict"]
        return {"depth_db": float(v["depth_db"]), "tier": v["tier"], "report": str(out),
                "ran": ran(self.work / "null" / f"{tag}.host.json")}

    def source(self):
        """The null test's DSD64 source, made on first use (a merged or resumed run may need none)."""
        with self._src_lock:
            if self._src is None:
                self._src = self._make_source()
        return self._src

    def _make_source(self):
        d = self.work / "null-source"
        if self.dm("signals", d, "--class", "A", "--profile", self.profile, "--only",
                   self.cfg["quality"]["null_signal"], log=self.work / "null-source.log"):
            raise Fail("dsd-measure signals failed")
        return d / f"{self.cfg['quality']['null_signal']}.dsf"


def ran(path):
    """Where a device report or null test was made (written by Runner.dm), or None when not recorded."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def conversion_names(name, in_rate):
    """The names an explained entry's ``paths`` are matched against, for one conversion and input rate:
    the page's Conversion column ("PCM to DSD128", "PCM to DSD128 explicit"), the same with its input
    rate ("PCM to DSD128 from 44.1 kHz"), and both with every run of other characters as one hyphen
    ("PCM-to-DSD128", "PCM-to-DSD128-from-44-1-kHz")."""
    full = f"{name} from {in_rate / 1000:g} kHz"
    return [name, full, safe(name), safe(full)]


def covers(entry, name, in_rate):
    """Does an explained entry apply to this conversion? Without ``paths`` it applies to every one."""
    paths = entry.get("paths")
    if paths is None:
        return True
    names = conversion_names(name, in_rate)
    return any(fnmatch.fnmatchcase(n, p) for p in paths for n in names)


def explanation(explained, part, metric, delta, name, in_rate):
    """The first explained entry that covers a change of ``metric`` by ``delta`` dB (new minus previous)
    in ``part`` on conversion ``name`` from ``in_rate`` Hz, or None."""
    return next((e for e in explained if e["part"] == part and metric in e["metrics"]
                 and e["min_db"] <= delta <= e["max_db"] and covers(e, name, in_rate)), None)


def check_explained(explained, devices):
    """Refuse a malformed explained entry, or one whose ``paths`` name a conversion the suite does not
    have in its part: an entry that matches nothing would sit in the suite looking like an explanation."""
    for i, e in enumerate(explained):
        where = f"[[quality.explained]] entry {i + 1} (version {e.get('version')!r})"
        missing = [k for k in ("version", "part", "metrics", "min_db", "max_db", "decision") if k not in e]
        if missing:
            raise Fail(f"{where}: missing {', '.join(missing)}")
        if e["part"] not in PARTS:
            raise Fail(f"{where}: part {e['part']!r} is not one of {', '.join(PARTS)}")
        if not e["metrics"] or any(k not in METRICS for k in e["metrics"]):
            raise Fail(f"{where}: metrics must be a non-empty list of {', '.join(METRICS)}")
        if not e["min_db"] <= e["max_db"]:
            raise Fail(f"{where}: min_db is above max_db")
        if "paths" not in e:
            continue
        paths = e["paths"]
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise Fail(f"{where}: paths must be a non-empty list of conversion names or globs")
        for p in paths:
            if not any(covers(dict(paths=[p]), d["name"], r) for r, d in devices if d["part"] == e["part"]):
                raise Fail(f"{where}: paths entry {p!r} matches no conversion of part {e['part']!r}")


def null_path(dev, in_rate):
    p = dev["path"]
    return p.replace("pcm-", f"pcm{in_rate}-") if p.startswith("pcm-") else p


def check_version(cfg, dry_run, runner):
    got = json.loads(subprocess.run([str(runner.bin / "dsd-measure"), "versions"], capture_output=True, text=True,
                                    check=True).stdout)["dsd_measure"]
    want = cfg["quality"]["dsd_measure_version"]
    if got != want:
        msg = f"the suite pins dsd-measure {want!r}, but {got!r} is installed ({cfg['quality']['dsd_measure_install']})"
        if not dry_run:
            raise Fail(msg + "; use --dry-run for a labelled trial run")
        print(f"DRY RUN: {msg}", file=sys.stderr)
    return got


def cli_info(cli, label):
    p = Path(cli).resolve()
    if not p.is_file() or not os.access(p, os.X_OK):
        raise Fail(f"{cli}: not an executable file")
    v = subprocess.run([str(p), "--version"], capture_output=True, text=True).stdout.strip()
    return {"path": str(p), "sha256": sha256(p), "version": v or "unknown", "label": label or v or p.name,
            "default_gain_db": default_gain(p)}


def fmt(x, unit=""):
    return "" if x is None else f"{x:.1f}"


def run_all(runner, builds, jobs):
    """builds: {role: cli}. Probes, then measures every supported (role, rate, device) in parallel."""
    supported, results = {}, {}
    for role, cli in builds.items():
        for r, d in runner.devices():
            if runner.selected(d):
                supported[(role, r, d["name"])] = runner.probe(cli, r, d)
    with cf.ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(runner.measure, role, cli, r, d): (role, r, d["name"])
                for role, cli in builds.items() for r, d in runner.devices()
                if runner.selected(d) and supported[(role, r, d["name"])][0]}
        try:
            for f in cf.as_completed(futs):
                results[futs[f]] = f.result()
                role, r, n = futs[f]
                print(f"measured {role} {n} from {r} Hz", flush=True)
        except BaseException:
            ex.shutdown(cancel_futures=True)  # stop at the first failure; running devices finish
            raise
    return supported, results


def repeat(args, runner, cfg):
    cli = cli_info(args.clis[0], None)
    builds = {f"run{i + 1}": cli["path"] for i in range(args.repeat)}
    _, results = run_all(runner, builds, args.jobs)
    lines = [f"Repeatability: {args.repeat} runs of {cli['version']} (SHA-256 {cli['sha256']}), profile {runner.profile}, "
             f"dsd-measure {runner.dm_version}, {cpu()}.", "",
             "| Input | Conversion | " + " | ".join(METRICS[k][0] + " spread (dB)" for k in METRICS) + " |",
             "|---|---|" + "---|" * len(METRICS)]
    worst = dict.fromkeys(METRICS, 0.0)
    for r, d in runner.devices():
        vals = [results[(role, r, d["name"])]["metrics"] for role in builds if (role, r, d["name"]) in results]
        if not vals:
            continue
        cells = []
        for k in METRICS:
            xs = [v[k] for v in vals if v[k] is not None]
            s = max(xs) - min(xs) if xs else None
            worst[k] = max(worst[k], s or 0.0)
            cells.append("" if s is None else f"{s:.4f}")
        lines.append(f"| {r / 1000:g} kHz | {d['name']} | " + " | ".join(cells) + " |")
    src = runner.source
    a, b = builds["run1"], builds[f"run{args.repeat}"]
    depths = []
    for r, d in runner.devices():
        if (f"run1", r, d["name"]) in results:
            n = runner.null(f"self-{r}-{safe(d['name'])}", null_path(d, r), src, a, b, d["null_args"])
            depths.append(f"{null_path(d, r)}: {n['tier']} ({n['depth_db']:.0f} dB)")
    lines += ["", "Largest spread per metric: " + ", ".join(f"{METRICS[k][0]} {worst[k]:.4f} dB" for k in METRICS) + ".",
              "Null test of the build against itself: " + "; ".join(depths) + "."]
    out = runner.work / "repeatability.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def cpu():
    try:
        for ln in open("/proc/cpuinfo"):
            if ln.startswith("model name"):
                return ln.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def cpus(results, nulls):
    """The CPUs the reports were made on (several after --merge), else this machine's."""
    seen = sorted({x["ran"]["cpu"] for x in [*results.values(), *nulls.values()] if x.get("ran")})
    return " and ".join(seen) if seen else cpu()


def compare(args, runner, cfg):
    old, new = cli_info(args.clis[0], args.old_label), cli_info(args.clis[1], args.new_label or args.version)
    rep = cfg["quality"]["repeatability"]
    check_explained(cfg["quality"].get("explained", []), runner.devices())  # before hours of measuring
    supported, results = run_all(runner, {"baseline": old["path"], "candidate": new["path"]}, args.jobs)
    src = runner.source
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        futs = {(r, d["name"]): ex.submit(runner.null, f"{r}-{safe(d['name'])}", null_path(d, r), src, old["path"], new["path"],
                                          d["null_args"])
                for r, d in runner.devices()
                if ("baseline", r, d["name"]) in results and ("candidate", r, d["name"]) in results}
        nulls = {k: f.result() for k, f in futs.items()}
    if args.only:  # one host's share of a split run: its reports stay in the work folder for --merge
        print(f"partial run (--only {' '.join(args.only)}): {len(results)} device reports and {len(nulls)} null tests "
              f"in {runner.work}; merge them with --merge {runner.work}")
        return 0

    q = cfg["quality"]
    explained = [e for e in q.get("explained", []) if e.get("version") == args.version]
    hdr = ["Input", "Conversion", "Build"] + [f"{METRICS[k][0]} ({METRICS[k][1]})" for k in METRICS] + [
        "Alias rejection", "Null depth vs previous (dB)", "Change beyond repeatability"]
    tables = {part: [] for part in PARTS}
    unexplained, accepted, new_caps, differs = [], [], [], []
    for r, d in runner.devices():
        part = d["part"]
        key_o, key_n = ("baseline", r, d["name"]), ("candidate", r, d["name"])
        where = f"{d['name']} from {r / 1000:g} kHz"
        for role, info, key in (("baseline", old, key_o), ("candidate", new, key_n)):
            if key in results:
                cells = [fmt(results[key]["metrics"][k]) for k in METRICS]
            else:
                cells = ["not accepted"] + [""] * (len(METRICS) - 1)
            nd, flag = "", ""
            if role == "candidate":
                if key_o in results and key_n in results:
                    n = nulls[(r, d["name"])]
                    nd = "identical" if n["tier"] == "identical" else f"{n['depth_db']:.1f}"
                    if n["tier"] != "identical":
                        differs.append((part, n["depth_db"]))
                    flags = []
                    for k, (lab, unit, _, _) in METRICS.items():
                        va, vb = results[key_o]["metrics"][k], results[key_n]["metrics"][k]
                        if va is None or vb is None:
                            raise Fail(f"{lab} missing for {where}")
                        delta = vb - va
                        if abs(delta) <= rep[k]:
                            continue
                        text = f"{where}: {lab} measures {vb:.1f} {unit} against {va:.1f} {unit}"
                        why = explanation(explained, part, k, delta, d["name"], r)
                        if why:
                            flags.append(f"{lab} {delta:+.1f} {unit}, explained by decision: {why['decision']}")
                            accepted.append(f"{text} (explained by decision: {why['decision']})")
                        else:
                            flags.append(f"{lab} {delta:+.1f} {unit}, NOT EXPLAINED")
                            unexplained.append(text)
                    flag = "; ".join(flags) or "none"
                elif key_n in results:
                    flag = f"not comparable: {old['label']} does not accept it"
                    if part == "defaults":
                        new_caps.append(f"{d['name']} from {r / 1000:g} kHz")
            tables[part].append([f"{r / 1000:g} kHz", d["name"], info["label"]] + cells + ["not measured", nd, flag])

    dry = " (DRY RUN)" if args.dry_run else ""
    settings = " ".join(q["explicit_settings"])
    cond = (f"dsd-measure class B, profile {runner.profile}; 1 kHz at 0 dB SACD input for SINAD and THD; "
            "20 Hz to 20 kHz; each output level-corrected by the gain its build applies (explicit, or its default as "
            f"its --help states it), checked to leave a gain error within {GAIN_CHECK_DB} dB")
    if unexplained:
        concl = ("Fails: changes beyond repeatability that no recorded decision explains, under " + cond + ": "
                 + "; ".join(unexplained) + ".")
    else:
        concl = (f"At equal input rate, output rate and explicit settings ({settings}), {new['label']} measures within "
                 f"the stated repeatability of {old['label']} on every figure"
                 + ("" if not [x for x in accepted if " explicit from " in x] else " apart from the explained changes listed"))
        dd = [x for p_, x in differs if p_ == "explicit"]
        concl += ("; the null test finds identical output at those settings" if not dd else
                  f"; the null depth at those settings measures {min(dd):.0f} to {max(dd):.0f} dB (20 Hz to 20 kHz, multitone)")
        dflt = [x for x in accepted if " explicit from " not in x]
        concl += ("; at each build's defaults, " + "; ".join(dflt) if dflt else
                  "; at each build's defaults the figures also stay within repeatability")
        if new_caps:
            concl += (f"; {', '.join(new_caps)} {'is' if len(new_caps) == 1 else 'are'} accepted only by "
                      f"{new['label']} and so {'has' if len(new_caps) == 1 else 'have'} no comparison")
        concl += "."
    lines = [f"# Quality: {new['label']} against {old['label']}{dry}", ""]
    if args.dry_run:
        lines += [f"> Dry run (dsd-measure {runner.dm_version}, suite pin {q['dsd_measure_version']}, profile "
                  f"{runner.profile}). Not a release record.", ""]
    lines += [
        f"Measured with dsd-measure {runner.dm_version} (profile {runner.profile}) and "
        f"`suites/upconverter.toml` (SHA-256 {sha256(SUITE)}) on {cpus(results, nulls)}, under {cond}. "
        f"Repeatability: {', '.join(f'{METRICS[k][0]} {rep[k]} {METRICS[k][1]}' for k in METRICS)}. "
        "Only equal input rate, output rate and format are compared.", "",
        "| Build | Version | Default gain, DSD output (from --help) | SHA-256 |", "|---|---|---|---|",
        f"| {old['label']} | {old['version']} | {old['default_gain_db']:g} dB | `{old['sha256']}` |",
        f"| {new['label']} | {new['version']} | {new['default_gain_db']:g} dB | `{new['sha256']}` |", ""]
    intro = {"explicit": f"Both builds with `{settings}`: the converter at equal rate, format and level. "
                         "Any change beyond repeatability fails unless a recorded decision explains it.",
             "defaults": "Each build at its own default settings. A default that moved shows here; every change "
                         "beyond repeatability must be explained by a recorded decision, or the comparison fails."}
    for part, title in PARTS.items():
        lines += [f"## {title}", "", intro[part], "", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        lines += ["| " + " | ".join(row) + " |" for row in tables[part]]
        lines += [""]
    lines += ["Alias rejection is not measured: dsd-measure measures image rejection for DSD-to-PCM devices "
              "only. DSD64 input is made by dsd-measure's reference modulator, so those rows include its DSD64 stage. "
              "Null depth: `dsd-measure null` in 20 Hz to 20 kHz on its multitone signal, each build's output decoded "
              "by its reference decoder, brought to a gain of 0 dB, low-passed at 24 kHz and level-matched.", "", "## Conclusion", "", concl]
    page = "\n".join(lines) + "\n"
    if args.dry_run:
        dest = runner.work / f"{args.version}-dry-run.md"
    else:
        dest = ROOT / "docs" / "quality" / f"{args.version}.md"
        dest.parent.mkdir(exist_ok=True)
    dest.write_text(page)
    (runner.work / "summary.json").write_text(json.dumps(
        {"old": old, "new": new, "supported": {"|".join(map(str, k)): v for k, v in supported.items()},
         "results": {"|".join(map(str, k)): v for k, v in results.items()},
         "nulls": {"|".join(map(str, k)): v for k, v in nulls.items()},
         "unexplained": unexplained, "explained": accepted}, indent=1))
    print(page)
    print(f"written: {dest}\nreports: {runner.work}")
    return 1 if unexplained else 0


def main():
    ap = argparse.ArgumentParser(prog="quality-compare.sh", description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="allow an unpinned dsd-measure; write the page under the work folder")
    ap.add_argument("--profile", choices=["quick", "full"], help="override the suite's profile (dry runs only)")
    ap.add_argument("--jobs", type=int, default=4, help="dsd-measure processes at a time (default 4)")
    ap.add_argument("--repeat", type=int, help="measure one build N times and print the spread")
    ap.add_argument("--old-label")
    ap.add_argument("--new-label")
    ap.add_argument("--work", help="work folder (default target/quality/VERSION)")
    ap.add_argument("--resume", action="store_true",
                    help="keep the work folder and reuse the device reports and null tests already in it")
    ap.add_argument("--only", action="append", metavar="GLOB",
                    help="measure only devices whose name matches (repeatable); writes no page, for --merge")
    ap.add_argument("--merge", action="append", metavar="DIR",
                    help="copy device reports and null tests from another work folder first (repeatable); implies --resume")
    ap.add_argument("clis", nargs="+", metavar="ARG", help="OLD-CLI NEW-CLI VERSION, or CLI with --repeat")
    args = ap.parse_args()
    try:
        cfg = tomllib.loads(SUITE.read_text())
        if args.repeat:
            if len(args.clis) != 1 or args.repeat < 2:
                ap.error("--repeat N (N >= 2) takes one CLI")
            args.version = "repeatability"
        else:
            if len(args.clis) != 3:
                ap.error("expected OLD-CLI NEW-CLI VERSION")
            args.version = args.clis.pop()
            if args.profile and args.profile != cfg["suite"].get("profile") and not args.dry_run:
                ap.error("--profile differs from the suite's: only for --dry-run")
        if args.only and args.merge:
            ap.error("--only and --merge are separate steps")
        work = Path(args.work or ROOT / "target" / "quality" / (args.version + ("-dry-run" if args.dry_run else "")))
        if work.exists() and not args.resume:
            shutil.rmtree(work)
        for sub in ("null-source",) if args.resume else ("null", "null-source"):  # --resume keeps null tests
            if (work / sub).exists():
                shutil.rmtree(work / sub)
        work.mkdir(parents=True, exist_ok=True)
        for m in args.merge or []:
            for sub in ("baseline", "candidate", "null"):
                if (Path(m) / sub).is_dir():
                    shutil.copytree(Path(m) / sub, work / sub, dirs_exist_ok=True, symlinks=True)
        args.resume = args.resume or bool(args.merge)
        runner = Runner(args, cfg, work)
        runner.dm_version = check_version(cfg, args.dry_run or bool(args.repeat), runner)
        return repeat(args, runner, cfg) if args.repeat else compare(args, runner, cfg)
    except Fail as e:
        print(f"quality-compare: {e}", file=sys.stderr)
        return 2
    except Exception:  # any other failure is a failed run, never a pass
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
