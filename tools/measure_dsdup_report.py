#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Tables and SVG plots for docs/measurements-dsd.md from a measure_dsdup.py run.

    python tools/measure_dsdup.py report --work DIR [--assets docs/assets/measurements]

Writes the SVGs into --assets and prints the Markdown tables to stdout.
"""
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "measure"))
import plot  # noqa: E402

RATES = (64, 128, 256)
ORDERS = (5, 6, 7, 8)
# configurations of earlier runs that the library no longer accepts (order 8 at DSD128
# clips on legal input, docs/modulator-design.md): their results are not reported
REFUSED = ("dsdup-o8-128",)
SOX = ("sdm-4", "sdm-6", "sdm-8", "clans-4", "clans-5", "clans-6", "clans-7", "clans-8")
TRELLIS = {64: "clans-8", 128: "clans-7", 256: "clans-6"}


def label(cfg):
    if cfg == "pcm24":
        return "PCM 24/88.2"
    if cfg.startswith("dsdup"):
        o, r = cfg.split("-")[1][1:], cfg.split("-")[-1]
        d = " (default)" if FINAL[int(r)][0] == int(o) else ""
        return f"dsd-upsample order {o}{d}, DSD{r}"
    m, r = cfg[4:].rsplit("-", 1)
    if m.endswith("t"):
        m = m[:-1] + " trellis"
    return f"SoX {m}, DSD{r}"


def set_defaults(meta):
    """Take the CLI's defaults from the run's meta.json (written by `measure_dsdup.py run`)."""
    global DEFAULT_LIMIT
    d = (meta or {}).get("dsd_upsample", {}).get("defaults")
    if not d:
        raise SystemExit("meta.json with the CLI's defaults is missing: re-run `measure_dsdup.py run`")
    DEFAULT_LIMIT = d["limit"]
    for r in RATES:
        FINAL[r] = (d["order"], float(d["limit"]))


class Run:
    def __init__(self, work):
        self.work = work
        self.r = {}
        self.meta = None
        mp = os.path.join(work, "meta.json")
        if os.path.exists(mp):
            with open(mp) as f:
                self.meta = json.load(f)
        set_defaults(self.meta)
        for p in glob.glob(os.path.join(work, "results", "*", "*.json")):
            cfg = os.path.basename(os.path.dirname(p))
            if cfg in REFUSED:
                continue
            with open(p) as f:
                self.r[(cfg, os.path.basename(p)[:-5])] = json.load(f)

    def get(self, cfg, sid, *keys):
        d = self.r.get((cfg, sid))
        try:
            for k in keys:
                d = d[k]
        except (KeyError, TypeError, IndexError):
            return None
        return d

    def spec(self, cfg, sid, suffix=""):
        p = os.path.join(self.work, "results", cfg, f"{sid}{suffix}.npz")
        return np.load(p) if os.path.exists(p) else None


def fmt(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}"


def configs_main():
    out = []
    for r in RATES:
        out += [f"dsdup-o{o}-{r}" for o in ORDERS if f"dsdup-o{o}-{r}" not in REFUSED]
        out += [f"sox-{m}-{r}" for m in SOX] + [f"sox-{TRELLIS[r]}t-{r}"]
    return out


def summary(run, compact=False):
    rows = ["| Encoder | SINAD, 0 dB SACD (dB) | THD+N at −2.9 dBFS (dB) | DR, A-weighted (dB) "
            "| Idle noise, digital silence, 20 Hz–20 kHz (dBFS) | Multitone DFR (dB) | CCIF IMD (dB) "
            "| SMPTE IMD (dB) | Ultrasonic 22–96 kHz (dBFS) | Highest ultrasonic density to 192 kHz (kHz, dBFS/Hz) |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for cfg in ["pcm24"] + configs_main():
        g = run.get
        if g(cfg, "tone0") is None:
            continue
        if compact and cfg.startswith("sox") and not ("sdm-8" in cfg or "clans-8-" in cfg or "t-" in cfg):
            continue
        hump = g(cfg, "dr", "ultrasonic")
        hs = "–" if hump is None else f"{hump['peak192_hz'] / 1000:.0f}, {hump['peak192_dbfs_hz']:.0f}"
        rows.append("| " + " | ".join([
            label(cfg), fmt(g(cfg, "tone0", "analysis", "tone", "sinad_db")),
            fmt(g(cfg, "tonepk", "analysis", "tone", "thdn_db")),
            fmt(g(cfg, "dr", "analysis", "dr", "dr_a_db")),
            fmt(g(cfg, "silence", "analysis", "noise", "n20_20k_dbfs")),
            fmt(g(cfg, "mt0", "analysis", "multitone", "dfr_db")),
            fmt(g(cfg, "ccif", "analysis", "ccif", "imd_db")),
            fmt(g(cfg, "smpte", "analysis", "smpte", "imd_db")),
            fmt(g(cfg, "dr", "ultrasonic", "u22_96_dbfs")
                if cfg != "pcm24" else None), hs]) + " |")
    return "\n".join(rows)


def detail(run):
    rows = ["| Encoder | THD, 0 dB SACD (dB) | THD+N −3 dB SACD (dB) | THD+N −20 dB SACD (dB) | THD+N −40 dB SACD (dB) "
            "| THD at −2.9 dBFS (dB) | DR unweighted (dB) | J-Test largest sideband (dBc) "
            "| Multitone DFR at −2.9 dBFS (dB) | Multitone DFR, 1 average (dB) |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for cfg in ["pcm24"] + configs_main():
        g = run.get
        if g(cfg, "tone0") is None:
            continue
        rows.append("| " + " | ".join([
            label(cfg), fmt(g(cfg, "tone0", "analysis", "tone", "thd_db")),
            fmt(g(cfg, "tone-3", "analysis", "tone", "thdn_db")),
            fmt(g(cfg, "tone-20", "analysis", "tone", "thdn_db")),
            fmt(g(cfg, "tone-40", "analysis", "tone", "thdn_db")),
            fmt(g(cfg, "tonepk", "analysis", "tone", "thd_db")),
            fmt(g(cfg, "dr", "analysis", "dr", "dr_db")),
            fmt(g(cfg, "jtest", "analysis", "jtest", "largest_sideband_dbc")),
            fmt(g(cfg, "mtpk", "analysis", "multitone", "dfr_db")),
            fmt(g(cfg, "mt0", "analysis", "multitone", "avg1", "dfr_db"))]) + " |")
    return "\n".join(rows)


def ultra_table(run):
    rows = ["| Encoder | Highest density to 192 kHz (kHz, dBFS/Hz) | Hump above 192 kHz (kHz, dBFS/Hz) "
            "| 22–96 kHz (dBFS) | 20–100 kHz (dBFS) | 100–192 kHz (dBFS) | Same, digital silence: 22–96 kHz (dBFS) |",
            "|---|--:|--:|--:|--:|--:|--:|"]
    for cfg in configs_main():
        u = run.get(cfg, "dr", "ultrasonic")
        s = run.get(cfg, "silence", "ultrasonic")
        if not u:
            continue
        above = (f"{u['peak_hz'] / 1000:.0f}, {u['peak_dbfs_hz']:.1f}" if u["peak_hz"] > 192500 else "–")
        rows.append(f"| {label(cfg)} | {u['peak192_hz'] / 1000:.0f}, {u['peak192_dbfs_hz']:.1f} | {above} | "
                    f"{u['u22_96_dbfs']:.1f} | {u['u20_100_dbfs']:.1f} | {fmt(u['u100_192_dbfs'])} | "
                    f"{fmt(s['u22_96_dbfs'] if s else None)} |")
    return "\n".join(rows)


def stability_table(run):
    def rec(d):
        fl = run.get(k[0], "tone-3", "analysis", "tone", "noise_dbfs") or -150
        return recovery_ms(d, fl)

    rows = ["| Encoder | Limit | Level (dB SACD) | Freq (kHz) | Limited | Clipped | Resets "
            "| Max modulation, 28-bit window (%) | Windows beyond 71.43 % | Longest run (bits) "
            "| THD+N first / last 10 s (dB) | Recovery (ms) |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    keys = sorted((k for k in run.r if k[1].startswith("hold") and k[0].startswith(("dsdup", "sox"))
                   and "not_run" not in run.r[k]),
                  key=lambda k: (k[0], run.r[k]["limit"] or "", run.r[k]["level_sacd"],
                                 run.r[k]["freq"]))
    for k in keys:
        d = run.r[k]
        c = d["counters"] or {}
        dn = d["density"]
        rows.append("| " + " | ".join([
            label(k[0]), (d["limit"] or DEFAULT_LIMIT) if k[0].startswith("dsdup") else "–",
            f"{d['level_sacd']:+.1f}", f"{d['freq'] / 1000:.0f}",
            str(c.get("limited", "–")), str(c.get("clipped", "–")), str(c.get("resets", "–")),
            f"{dn['max_modulation_pct']:.1f}", f"{dn['windows_over_frac'] * 100:.3g} %",
            str(dn["longest_run_bits"]),
            f"{d['thdn_first']:.1f} / {d['thdn_last']:.1f}",
            "> 2000" if rec(d) is None else str(rec(d))]) + " |")
    return "\n".join(rows)


def plots(run, assets):
    os.makedirs(assets, exist_ok=True)
    A = lambda n: os.path.join(assets, n)  # noqa: E731
    made = []

    def sp(cfg, sid, key, suffix=""):
        d = run.spec(cfg, sid, suffix)
        if d is None or key + "_f" not in d and key not in ("n",):
            return None
        return d

    # 1. 1 kHz at 0 dB SACD, per rate
    for r in RATES:
        ser = []
        for cfg in ("pcm24", f"dsdup-o6-{r}", f"sox-sdm-8-{r}", f"sox-clans-8-{r}"):
            d = run.spec(cfg, "tone0")
            if d is not None:
                ser.append((label(cfg), d["t_f"], d["t_db"]))
        if ser:
            plot.spectra(A(f"tone1k-dsd{r}.svg"), ser, (20, 20000), (-220, 0), log=True,
                         title=f"1 kHz at 0 dB SACD (−6.02 dBFS), DSD{r}",
                         note="Reference decoder to 352.8 kHz; FFT 2^18, 7-term Blackman-Harris, "
                              "1 average; dBFS per bin")
            made.append(f"tone1k-dsd{r}.svg")
    # 2. orders, idle noise density, DSD128
    for r in RATES:
        ser = []
        for o in ORDERS:
            d = run.spec(f"dsdup-o{o}-{r}", "dr", "-ultra")
            if d is not None:
                ser.append((f"order {o}", d["n_f"], d["n_dbhz"]))
        if ser:
            plot.spectra(A(f"orders-dsd{r}.svg"), ser, (20, 192000), (-220, -60), log=True,
                         ylabel="dBFS/Hz",
                         title=f"dsd-upsample noise by modulator order, DSD{r}",
                         note="1 kHz at −60 dB SACD in; reference decoder to "
                              f"{705.6 if r < 256 else 1411.2} kHz; FFT 2^20, BH7, 8 averages")
            made.append(f"orders-dsd{r}.svg")
    # 3. ultrasonic by rate, ours at the default order, and SoX
    for enc, name in (("dsdup-o6-{}", "dsd-upsample order 6 (default)"), ("sox-sdm-8-{}", "SoX sdm-8"),
                      ("sox-clans-8-{}", "SoX clans-8")):
        ser = []
        for r in RATES:
            d = run.spec(enc.format(r), "dr", "-ultra")
            if d is not None:
                ser.append((f"DSD{r}", d["n_f"], d["n_dbhz"]))
        if ser:
            fn = f"ultrasonic-{enc.split('-{')[0]}.svg"
            plot.spectra(A(fn), ser, (0, 192000), (-220, -60), log=False, ylabel="dBFS/Hz",
                         title=f"Ultrasonic noise by DSD rate, {name}",
                         note="1 kHz at −60 dB SACD in; FFT 2^20, BH7, 8 averages; linear frequency axis")
            made.append(fn)
    # 4. ultrasonic, encoders compared at each rate
    for r in RATES:
        ser = []
        for cfg in (f"dsdup-o6-{r}", f"sox-sdm-8-{r}", f"sox-clans-8-{r}",
                    f"sox-{TRELLIS[r]}t-{r}"):
            d = run.spec(cfg, "dr", "-ultra")
            if d is not None:
                ser.append((label(cfg), d["n_f"], d["n_dbhz"]))
        if ser:
            plot.spectra(A(f"ultrasonic-dsd{r}.svg"), ser, (0, 192000), (-220, -60), log=False,
                         ylabel="dBFS/Hz", title=f"Ultrasonic noise, encoders compared, DSD{r}",
                         note="1 kHz at −60 dB SACD in; FFT 2^20, BH7, 8 averages")
            made.append(f"ultrasonic-dsd{r}.svg")
    # 5. multitone
    for sid, lvl in (("mt0", "peak −6.02 dBFS"), ("mtpk", "peak −2.92 dBFS")):
        ser = []
        for cfg in ("pcm24", "dsdup-o6-64", "sox-clans-8-64", "dsdup-o6-128", "dsdup-o6-256"):
            d = run.spec(cfg, sid)
            if d is not None:
                ser.append((label(cfg), d["mt_f"], d["mt_db"]))
        if ser:
            plot.spectra(A(f"multitone-{sid}.svg"), ser, (10, 22050), (-220, 0), log=True,
                         title=f"32-tone multitone, {lvl}",
                         note="25 kHz linear-phase low-pass, then FFT 2^20, rectangular window (coherent tones), 8 averages")
            made.append(f"multitone-{sid}.svg")
    # 6. J-Test
    ser = []
    for cfg in ("pcm24", "dsdup-o6-64", "sox-sdm-8-64", "dsdup-o6-128", "dsdup-o6-256"):
        d = run.spec(cfg, "jtest")
        if d is not None:
            ser.append((label(cfg), d["n_f"], d["n_db"]))
    if ser:
        plot.spectra(A("jtest.svg"), ser, (9000, 13000), (-220, 0), log=False,
                     title="24-bit J-Test (11.025 kHz at −6.02 dBFS + LSB square at 229.7 Hz)",
                     note="File-level test (arithmetic only); FFT 2^20, BH7, 8 averages")
        made.append("jtest.svg")
    # 7. DR tone, CCIF, SMPTE at DSD64 and DSD128
    for sid, xl, title in (("dr", (20, 20000), "1 kHz at −66.02 dBFS (−60 dB SACD)"),
                           ("ccif", (100, 25000), "CCIF 19 + 20 kHz, each −12.04 dBFS"),
                           ("smpte", (20, 20000), "SMPTE 60 Hz + 7 kHz 4:1, peak −6.02 dBFS")):
        ser = []
        for cfg in ("pcm24", "dsdup-o6-64", "sox-sdm-8-64", "dsdup-o6-128", "dsdup-o6-256"):
            d = run.spec(cfg, sid)
            if d is not None:
                ser.append((label(cfg), d["t_f"], d["t_db"]))
        if ser:
            plot.spectra(A(f"{sid}.svg"), ser, xl, (-220, 0), log=sid != "ccif", title=title,
                         note="FFT 2^18, BH7, 1 average; dBFS per bin")
            made.append(f"{sid}.svg")
    # 8. in-band idle noise against order, per rate (lines)
    ser = []
    for r in RATES:
        ser.append((f"dsd-upsample DSD{r}",
                    [run.get(f"dsdup-o{o}-{r}", "silence", "analysis", "noise", "n20_20k_dbfs")
                     if f"dsdup-o{o}-{r}" not in REFUSED else float("nan") for o in ORDERS]))
    plot.lines(A("noise-vs-order.svg"), list(ORDERS), ser, "Modulator order",
               "Idle noise 20 Hz–20 kHz (dBFS)", title="In-band idle noise against order",
               xticks=(list(ORDERS), [str(o) for o in ORDERS]))
    made.append("noise-vs-order.svg")
    # 9. IMD sweep
    cents = [100, 120, 140, 160, 180, 195]
    ser = []
    for cfg in ("pcm24", "dsdup-o6-64", "dsdup-o6-128", "dsdup-o6-256", "sox-sdm-8-64",
                "sox-clans-8-64"):
        v = [run.get(cfg, f"ccif{c}", "analysis", "ccif", "imd_db") for c in cents]
        if any(x is not None for x in v):
            ser.append((label(cfg), v))
    if ser:
        plot.lines(A("imd-sweep-ccif.svg"), [c / 10 for c in cents], ser,
                   "Pair centre frequency (kHz), 1 kHz spacing", "CCIF IMD (dB)",
                   title="CCIF IMD swept in frequency (pair peak −6.02 dBFS)")
        made.append("imd-sweep-ccif.svg")
    lv = [-60, -50, -40, -30, -20, -10, 0]
    ser = []
    for cfg in ("pcm24", "dsdup-o6-64", "dsdup-o6-128", "dsdup-o6-256", "sox-sdm-8-64",
                "sox-clans-8-64"):
        v = [run.get(cfg, f"smpte{x}", "analysis", "smpte", "imdn_db") for x in lv]
        if any(x is not None for x in v):
            ser.append((label(cfg), v))
    if ser:
        plot.lines(A("imd-sweep-smpte.svg"), lv, ser, "Peak level (dB SACD)",
                   "SMPTE IMD+N (dB)", title="SMPTE IMD+N against level")
        made.append("imd-sweep-smpte.svg")
    # 10. stability: max modulation against level, 1 kHz, per order (DSD128, limit 1.0)
    for lim in (None, "1.0"):
        for r in RATES:
            ser = []
            levels = [0.0, 1.5, 3.1, 4.1, 6.1]
            for o in ORDERS:
                v = []
                for x in levels:
                    k = (f"dsdup-o{o}-{r}", f"hold1k{x:+.1f}{'-l' + lim if lim else ''}")
                    d = run.r.get(k)
                    v.append(d["density"]["max_modulation_pct"] if d else None)
                if any(y is not None for y in v):
                    ser.append((f"order {o}", v))
            if ser:
                fn = f"stability-dsd{r}{'-nolimit' if lim else ''}.svg"
                plot.lines(A(fn), levels, ser, "1 kHz input level (dB SACD)",
                           "Max modulation in any 28-bit window (%)",
                           title=f"Peak modulation, DSD{r}, input limit {lim or DEFAULT_LIMIT + ' (default)'}",
                           hlines=((71.43, "71.43 % (+3.1 dB SACD)"),))
                made.append(fn)
    # 11. SINAD against level near full scale, per order (1 kHz), with the new defaults
    rows = ceiling_rows(run)
    for rate in RATES:
        ser = []
        lv = None
        for o in ORDERS:
            x = next((q for q in rows if q["cfg"] == f"dsdup-o{o}-{rate}" and q["freq"] == 1000), None)
            if x:
                lv = lv or sorted(x["sinad"])
                ser.append((f"order {o}", [x["sinad"].get(k) for k in lv]))
        if ser:
            fn = f"sinad-vs-level-dsd{rate}.svg"
            plot.lines(A(fn), lv, ser, "1 kHz input level (dB SACD)", "SINAD (dB)",
                       title=f"SINAD near full scale, DSD{rate}, input limit {DEFAULT_LIMIT}",
                       ylim=(0, 210))
            made.append(fn)
    return made


def report(work, assets):
    run = Run(work)
    made = plots(run, assets)
    print("## Summary\n")
    print(summary(run))
    print("\n## Detail\n")
    print(detail(run))
    print("\n## Ultrasonic\n")
    print(ultra_table(run))
    print("\n## Stability\n")
    print(stability_table(run))
    print("\n<!-- plots: " + ", ".join(made) + " -->")


def ceiling_rows(run):
    """Per rate, order and frequency: SINAD by level and the clean ceilings."""
    out = {}
    for (cfg, sid), d in run.r.items():
        if not sid.startswith("ceil"):
            continue
        out.setdefault((cfg, d["freq"]), []).append(d)
    rows = []
    for (cfg, fr), ds in sorted(out.items()):
        ds.sort(key=lambda d: d["level_sacd"])
        base = next((d for d in ds if abs(d["level_sacd"] + 6) < 1e-6), None)
        if base is None:
            continue
        s0 = base["tone"]["sinad_db"]
        nd0 = -6 - s0
        lit = noclip = nd = None
        for d in ds:
            L, s = d["level_sacd"], d["tone"]["sinad_db"]
            c = d["counters"] or {}
            if lit is None and s < s0 - 3:
                lit = "fail"
            if lit is None or lit != "fail":
                lit_v = L
            if noclip is None and (c.get("clipped", 0) or c.get("limited", 0) or c.get("resets", 0)):
                noclip = "fail"
            if noclip != "fail":
                noclip_v = L
            if nd is None and (L - s) > nd0 + 3:
                nd = "fail"
            if nd != "fail":
                nd_v = L
        sin = {d["level_sacd"]: d["tone"]["sinad_db"] for d in ds}
        first_clip = next((d["level_sacd"] for d in ds if (d["counters"] or {}).get("clipped")), None)
        rows.append({"cfg": cfg, "freq": fr, "sinad_m6": s0, "ceiling_sinad": lit_v,
                     "ceiling_noclip": noclip_v, "ceiling_nd": nd_v, "first_clip": first_clip,
                     "sinad": sin,
                     "sinad_0": sin.get(0.0), "sinad_m3": sin.get(-3.0)})
    return rows


def parse_cfg(cfg):
    """(rate, order, limit) of a dsd-upsample configuration name (dsdup-oN-R, trya-R-oN-lL)."""
    p = cfg.split("-")
    if cfg.startswith("dsdup"):
        return int(p[2]), int(p[1][1:]), float(DEFAULT_LIMIT)
    if cfg.startswith("trya"):
        return int(p[1]), int(p[2][1:]), float(p[3][1:])
    return None


def ceiling_table(run):
    rows = ceiling_rows(run)
    t = ["| Output | Order | Limit | Tone (kHz) | SINAD at −6 / −3 / 0 dB SACD (dB) | First clip event (dB SACD) "
         "| Clean ceiling, no clip or limiter event (dB SACD) | Clean ceiling, SINAD ≥ value at −6 dB SACD − 3 dB (dB SACD) |",
         "|---|--:|--:|--:|--:|--:|--:|--:|"]
    sel = [x for x in rows if x["cfg"].startswith("dsdup")]
    for x in sorted(sel, key=lambda x: (parse_cfg(x["cfg"])[0], parse_cfg(x["cfg"])[1], x["freq"])):
        rate, o, lim = parse_cfg(x["cfg"])
        fc = "none up to +1.0" if x["first_clip"] is None else f"{x['first_clip']:+.1f}"
        t.append(f"| DSD{rate} | {o} | {lim} | {x['freq'] / 1000:g} | {fmt(x['sinad_m6'])} / {fmt(x['sinad_m3'])} / "
                 f"{fmt(x['sinad_0'])} | {fc} | {x['ceiling_noclip']:+.1f} | {x['ceiling_sinad']:+.1f} |")
    return "\n".join(t)


def defaults_table(run):
    t = ["| Input | Output | Tone (kHz) | Limited | Clipped | Resets | Output level (dBFS) | SINAD (dB) |",
         "|---|---|--:|--:|--:|--:|--:|--:|"]
    for (cfg, sid), d in sorted(run.r.items()):
        if not cfg.startswith("default-"):
            continue
        c = d["counters"] or {}
        inp = "PCM sine, 0 dBFS" if d["kind"] == "pcm0dbfs" else "DSD64 sine, +3.1 dB SACD (gen)"
        t.append(f"| {inp} | DSD{cfg.split('-')[1]} | {d['freq'] / 1000:g} | {c.get('limited')} | "
                 f"{c.get('clipped')} | {c.get('resets')} | {d['tone']['level_dbfs']:.2f} | "
                 f"{d['tone']['sinad_db']:.1f} |")
    return "\n".join(t)


def ceiling_report(work):
    run = Run(work)
    print(ceiling_table(run))
    print()
    print(defaults_table(run))


# the CLI's defaults per rate (order, limit) and the default limit as the CLI prints it;
# set from the run's meta.json by set_defaults()
FINAL = {}
DEFAULT_LIMIT = None


def shown_trials():
    """Trial configurations on the page: the defaults at each rate."""
    return [f"trya-{r}-o{o}-l{DEFAULT_LIMIT}" for r, (o, _) in FINAL.items()]


def trial_label(cfg):
    rate, o, lim = parse_cfg(cfg)
    return f"{o}, {lim:g}" + (" (defaults)" if FINAL[rate] == (o, lim) else "")


def recovery_ms(d, floor_dbfs):
    """Time until the idle noise after the tone is back within 3 dB of the larger of the
    idle level before it and the modulator's own noise floor with signal."""
    ref = max(d["idle_before_dbfs"], floor_dbfs) + 3
    na = d["idle_after_blocks"]
    for i in range(len(na)):
        if all(v <= ref for v in na[i:]):
            return i * 50
    return None


