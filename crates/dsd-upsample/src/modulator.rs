// SPDX-License-Identifier: MIT OR Apache-2.0
//! One-bit sigma-delta modulator: cascade of resonators with distributed feedback (CRFB).
//!
//! Structure and coefficient naming follow Schreier & Temes, "Understanding Delta-Sigma
//! Data Converters" (2005), and the CRFB form of the Delta-Sigma Toolbox (`stuffABCD`):
//! integrators in pairs, the second of each pair a delaying integrator fed from the first's
//! new value, a resonator feedback `-g` from the second to the first, feed-in `b`, feedback
//! `a` from the quantiser output and inter-stage gains `c`. The coefficients are designed
//! and scaled offline (tools/gen_tables.py); `tools/gen_tables.py` also checks this exact
//! operation order against the toolbox's own simulator.
//!
//! Overload handling: the input is hard-limited, every state is clipped to `STATE_CLIP`,
//! and if clipping persists for `RESET_RUN` consecutive samples the states are reset to 0.
//! Each event is counted.

use crate::filters::{f64s, ModTable};

/// Integrator state bound. The scaled states stay within +-1 for stable inputs.
pub const STATE_CLIP: f64 = 1.5;
/// Consecutive samples with clipped states that trigger a reset.
pub const RESET_RUN: u32 = 64;

/// Overload counters of one channel.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Counters {
    /// Input samples hard-limited to the stable range.
    pub limited: u64,
    /// Samples in which at least one integrator state was clipped.
    pub clipped: u64,
    /// Modulator resets after sustained clipping.
    pub resets: u64,
}

impl Counters {
    /// Adds another channel's counts.
    pub fn add(&mut self, o: &Counters) {
        self.limited += o.limited;
        self.clipped += o.clipped;
        self.resets += o.resets;
    }
}

/// CRFB modulator, orders 5 to 8.
#[derive(Clone, Debug)]
pub struct Modulator {
    order: usize,
    a: [f64; 8],
    g: [f64; 4],
    b: [f64; 9],
    c: [f64; 8],
    x: [f64; 8],
    limit: f64,
    run: u32,
    /// Counts so far.
    pub counters: Counters,
}

impl Modulator {
    pub(crate) fn new(t: &ModTable, limit: f64) -> Modulator {
        let mut m = Modulator {
            order: t.order,
            a: [0.0; 8],
            g: [0.0; 4],
            b: [0.0; 9],
            c: [0.0; 8],
            x: [0.0; 8],
            limit,
            run: 0,
            counters: Counters::default(),
        };
        m.a[..t.order].copy_from_slice(&f64s(t.a));
        m.g[..t.order / 2].copy_from_slice(&f64s(t.g));
        m.b[..=t.order].copy_from_slice(&f64s(t.b));
        m.c[..t.order].copy_from_slice(&f64s(t.c));
        m
    }

    /// Modulates `u` and appends one bit per sample (`true` = +1) through `emit`.
    pub fn run(&mut self, u: &[f64], emit: &mut impl FnMut(bool)) {
        match self.order {
            5 => self.run_n::<5>(u, emit),
            6 => self.run_n::<6>(u, emit),
            7 => self.run_n::<7>(u, emit),
            _ => self.run_n::<8>(u, emit),
        }
    }

    #[inline(always)]
    fn run_n<const N: usize>(&mut self, u: &[f64], emit: &mut impl FnMut(bool)) {
        let (a, g, b, c) = (self.a, self.g, self.b, self.c);
        let mut x = self.x;
        let lim = self.limit;
        for &u0 in u {
            // Out of range or not a number: limited (NaN to 0); finite input in range
            // passes unchanged.
            let u = if u0.abs() <= lim {
                u0
            } else {
                self.counters.limited += 1;
                if u0 > 0.0 {
                    lim
                } else if u0 < 0.0 {
                    -lim
                } else {
                    0.0
                }
            };
            let y = c[N - 1] * x[N - 1] + b[N] * u;
            let bit = y >= 0.0;
            // Both possible next states are computed before the comparison is known, then
            // one is selected without a branch: the same operations as a direct update, but
            // off the loop's critical path.
            let xp = step::<N>(&x, u, 1.0, &a, &g, &b, &c);
            let xm = step::<N>(&x, u, -1.0, &a, &g, &b, &c);
            let mask = 0u64.wrapping_sub(u64::from(bit));
            for i in 0..N {
                x[i] = f64::from_bits((xp[i].to_bits() & mask) | (xm[i].to_bits() & !mask));
            }
            let mut clipped = false;
            for s in x.iter_mut().take(N) {
                if s.abs() > STATE_CLIP {
                    *s = STATE_CLIP.copysign(*s);
                    clipped = true;
                }
            }
            if clipped {
                self.counters.clipped += 1;
                self.run += 1;
                if self.run >= RESET_RUN {
                    x = [0.0; 8];
                    self.run = 0;
                    self.counters.resets += 1;
                }
            } else {
                self.run = 0;
            }
            emit(bit);
        }
        self.x = x;
    }
}

