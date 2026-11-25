# SPDX-License-Identifier: MIT OR Apache-2.0
"""NTF design for the one-bit CRFB modulator (pure NumPy, reproducible).

Method (public literature, see PROVENANCE.md):
- zeros on the unit circle at the roots of the Legendre polynomial scaled to the signal
  band, which minimise the integrated in-band noise (Schreier, IEEE TCAS-II 40(8), 1993;
  Schreier & Temes 2005, sec. 4.3), or at given frequencies;
- poles: the maximally flat all-pole family of the Delta-Sigma Toolbox's synthesizeNTF,
  iterated until the NTF gain at fs/2 equals H_inf (Lee's rule; Schreier & Temes 2005,
  sec. 4.4);
- CRFB coefficients: g from the zero angles, a solved from the pole polynomial using the
  state update of modulator.rs itself, b = [a, 1] (unity signal transfer function).

Nothing here is random and nothing depends on a platform libm beyond NumPy's own
elementary functions; the generated tables are committed as bit patterns.
"""
import numpy as np

BASE = 44100


def legendre_zero_freqs(order, band):
    """Positive zero frequencies (Hz) for the band 0..band; odd orders add one at DC."""
    r = np.sort(np.polynomial.legendre.leggauss(order)[0])
    return [float(x) * band for x in r if x > 1e-12]


def zeros_from_freqs(order, freqs, fs):
    th = 2 * np.pi * np.asarray(sorted(freqs), dtype=np.float64) / fs
    if len(th) != order // 2:
        raise ValueError("need order // 2 zero frequencies")
    z = []
    if order % 2:
        z.append(1.0 + 0j)
    for t in th:
        z += [np.exp(1j * t), np.exp(-1j * t)]
    return np.array(z)


def _gain_at_nyquist(z, p):
    return float(np.real(np.prod(-1.0 - z) / np.prod(-1.0 - p)))


def maxflat_poles(z, hinf, order):
    """Poles of synthesizeNTF's low-pass family with NTF(-1) = hinf (secant iteration)."""
    w = (2 * np.arange(1, order + 1) + 1) * np.pi / order

    def poles(x):
        me2 = -0.5 * x ** (2.0 / order)
        mb2 = 1 + me2 * np.exp(1j * w)
        p = mb2 - np.sqrt(mb2 ** 2 - 1)
        out = np.abs(p) > 1
        p[out] = 1.0 / p[out]
        return p

    # the gain rises monotonically with x: bisect in log x
    lo, hi = -40.0, 10.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _gain_at_nyquist(z, poles(np.exp(mid))) > hinf:
            hi = mid
        else:
            lo = mid
    return poles(np.exp(0.5 * (lo + hi)))