def hot_table(run):
    t = ["| Output | Order, limit | Input before gain (dB SACD) | Tone (kHz) | Limited (s of 60) | Clip events | Resets "
         "| THD+N first / last 10 s (dB) | Excess over ideal limiter, whole / worst 10 ms (dB re the ideal signal) "
         "| Max modulation, 28-bit window (%) | Recovery (ms) |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    shown = shown_trials()
    for (cfg, sid), d in sorted(run.r.items(), key=lambda k: (parse_cfg(k[0][0])[0] if k[0][0] in shown else 0,
                                                              shown.index(k[0][0]) if k[0][0] in shown else 0,
                                                              k[1].get("level_before_gain_sacd", 0), k[1].get("freq", 0))):
        if not (cfg in shown and sid.startswith("hot")):
            continue
        ol = (trial_label(cfg).replace(" (defaults)", "") + f", gain {d['gain_db']:g} dB"
              if "gain_db" in d else trial_label(cfg))
        ex = d.get("excess") or []
        exs = "–" if not ex else (f"{max(e['excess_db'] for e in ex):.1f} / "
                                  f"{max(e['excess_worst_window_db'] for e in ex):.1f}")
        c = d["counters"] or {}
        fl = run.get(cfg, "tone-3", "analysis", "tone", "noise_dbfs") or -150
        rec = recovery_ms(d, fl)
        t.append(f"| DSD{cfg.split('-')[1]} | {ol} | {d['level_before_gain_sacd']:+.1f} | {d['freq'] / 1000:g} | "
                 f"{d['limited_s']:.1f} | {c.get('clipped')} | {c.get('resets')} | "
                 f"{d['thdn_first']:.1f} / {d['thdn_last']:.1f} | {exs} | {d['density']['max_modulation_pct']:.1f} | "
                 f"{'–' if rec is None else rec} |")
    return "\n".join(t)


EDGE = 10  # blocks (0.5 s) skipped at each end: decoder start-up and flush


def track_error(ch):
    ed = np.array(ch["block_error_dbfs"][EDGE:-EDGE])
    sig = ed - np.array(ch["block_rel_db"][EDGE:-EDGE])
    return 10 * np.log10(np.sum(10 ** (ed / 10)) / np.sum(10 ** (sig / 10)))


def limiter_events(ch, thr=-100.0):
    """Runs of 50 ms blocks whose error against the reference exceeds thr dBFS."""
    ed = ch["block_error_dbfs"][EDGE:-EDGE]
    rel = ch["block_rel_db"][EDGE:-EDGE]
    ev, longest, cur, worst = 0, 0, 0, None
    for e, r in zip(ed, rel):
        if e > thr:
            cur += 1
            worst = r if worst is None else max(worst, r)
        else:
            if cur:
                ev += 1
                longest = max(longest, cur)
            cur = 0
    if cur:
        ev += 1
        longest = max(longest, cur)
    return ev, longest * ch["block_s"], worst


def music_files(work):
    """Conversion results of the music driver, named <source>-<rate>-<order>-l<limit>.json."""
    import re as _re
    out = []
    for p in glob.glob(os.path.join(work, "music", "*.json")):
        if _re.fullmatch(r".+-\d+-\d-l[0-9.]+\.json", os.path.basename(p)) and \
                not os.path.basename(p).startswith("isp"):
            with open(p) as f:
                out.append(json.load(f))
    return out


def music_table(work, kind="defaults"):
    """kind "defaults": conversions at the CLI's defaults; "orders": every other order."""
    t = ["| Track | Peak, wideband / audio band (dB SACD) | Output | Order, limit | Limited time (s, % of track) "
         "| Clip events | Resets | Limiter events (50 ms blocks, error > −100 dBFS) | Longest (s) "
         "| Worst block error re signal (dB) | Whole-track error re signal (dB) |",
         "|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    rows = []
    for d in music_files(work):
        is_def = FINAL[d["rate"]] == (d["order"], float(d["limit"]))
        if is_def != (kind == "defaults"):
            continue
        rows.append(d)
    def key(d):
        m = d["source"]
        return (int(m[1:]) if m[1:].isdigit() else 0, m, d["rate"], d["order"])
    for d in sorted(rows, key=key):
        ol = f"{d['order']}, {float(d['limit']):g}" + (" (defaults)" if kind == "defaults" else "")
        pk = os.path.join(work, "music", f"{d['source']}-peaks.json")
        peaks = "–"
        if os.path.exists(pk) and os.path.getsize(pk):
            with open(pk) as f:
                pp = json.load(f)["peaks"]
            peaks = (f"{max(x['wideband_peak_dbsacd'] for x in pp):+.1f} / "
                     f"{max(x['audio_true_peak_dbsacd'] for x in pp):+.1f}")
        chs = d["channels"]
        dur = len(chs[0]["block_error_dbfs"]) * chs[0]["block_s"]
        lim = max((c.get("limited_s") or 0) for c in chs)
        clip = sum((c or {}).get("clipped", 0) for c in d["counters"])
        res = sum((c or {}).get("resets", 0) for c in d["counters"])
        evs = [limiter_events(c) for c in chs]
        ev = max(e[0] for e in evs)
        lg = max(e[1] for e in evs)
        worst = [e[2] for e in evs if e[2] is not None]
        t.append(f"| {d['source']} | {peaks} | DSD{d['rate']} | {ol} | "
                 f"{lim:.3f} ({100 * lim / dur:.3f} %) | {clip} | {res} | {ev} | {lg:.2f} | "
                 f"{fmt(max(worst)) if worst else '–'} | {fmt(max(track_error(c) for c in chs))} |")
    return "\n".join(t)


def try_holds(run):
    t = ["| Output | Order, limit | Clip events, 60 s at 0 dB SACD, 1 / 10 / 20 kHz | Limited samples, 1 / 10 / 20 kHz |",
         "|---|--:|--:|--:|"]
    cfgs = sorted(shown_trials(), key=lambda c: (parse_cfg(c)[0], shown_trials().index(c)))
    for cfg in cfgs:
        hs = [run.r.get((cfg, f"hold{f}k+0.0")) for f in (1, 10, 20)]
        if not any(hs):
            continue
        rr = parse_cfg(cfg)[0]
        ol = trial_label(cfg)
        cl = " / ".join("–" if h is None else str((h["counters"] or {}).get("clipped")) for h in hs)
        li = " / ".join("–" if h is None else str((h["counters"] or {}).get("limited")) for h in hs)
        t.append(f"| DSD{rr} | {ol} | {cl} | {li} |")
    return "\n".join(t)


def fill(doc, work, assets):
    """Replace each <!-- table:NAME --> ... <!-- /table --> block in doc with fresh output."""
    import re as _re
    run = Run(work)
    with open(doc) as f:
        if "assets/measurements/" in f.read():
            plots(run, assets)
    tables = {"summary": lambda: summary(run, True), "summary_full": lambda: summary(run),
              "detail": lambda: detail(run),
              "ultrasonic": lambda: ultra_table(run), "stability": lambda: stability_table(run), "stability_compact": lambda: stability_compact(run),
              "ceiling": lambda: ceiling_table(run), "defaults": lambda: defaults_table(run),
              "trials": lambda: try_holds(run), "hot": lambda: hot_table(run),
              "music": lambda: music_table(work), "music_orders": lambda: music_table(work, "orders"),
              "defaults_main": lambda: defaults_main(run),
              "isp": lambda: isp_table(work), "sweeps": lambda: sweep_table(run),
              "provenance": lambda: provenance(run)}
    with open(doc) as f:
        s = f.read()

    def rep(m):
        return f"<!-- table:{m.group(1)} -->\n{tables[m.group(1)]()}\n<!-- /table -->"
    s = _re.sub(r"<!-- table:(\w+) -->.*?<!-- /table -->", rep, s, flags=_re.S)
    with open(doc, "w") as f:
        f.write(s)
    for n in os.listdir(assets):  # keep only the plots the page uses
        if "assets/measurements/" in s and n.endswith(".svg") and n not in s:
            os.remove(os.path.join(assets, n))


def isp_table(work):
    t = ["| Source rate | Output | Order, limit | Limited | Clip events | Resets | SINAD (dB) |",
         "|---|---|--:|--:|--:|--:|--:|"]
    rows = []
    for p in glob.glob(os.path.join(work, "music", "isp*-o*-l*.json")):
        with open(p) as f:
            d = json.load(f)
        if FINAL[d["rate"]] == (d["order"], float(d["limit"])):
            rows.append(d)
    for d in sorted(rows, key=lambda d: (d["fs"], d["rate"])):
        c = d["counters"][0]
        t.append(f"| {d['fs'] / 1000:g} kHz | DSD{d['rate']} | {d['order']}, {float(d['limit']):g} (defaults) | "
                 f"{c['limited']} | {c['clipped']} | {c['resets']} | {d['tone']['sinad_db']:.1f} |")
    return "\n".join(t)


def sweep_table(run):
    cents = [100, 120, 140, 160, 180, 195]
    lv = [-60, -40, -20, 0]
    t = ["| Encoder | CCIF IMD at pair centre 10 / 12 / 14 / 16 / 18 / 19.5 kHz (dB) "
         "| SMPTE IMD+N at −60 / −40 / −20 / 0 dB SACD (dB) |", "|---|--:|--:|"]
    for cfg in ["pcm24"] + [c for c in configs_main() if "t-" not in c]:
        cc = [run.get(cfg, f"ccif{c}", "analysis", "ccif", "imd_db") for c in cents]
        ss = [run.get(cfg, f"smpte{x}", "analysis", "smpte", "imdn_db") for x in lv]
        if all(v is None for v in cc + ss):
            continue
        t.append(f"| {label(cfg)} | {' / '.join(fmt(v) for v in cc)} | {' / '.join(fmt(v) for v in ss)} |")
    return "\n".join(t)


def stability_compact(run):
    """Per rate, order and limit: 1 kHz holds, clip events and THD+N per level, resets."""
    lv = (0.0, 1.5, 3.1, 4.1, 6.1)
    t = ["| Output | Order | Limit | 1 kHz, 60 s: clip events / THD+N (dB) at 0, +1.5, +3.1, +4.1, +6.1 dB SACD "
         "| Resets, all tones and levels | Max modulation, 28-bit window, at +3.1 dB SACD (%) "
         "| Windows beyond 71.43 % at +3.1 dB SACD |", "|---|--:|--:|---|--:|--:|--:|"]
    for rate in RATES:
        for o in ORDERS:
            cfgs = [(f"dsdup-o{o}-{rate}", None), (f"dsdup-o{o}-{rate}", "1.0")]
            for cfg, lim in cfgs:
                sfx = f"-l{lim}" if lim else ""
                cells, resets = [], 0
                for x in lv:
                    d = run.r.get((cfg, f"hold1k{x:+.1f}{sfx}"))
                    if d is None:
                        cells.append("–")
                        continue
                    c = d["counters"] or {}
                    cells.append(f"{c.get('clipped')} / {d['thdn_first']:.0f}")
                for f in (1, 10, 20):
                    for x in lv:
                        d = run.r.get((cfg, f"hold{f}k{x:+.1f}{sfx}"))
                        if d:
                            resets += (d["counters"] or {}).get("resets", 0)
                d = run.r.get((cfg, f"hold1k+3.1{sfx}"))
                if d is None:
                    continue
                limtxt = lim or DEFAULT_LIMIT
                t.append(f"| DSD{rate} | {o} | {limtxt} | {'; '.join(cells)} | {resets} | "
                         f"{d['density']['max_modulation_pct']:.1f} | {d['density']['windows_over_frac'] * 100:.3g} % |")
    return "\n".join(t)


def defaults_main(run):
    """The defaults table for docs/measurements.md."""
    t = ["| Output | Order | Limit | SINAD at −3 dB SACD, 1 kHz (dB) | Clip events, 60 s at 0 dB SACD, 1 / 10 / 20 kHz "
         "| Excess over an ideal limiter, worst hot input: whole / worst 10 ms (dB re the ideal signal) | Resets |",
         "|---|--:|--:|--:|--:|--:|--:|"]
    for r, (o, lim) in FINAL.items():
        cfg = f"trya-{r}-o{o}-l{lim}"
        sinad = run.get(f"dsdup-o{o}-{r}", "tone-3", "analysis", "tone", "sinad_db")
        holds = [run.r.get((cfg, f"hold{f}k+0.0")) for f in (1, 10, 20)]
        hots = [d for (c, sid), d in run.r.items() if c == cfg and sid.startswith("hot")]
        exw = max((e["excess_db"] for d in hots for e in d.get("excess", [])), default=None)
        ex10 = max((e["excess_worst_window_db"] for d in hots for e in d.get("excess", [])), default=None)
        res = sum((d["counters"] or {}).get("resets", 0) for d in hots + [h for h in holds if h])
        cl = " / ".join("–" if h is None else str((h["counters"] or {}).get("clipped")) for h in holds)
        t.append(f"| DSD{r} | {o} (default) | {lim} | {fmt(sinad)} | {cl} | {fmt(exw)} / {fmt(ex10)} | {res} |")
    return "\n".join(t)


def provenance(run):
    """Versions and SHA-256 of every tool behind the page's results (meta.json)."""
    m = run.meta
    u, x, a = m["dsd_upsample"], m["sox"], m["analysis"]
    d = u["defaults"]
    t = ["| Tool | Version | Source | SHA-256 of the binary |", "|---|---|---|---|",
         f"| dsd-upsample (CLI) | {u['version']} | commit {u['rev'][:12]}; defaults order {d['order']}, "
         f"limit {d['limit']}, gain {d['gain_db']:g} dB | `{u['sha256']}` |",
         f"| SoX-DSD, run as a black box | {x['version']} | {x['source']}; {x['env']} | `{x['sha256']}` |",
         f"| Analysis (tools/measure) | Python {a['python']}, NumPy {a['numpy']}, SciPy {a['scipy']}, "
         f"Matplotlib {a['matplotlib']} | this tree | – |"]
    t.append("")
    mp = os.path.join(run.work, "music", "meta.json")
    if os.path.exists(mp):
        with open(mp) as f:
            mm = json.load(f)
        mu, ma = mm["dsd_upsample"], mm["analysis"]
        t.insert(4, f"| dsd-upsample (CLI), real-music and intersample-over rows | {mu['version']} | "
                    f"commit {mu['rev'][:12]}; measured {mm['date']} on {mm['cpu']}; Python {ma['python']}, "
                    f"NumPy {ma['numpy']}, SciPy {ma['scipy']} | `{mu['sha256']}` |")
    cpu = m["cpu"] or "an unrecorded CPU"
    if m.get("date_dsd_upsample", m["date"]) != m["date"]:
        t.append(f"dsd-upsample rows measured {m['date_dsd_upsample']}, SoX-DSD and PCM rows "
                 f"{m['date']}, on {cpu}.")
    else:
        t.append(f"Measured {m['date']} on {cpu}.")
    return "\n".join(t)