/// One CRFB state update for quantiser output `v` (+-1), in the operation order of
/// tools/gen_tables.py's reference.
#[inline(always)]
#[allow(clippy::assign_op_pattern, clippy::too_many_arguments)]
fn step<const N: usize>(
    x: &[f64; 8],
    u: f64,
    v: f64,
    a: &[f64; 8],
    g: &[f64; 4],
    b: &[f64; 9],
    c: &[f64; 8],
) -> [f64; 8] {
    let odd = N % 2;
    let mut n = *x;
    // resonator pairs, last first, so that each reads its predecessor's old state
    let mut k = (N - odd) / 2;
    while k > 0 {
        k -= 1;
        let p = odd + 2 * k;
        let q = p + 1;
        // grouped so that the loop-carried dependency chain is short
        let mut t = if p > 0 {
            (x[p] + c[p - 1] * x[p - 1]) + (b[p] * u - g[k] * x[q])
        } else {
            x[p] + (b[p] * u - g[k] * x[q])
        };
        t = t - a[p] * v;
        let s = (x[q] + (b[q] * u - a[q] * v)) + c[p] * t;
        n[p] = t;
        n[q] = s;
    }
    if odd == 1 {
        n[0] = (x[0] + b[0] * u) - a[0] * v;
    }
    n
}

#[cfg(test)]
mod tests {
    use super::*;

    mod reference {
        include!("../tests/data/crfb_ref.rs");
    }
    mod audio_reference {
        include!("../tests/data/crfb_audio_ref.rs");
    }

    fn pack(m: &mut Modulator, u: &[f64]) -> Vec<u8> {
        let mut bytes = Vec::new();
        let (mut acc, mut n) = (0u8, 0);
        m.run(u, &mut |b| {
            acc = (acc << 1) | u8::from(b);
            n += 1;
            if n == 8 {
                bytes.push(acc);
                acc = 0;
                n = 0;
            }
        });
        bytes
    }

    /// The audio-band tables (tools/modulator/design.py, states scaled by powers of two)
    /// match the generator's reference too.
    #[test]
    fn audio_table_matches_python_reference() {
        use audio_reference::*;
        let t = crate::tables::modulator(CRFB_AUDIO_REF_RATE, CRFB_AUDIO_REF_ORDER, false).unwrap();
        let mut m = Modulator::new(t, 1.0);
        let u: Vec<f64> = (0..8192)
            .map(|i| ((i % 97) as f64 - 48.0) / 128.0)
            .collect();
        assert_eq!(pack(&mut m, &u), CRFB_AUDIO_REF_BITS.to_vec());
        assert_eq!(m.counters, Counters::default());
    }

    /// The recurrence matches the generator's Python reference bit for bit (which in turn
    /// matches the toolbox simulator); see tools/gen_tables.py.
    #[test]
    fn matches_python_reference() {
        use reference::*;
        let t = crate::tables::modulator(CRFB_REF_RATE, CRFB_REF_ORDER, true).unwrap();
        let mut m = Modulator::new(t, 1.0);
        let u: Vec<f64> = (0..8192)
            .map(|i| ((i % 97) as f64 - 48.0) / 128.0)
            .collect();
        let mut bytes = Vec::new();
        let (mut acc, mut n) = (0u8, 0);
        m.run(&u, &mut |b| {
            acc = (acc << 1) | u8::from(b);
            n += 1;
            if n == 8 {
                bytes.push(acc);
                acc = 0;
                n = 0;
            }
        });
        assert_eq!(bytes, CRFB_REF_BITS.to_vec());
        assert_eq!(m.counters, Counters::default());
    }

    /// Driving every design far past full scale stays bounded and is counted.
    #[test]
    fn overload_is_limited_and_counted() {
        for (mult, order, wide) in (5..=8).flat_map(|o| {
            [64, 128, 256]
                .into_iter()
                .flat_map(move |m| [(m, o, false), (m, o, true)])
        }) {
            {
                let t = crate::tables::modulator(mult, order, wide).unwrap();
                let mut m = Modulator::new(t, 0.6);
                let u: Vec<f64> = (0..200_000)
                    .map(|i| if (i / 5000) % 2 == 0 { 2.0 } else { -2.0 })
                    .collect();
                let mut ones = 0u64;
                m.run(&u, &mut |b| ones += u64::from(b));
                assert!(m.counters.limited > 0);
                assert!(m.x.iter().all(|v| v.is_finite() && v.abs() <= STATE_CLIP));
                assert!(ones > 0 && ones < 200_000);
            }
        }
    }
}