def crfb_linear(order, a, g, b, c):
    """(A, Bu, Bv, C, D) of the recurrence in modulator.rs: x' = A x + Bu u + Bv v,
    y = C x + D u. Built by probing the recurrence, so it is that recurrence."""
    def step(x, u, v):
        n = order
        odd = n % 2
        new = list(x)
        for k in range((n - odd) // 2 - 1, -1, -1):
            p = odd + 2 * k
            q = p + 1
            if p > 0:
                t = (x[p] + c[p - 1] * x[p - 1]) + (b[p] * u - g[k] * x[q])
            else:
                t = x[p] + (b[p] * u - g[k] * x[q])
            t = t - a[p] * v
            s = (x[q] + (b[q] * u - a[q] * v)) + c[p] * t
            new[p], new[q] = t, s
        if odd:
            new[0] = (x[0] + b[0] * u) - a[0] * v
        return np.array(new)

    n = order
    A = np.zeros((n, n))
    for i in range(n):
        e = np.zeros(n)
        e[i] = 1.0
        A[:, i] = step(e, 0.0, 0.0)
    Bu = step(np.zeros(n), 1.0, 0.0)
    Bv = step(np.zeros(n), 0.0, 1.0)
    C = np.zeros(n)
    C[n - 1] = c[n - 1]
    return A, Bu, Bv, C, b[n]


def realize_crfb(z, p, order):
    """Unscaled CRFB (c = 1, b = [a, 1]) with NTF zeros z and poles p."""
    odd = order % 2
    ang = np.sort(np.abs(np.angle(z[np.imag(z) > 1e-15])))
    g = 2.0 - 2.0 * np.cos(ang)
    c = np.ones(order)
    # transfer from a unit a_i to y, at points around z = 1 where zeros and poles live
    rho = 2.0 * max(np.max(np.abs(p - 1.0)), np.max(np.abs(z - 1.0)))
    m = 8 * order
    pts = 1.0 + rho * np.exp(1j * (np.arange(m) + 0.5) * 2 * np.pi / m)
    A0, _, _, C, _ = crfb_linear(order, np.zeros(order), g, np.zeros(order + 1), c)
    T = np.zeros((m, order), dtype=np.complex128)
    for i in range(order):
        ai = np.zeros(order)
        ai[i] = 1.0
        Bv = crfb_linear(order, ai, g, np.zeros(order + 1), c)[2]
        for j, zz in enumerate(pts):
            T[j, i] = C @ np.linalg.solve(zz * np.eye(order) - A0, Bv)
    # NTF = 1 / (1 - L1), L1 = sum a_i T_i  =>  sum a_i T_i = 1 - P/Z
    rhs = np.array([1.0 - np.prod(zz - p) / np.prod(zz - z) for zz in pts])
    M = np.vstack([T.real, T.imag])
    a = np.linalg.lstsq(M, np.concatenate([rhs.real, rhs.imag]), rcond=None)[0]
    b = np.concatenate([a, [1.0]])
    # check: closed-loop poles are the eigenvalues of A + Bv C
    A, _, Bv, C, _ = crfb_linear(order, a, g, b, c)
    got = np.linalg.eigvals(A + np.outer(Bv, C))
    err = max(np.min(np.abs(got - q)) for q in p)
    return dict(a=a, g=g, b=b, c=c, pole_err=float(err))


def realize_crff(z, p, order):
    """Feed-forward form on the same integrator chain: the quantiser error enters the
    first integrator only (a = b = [1, 0, ...]) and y = sum k_i x_i + u. The states do not
    depend on the weights k, so k may change while running."""
    ang = np.sort(np.abs(np.angle(z[np.imag(z) > 1e-15])))
    g = 2.0 - 2.0 * np.cos(ang)
    c = np.ones(order)
    a = np.zeros(order)
    a[0] = 1.0
    b = np.zeros(order + 1)
    b[0] = 1.0
    A, _, Bv, _, _ = crfb_linear(order, a, g, b, c)
    rho = 2.0 * max(np.max(np.abs(p - 1.0)), np.max(np.abs(z - 1.0)))
    m = 8 * order
    pts = 1.0 + rho * np.exp(1j * (np.arange(m) + 0.5) * 2 * np.pi / m)
    # x = (zI - A)^-1 Bv v ; y = k.x ; NTF = 1 / (1 - k.T(z))
    T = np.array([np.linalg.solve(zz * np.eye(order) - A, Bv) for zz in pts])
    rhs = np.array([1.0 - np.prod(zz - p) / np.prod(zz - z) for zz in pts])
    # column scaling: the states are 1..N-fold integrals and differ by many decades
    sc = np.max(np.abs(T), axis=0)
    M = np.vstack([T.real, T.imag]) / sc
    k = np.linalg.lstsq(M, np.concatenate([rhs.real, rhs.imag]), rcond=None)[0] / sc
    got = np.linalg.eigvals(A + np.outer(Bv, k))
    err = max(np.min(np.abs(got - q)) for q in p)
    return dict(a=a, g=g, b=b, c=c, k=k, pole_err=float(err))


def ntf_mag(z, p, f, fs):
    e = np.exp(2j * np.pi * np.asarray(f, dtype=np.float64) / fs)
    num = np.ones(len(e), dtype=np.complex128)
    den = np.ones(len(e), dtype=np.complex128)
    for q in z:
        num *= e - q
    for q in p:
        den *= e - q
    return np.abs(num / den)


def predicted(z, p, fs, amp=0.0):
    """Linear-model noise (dBFS, 100 % modulation = 0 dBFS) with white quantisation
    noise of power 1 - amp^2/2 over fs/2; only a guide (the simulations decide)."""
    out = {}
    q = max(1.0 - amp * amp / 2, 1e-3)
    for name, lo, hi in (("n20_20k", 20, 20000), ("u22_96", 22000, 96000),
                         ("u100_192", 100000, 192000)):
        f = np.linspace(lo, hi, 20001)
        h2 = ntf_mag(z, p, f, fs) ** 2
        pw = q * float(np.sum(0.5 * (h2[1:] + h2[:-1]) * np.diff(f))) / (fs / 2)
        out[name] = float(10 * np.log10(pw / 0.5))
    return out


def design(rate_mult, order, hinf, band=None, freqs=None, form="crfb"):
    """One candidate. band: Legendre zeros over 0..band Hz; freqs: explicit zero pairs."""
    fs = BASE * rate_mult
    if freqs is None:
        freqs = legendre_zero_freqs(order, band)
    z = zeros_from_freqs(order, freqs, fs)
    p = maxflat_poles(z, hinf, order)
    r = realize_crfb(z, p, order) if form == "crfb" else realize_crff(z, p, order)
    imp = _impulse(z, p, 4096)
    return dict(rate=rate_mult, order=order, hinf=hinf, zero_hz=[float(x) for x in freqs],
                z=z, p=p, l1norm=float(np.sum(np.abs(imp))), pred=predicted(z, p, fs), **r)


# The audio-band family of the library (tables.rs, band "audio"): Legendre zeros over
# 0..AUDIO_BAND Hz and the H_inf below per (DSD rate multiple, order). The values are the
# result of docs/modulator-design.md.
AUDIO_BAND = 20000.0
AUDIO_HINF = {(r, o): {5: 1.38, 6: 1.36, 7: 1.36, 8: 1.35}[o]
              for r in (64, 128, 256) for o in (5, 6, 7, 8)}
AUDIO_HINF[(128, 8)] = 1.30


def audio_design(rate_mult, order):
    return design(rate_mult, order, AUDIO_HINF[(rate_mult, order)], AUDIO_BAND)


def scaled(d, exp):
    """Coefficients for states divided by 2**exp[i] (exact: powers of two)."""
    n = len(d["a"])
    m = [2.0 ** e for e in exp]
    a = np.array([d["a"][i] / m[i] for i in range(n)])
    b = np.array([d["b"][i] / m[i] for i in range(n)] + [d["b"][n]])
    c = np.array([d["c"][i] * m[i] / m[i + 1] for i in range(n - 1)] + [d["c"][n - 1] * m[n - 1]])
    odd = n % 2
    g = np.array([d["g"][k] * m[odd + 2 * k + 1] / m[odd + 2 * k] for k in range(n // 2)])
    return dict(a=a, g=g, b=b, c=c)


def _impulse(z, p, n):
    num = np.real(np.poly(z))
    den = np.real(np.poly(p))
    h = np.zeros(n)
    x = np.zeros(n)
    x[0] = 1.0
    for i in range(n):
        acc = sum(num[k] * x[i - k] for k in range(len(num)) if i - k >= 0)
        acc -= sum(den[k] * h[i - k] for k in range(1, len(den)) if i - k >= 0)
        h[i] = acc
    return h


if __name__ == "__main__":
    for rate, order, hinf, band in ((128, 6, 1.5, 50000.0), (256, 7, 1.5, 80000.0),
                                    (128, 8, 1.5, 22050.0), (256, 8, 1.5, 22050.0),
                                    (256, 6, 1.4, 30000.0)):
        d = design(rate, order, hinf, band)
        print(rate, order, hinf, band, "pole_err %.2e" % d["pole_err"], "l1 %.3f" % d["l1norm"],
              d["pred"], "\n  a", np.round(d["a"], 6), "\n  g", d["g"])
