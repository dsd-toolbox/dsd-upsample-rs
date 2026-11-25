/* SPDX-License-Identifier: MIT OR Apache-2.0
 * Study simulator for the CRFB modulator: the recurrence of crates/dsd-upsample/src/
 * modulator.rs in the same operation order (build with -ffp-contract=off), plus state
 * statistics and built-in test inputs. Not part of the library. */
#include <math.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    int n;
    double a[8], g[4], b[9], c[8], x[8];
    double k[8];      /* feed-forward weights (ff != 0): y = sum k_i x_i + u */
    int ff;
    double clip[8];   /* per-state clip level (inf: none) */
    double blow;      /* |state| / clip ratio counted as blow-up when clip is inf: abs level */
    double xmax[8];   /* largest |state| seen (before clipping) */
    double ymax;      /* largest |quantiser input| */
    int64_t clipped, resets, blowups, limited;
    int run, reset_run;
    double limit;
    uint64_t rng;
    double phase;
} dsm_t;

static inline void step(const dsm_t *s, const double *x, double u, double v, double *n)
{
    int N = s->n, odd = N % 2;
    for (int i = 0; i < N; i++) n[i] = x[i];
    for (int k = (N - odd) / 2 - 1; k >= 0; k--) {
        int p = odd + 2 * k, q = p + 1;
        double t;
        if (p > 0)
            t = (x[p] + s->c[p - 1] * x[p - 1]) + (s->b[p] * u - s->g[k] * x[q]);
        else
            t = x[p] + (s->b[p] * u - s->g[k] * x[q]);
        t = t - s->a[p] * v;
        double w = (x[q] + (s->b[q] * u - s->a[q] * v)) + s->c[p] * t;
        n[p] = t;
        n[q] = w;
    }
    if (odd) n[0] = (x[0] + s->b[0] * u) - s->a[0] * v;
}

static inline int one(dsm_t *s, double u0)
{
    int N = s->n;
    double u = u0;
    if (!(fabs(u0) <= s->limit)) {
        s->limited++;
        u = u0 > 0 ? s->limit : (u0 < 0 ? -s->limit : 0.0);
    }
    double y;
    if (s->ff) {
        y = 0.0;
        for (int i = N - 1; i >= 0; i--) y += s->k[i] * s->x[i];
        y += u;
    } else
        y = s->c[N - 1] * s->x[N - 1] + s->b[N] * u;
    int bit = y >= 0.0;
    if (fabs(y) > s->ymax) s->ymax = fabs(y);
    double nx[8];
    step(s, s->x, u, bit ? 1.0 : -1.0, nx);
    int clipped = 0, blown = 0;
    for (int i = 0; i < N; i++) {
        double m = fabs(nx[i]);
        if (m > s->xmax[i]) s->xmax[i] = m;
        if (m > s->clip[i]) {
            nx[i] = nx[i] > 0 ? s->clip[i] : -s->clip[i];
            clipped = 1;
        }
        if (!(m <= s->blow)) blown = 1;
        s->x[i] = nx[i];
    }
    if (blown) {
        s->blowups++;
        for (int i = 0; i < N; i++) s->x[i] = 0.0;
    }
    if (clipped) {
        s->clipped++;
        if (++s->run >= s->reset_run) {
            for (int i = 0; i < N; i++) s->x[i] = 0.0;
            s->run = 0;
            s->resets++;
        }
    } else
        s->run = 0;
    return bit;
}

/* u[] in, bits[] out (0/1 per sample; may be NULL) */
void dsm_run(dsm_t *s, const double *u, unsigned char *bits, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        int b = one(s, u[i]);
        if (bits) bits[i] = (unsigned char)b;
    }
}

static inline double urand(dsm_t *s)
{ /* SplitMix64 -> uniform in [-1, 1) */
    uint64_t z = (s->rng += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    z ^= z >> 31;
    return (double)(z >> 11) * (1.0 / 4503599627370496.0) - 1.0;
}

/* Built-in inputs, n samples, amplitude amp, normalised frequency fn (cycles/sample):
 * 0 DC, 1 sine, 2 square, 3 uniform white noise held for `hold` samples (hold = fn),
 * 4 random +-amp held for fn samples, 5 sine + DC (dc in aux), 6 two sines (aux = second fn).
 * ramp0 < 0: constant amplitude, returns n. Otherwise the amplitude rises linearly from
 * ramp0 * amp to amp over the run and the run stops at the first blow-up (returns its index). */
int64_t dsm_gen(dsm_t *s, int kind, double amp0, double fn, double aux, int64_t n, double ramp0)
{
    double held = 0.0;
    int64_t hold = (int64_t)fn, left = 0;
    double ph2 = 0.0;
    for (int64_t i = 0; i < n; i++) {
        double u, amp = amp0;
        if (ramp0 >= 0.0) amp = amp0 * (ramp0 + (1.0 - ramp0) * (double)i / (double)n);
        switch (kind) {
        case 0: u = amp; break;
        case 1: u = amp * sin(6.283185307179586 * s->phase); break;
        case 2: u = s->phase < 0.5 ? amp : -amp; break;
        case 3: if (left-- <= 0) { held = amp * urand(s); left = hold - 1; } u = held; break;
        case 4: if (left-- <= 0) { held = urand(s) < 0 ? -amp : amp; left = hold - 1; } u = held; break;
        case 5: u = aux + amp * sin(6.283185307179586 * s->phase); break;
        case 6: u = 0.5 * amp * (sin(6.283185307179586 * s->phase) + sin(6.283185307179586 * ph2));
                ph2 += aux; if (ph2 >= 1.0) ph2 -= 1.0; break;
        default: u = amp; break;
        }
        if (kind == 1 || kind == 2 || kind == 5 || kind == 6) {
            s->phase += fn;
            if (s->phase >= 1.0) s->phase -= 1.0;
        }
        int64_t before = s->blowups;
        one(s, u);
        if (ramp0 >= 0.0 && s->blowups != before) return i;
    }
    return n;
}
