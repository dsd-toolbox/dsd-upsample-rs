# SPDX-License-Identifier: MIT OR Apache-2.0
"""SVG plots for measurement results: spectra overlays and simple x-y charts.

Spectra are reduced to a fixed number of columns before drawing, so an SVG stays small:
each column draws the mean of the bins in it as the line, and where the largest bin in
the column is more than 6 dB above that mean (a spectral line), a spike up to it. Tones
and distortion products therefore keep their true peak levels, and the noise floor keeps
its true per-bin level.

Style: 9 x 5 in, one colour per series in a fixed order (colour-blind-checked palette),
2 px lines, light grid, the legend always shown for two or more series.

    from plot import spectra, lines
    spectra("out.svg", [("label", f, p_db), ...], xlim=(20, 20000), ylim=(-200, 0), log=True)
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6",
           "#e34948"]
REF_GREY = "#52514e"
plt.rcParams.update({"svg.fonttype": "none", "font.size": 10, "axes.edgecolor": "#8a8984",
                     "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e",
                     "ytick.color": "#52514e", "axes.grid": True, "grid.color": "#e4e3df",
                     "grid.linewidth": 0.6, "axes.spines.top": False,
                     "axes.spines.right": False, "svg.hashsalt": "measure"})


def bucket(f, p_db, lo, hi, cols=700, log=False):
    """Reduce a spectrum (dB per bin) to `cols` columns: (x, mean_db, max_db)."""
    m = (f >= lo) & (f <= hi)
    f, v = f[m], p_db[m]
    edges = np.geomspace(lo, hi, cols + 1) if log else np.linspace(lo, hi, cols + 1)
    idx = np.searchsorted(edges, f, side="right") - 1
    idx = np.clip(idx, 0, cols - 1)
    lin = 10 ** (v / 10)
    cnt = np.bincount(idx, minlength=cols)
    s = np.bincount(idx, weights=lin, minlength=cols)
    mx = np.full(cols, -np.inf)
    np.maximum.at(mx, idx, v)
    ok = cnt > 0
    x = np.sqrt(edges[:-1] * edges[1:]) if log else (edges[:-1] + edges[1:]) / 2
    mean = 10 * np.log10(np.maximum(s[ok] / cnt[ok], 1e-300))
    return x[ok], mean, mx[ok]


def _finish(fig, ax, out, title, note):
    if title:
        ax.set_title(title, loc="left", fontsize=12)
    if note:
        fig.text(0.01, 0.01, note, fontsize=8, color=REF_GREY)
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(out, format="svg", metadata={"Date": None, "Creator": None})
    plt.close(fig)


def spectra(out, series, xlim, ylim, log=True, title=None, ylabel="dBFS", note=None,
            cols=700, xlabel="Frequency (Hz)", hlines=()):
    """Overlay spectra. series: list of (label, f_hz, level_db_per_bin[, colour])."""
    fig, ax = plt.subplots(figsize=(9, 5), dpi=100)
    for i, s in enumerate(series):
        label, f, v = s[:3]
        col = s[3] if len(s) > 3 else PALETTE[i % len(PALETTE)]
        x, mean, mx = bucket(f, v, xlim[0], xlim[1], cols, log)
        ax.plot(x, mean, color=col, lw=1.2, label=label)
        spike = mx > mean + 6
        if np.any(spike):
            ax.vlines(x[spike], mean[spike], mx[spike], color=col, lw=1.0)
    for y, txt in hlines:
        ax.axhline(y, color=REF_GREY, lw=0.8, ls="--")
        ax.text(xlim[0], y, " " + txt, va="bottom", fontsize=8, color=REF_GREY)
    if log:
        ax.set_xscale("log")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if len(series) > 1:
        ax.legend(fontsize=8, loc="upper left", frameon=False, ncol=2)
    _finish(fig, ax, out, title, note)


def lines(out, x, series, xlabel, ylabel, title=None, note=None, xlog=False, ylim=None,
          xticks=None, markers=True, hlines=()):
    """Simple x-y chart. series: list of (label, y_values)."""
    fig, ax = plt.subplots(figsize=(9, 5), dpi=100)
    for i, (label, y) in enumerate(series):
        ax.plot(x, y, color=PALETTE[i % len(PALETTE)], lw=2, label=label,
                marker="o" if markers else None, ms=5)
    for y, txt in hlines:
        ax.axhline(y, color=REF_GREY, lw=0.8, ls="--")
        ax.text(ax.get_xlim()[0], y, " " + txt, va="bottom", fontsize=8, color=REF_GREY)
    if xlog:
        ax.set_xscale("log")
    if xticks is not None:
        ax.set_xticks(xticks[0])
        ax.set_xticklabels(xticks[1])
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if len(series) > 1:
        ax.legend(fontsize=8, frameon=False, ncol=2)
    _finish(fig, ax, out, title, note)
