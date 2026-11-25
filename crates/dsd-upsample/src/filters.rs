// SPDX-License-Identifier: MIT OR Apache-2.0
//! Decimation and interpolation filters driven by the tables in `tables.rs`.
//!
//! All arithmetic is scalar `f64` with a fixed summation order and no fused multiply-add.

/// One polyphase branch: `taps[j]` multiplies `x[n - offset - j]`.
#[derive(Debug)]
pub(crate) struct PhaseTable {
    pub offset: usize,
    pub taps: &'static [u64],
}

/// A x2 interpolator: output `2n + p` is phase `p` applied at input `n`.
#[derive(Debug)]
pub(crate) struct InterpTable {
    pub out_rate: u32,
    /// Group delay in output samples.
    pub delay: usize,
    pub phases: [PhaseTable; 2],
}

/// A byte-LUT FIR decimator from a DSD rate to 352.8 kHz.
#[derive(Debug)]
pub(crate) struct DecimTable {
    #[allow(dead_code)]
    pub in_rate: u32,
    pub ratio: usize,
    /// Centre tap index (a multiple of 8).
    pub center: usize,
    /// Taps, zero-padded to a multiple of 8.
    pub taps: &'static [u64],
}

/// CRFB modulator coefficients (Schreier's naming).
#[derive(Debug)]
pub(crate) struct ModTable {
    pub order: usize,
    /// Largest stable DC input found when the table was designed.
    #[allow(dead_code)]
    pub umax: u64,
    pub a: &'static [u64],
    pub g: &'static [u64],
    pub b: &'static [u64],
    pub c: &'static [u64],
}

pub(crate) fn f64s(bits: &[u64]) -> Vec<f64> {
    bits.iter().map(|&b| f64::from_bits(b)).collect()
}

/// DSD silence pattern used before the input and after its end.
pub(crate) const IDLE: u8 = 0x69;

/// Byte-LUT FIR decimator (distributed arithmetic): `y[m] = sum_j lut[j][byte[m*step + j]]`.
/// The history starts with `center / 8` idle bytes, so output `m` is centred on input
/// sample `m * ratio`: no delay.
#[derive(Debug)]
pub(crate) struct Decimator {
    lut: Vec<[f64; 256]>,
    step: usize,
    hist: Vec<u8>,
    pos: usize,
}

impl Decimator {
    pub(crate) fn new(t: &DecimTable) -> Decimator {
        let taps = f64s(t.taps);
        let k = taps.len() / 8;
        let mut lut = vec![[0.0f64; 256]; k];
        for (j, table) in lut.iter_mut().enumerate() {
            for (v, e) in table.iter_mut().enumerate() {
                let mut s = 0.0f64;
                for bit in 0..8 {
                    let w = taps[8 * j + bit];
                    s = if (v >> (7 - bit)) & 1 == 1 {
                        s + w
                    } else {
                        s - w
                    };
                }
                *e = s;
            }
        }
        Decimator {
            lut,
            step: t.ratio / 8,
            hist: vec![IDLE; t.center / 8],
            pos: 0,
        }
    }

    pub(crate) fn push(&mut self, input: &[u8], out: &mut Vec<f64>) {
        self.hist.extend_from_slice(input);
        let k = self.lut.len();
        while self.pos + k <= self.hist.len() {
            let w = &self.hist[self.pos..self.pos + k];
            let mut s = 0.0f64;
            for (t, &b) in self.lut.iter().zip(w) {
                s += t[usize::from(b)];
            }
            out.push(s);
            self.pos += self.step;
        }
        let drop = self.pos.min(self.hist.len());
        self.hist.drain(..drop);
        self.pos -= drop;
    }
}

/// x2 polyphase interpolator; starts with zero history, so it delays by `delay` samples.
#[derive(Debug)]
pub(crate) struct Interpolator {
    phases: [(usize, Vec<f64>); 2],
    span: usize,
    hist: Vec<f64>,
}

impl Interpolator {
    pub(crate) fn new(t: &InterpTable) -> Interpolator {
        let phases = [
            (t.phases[0].offset, f64s(t.phases[0].taps)),
            (t.phases[1].offset, f64s(t.phases[1].taps)),
        ];
        let span = phases.iter().map(|(o, t)| o + t.len()).max().unwrap_or(1);
        Interpolator {
            phases,
            span,
            hist: vec![0.0; span - 1],
        }
    }

    pub(crate) fn process(&mut self, input: &[f64], out: &mut Vec<f64>) {
        let h = self.span - 1;
        self.hist.extend_from_slice(input);
        let m = input.len();
        let start = out.len();
        out.resize(start + 2 * m, 0.0);
        let dst = &mut out[start..];
        for (p, (off, taps)) in self.phases.iter().enumerate() {
            phase(taps, h - off, &self.hist, m, p, dst);
        }
        let keep_from = self.hist.len() - h;
        self.hist.drain(..keep_from);
    }
}

/// `dst[2n + p] = sum_j taps[j] * x[base + n - j]` for `n < m`, each sum in ascending `j`.
/// Eight outputs are computed side by side (independent sums, so the order within each sum
/// is unchanged); this only hides the latency of the dependent additions.
#[inline(always)]
fn phase(taps: &[f64], base: usize, x: &[f64], m: usize, p: usize, dst: &mut [f64]) {
    const B: usize = 8;
    let mut n = 0;
    while n + B <= m {
        let mut acc = [0.0f64; B];
        for (j, &t) in taps.iter().enumerate() {
            let w = &x[base + n - j..base + n - j + B];
            for k in 0..B {
                acc[k] += t * w[k];
            }
        }
        for k in 0..B {
            dst[2 * (n + k) + p] = acc[k];
        }
        n += B;
    }
    while n < m {
        let mut s = 0.0f64;
        for (j, &t) in taps.iter().enumerate() {
            s += t * x[base + n - j];
        }
        dst[2 * n + p] = s;
        n += 1;
    }
}

/// The prototype lowpass of a rational resampler, at `up` x the input rate: odd length
/// `2 * center + 1`, symmetric, stored as its first `center + 1` taps.
#[derive(Debug)]
pub(crate) struct ResampleTable {
    pub up: usize,
    pub center: usize,
    pub half: &'static [u64],
}

/// Synchronous rational resampler by `up / down` (polyphase FIR). Output `m` is centred on
/// input time `m * down / up` once the delay of `center / down` output samples is removed:
/// it starts with zero history, like [`Interpolator`].
///
/// Output `m` is `sum_j phase[p][j] * x[n - j]` with `n = floor(m * down / up)` and
/// `p = (m * down) mod up`, each sum in ascending `j` (`tools/gen_resampler.py` computes
/// its reference vector in the same order).
#[derive(Debug)]
pub(crate) struct Resampler {
    /// `phases[p * k + j]` is prototype tap `p + j * up` (zero past the end).
    phases: Vec<f64>,
    k: usize,
    up: usize,
    down: usize,
    /// Input history: `k - 1` samples before the next output's newest input, and after.
    hist: Vec<f64>,
    /// Index in `hist` of the next output's newest input sample.
    pos: usize,
    /// Phase of the next output.
    p: usize,
}

impl Resampler {
    pub(crate) fn new(t: &ResampleTable, down: usize) -> Resampler {
        let n = 2 * t.center + 1;
        let tap = |i: usize| -> f64 {
            if i < n {
                f64::from_bits(t.half[if i <= t.center { i } else { n - 1 - i }])
            } else {
                0.0
            }
        };
        let k = n.div_ceil(t.up);
        let mut phases = vec![0.0; t.up * k];
        for p in 0..t.up {
            for j in 0..k {
                phases[p * k + j] = tap(p + j * t.up);
            }
        }
        Resampler {
            phases,
            k,
            up: t.up,
            down,
            hist: vec![0.0; k - 1],
            pos: k - 1,
            p: 0,
        }
    }

    /// Group delay in output samples (whole, because the table's centre is a multiple of
    /// `down`).
    pub(crate) fn delay(t: &ResampleTable, down: usize) -> usize {
        debug_assert_eq!(t.center % down, 0);
        t.center / down
    }

    pub(crate) fn process(&mut self, input: &[f64], out: &mut Vec<f64>) {
        const B: usize = 4;
        self.hist.extend_from_slice(input);
        let k = self.k;
        let len = self.hist.len();
        // Up to B outputs side by side (independent sums, each in ascending j).
        let mut pos = [0usize; B];
        let mut ph = [0usize; B];
        loop {
            let mut nb = 0;
            while nb < B && self.pos < len {
                pos[nb] = self.pos;
                ph[nb] = self.p * k;
                nb += 1;
                self.p += self.down;
                self.pos += self.p / self.up;
                self.p %= self.up;
            }
            if nb == B {
                let t: [&[f64]; B] = std::array::from_fn(|i| &self.phases[ph[i]..ph[i] + k]);
                let x: [&[f64]; B] = std::array::from_fn(|i| &self.hist[pos[i] + 1 - k..=pos[i]]);
                let mut acc = [0.0f64; B];
                for j in 0..k {
                    for i in 0..B {
                        acc[i] += t[i][j] * x[i][k - 1 - j];
                    }
                }
                out.extend_from_slice(&acc);
            } else {
                for i in 0..nb {
                    let taps = &self.phases[ph[i]..ph[i] + k];
                    let x = &self.hist[pos[i] + 1 - k..=pos[i]];
                    let mut s = 0.0f64;
                    for (t, v) in taps.iter().zip(x.iter().rev()) {
                        s += t * v;
                    }
                    out.push(s);
                }
                break;
            }
        }
        let drop = self.pos + 1 - k;
        let drop = drop.min(self.hist.len());
        self.hist.drain(..drop);
        self.pos -= drop;
    }
}

#[cfg(test)]
mod resampler_tests {
    use super::*;
    use crate::resample_table::RESAMPLE_147;

    mod reference {
        include!("../tests/data/resample_ref.rs");
    }

    fn input() -> Vec<f64> {
        (0..reference::RESAMPLE_REF_IN)
            .map(|i| (((i * 37) % 101) as f64 - 50.0) / 64.0)
            .collect()
    }

    /// Bit-identical to tools/gen_resampler.py's reference (same taps, same summation
    /// order), which agrees with SciPy's upfirdn to 2.4e-15.
    #[test]
    fn matches_python_reference() {
        let mut r = Resampler::new(&RESAMPLE_147, 160);
        let mut out = Vec::new();
        r.process(&input(), &mut out);
        assert!(out.len() >= reference::RESAMPLE_REF_OUT.len());
        for (m, (&got, &want)) in out.iter().zip(&reference::RESAMPLE_REF_OUT).enumerate() {
            assert_eq!(
                got.to_bits(),
                want,
                "output {m}: {got} vs {}",
                f64::from_bits(want)
            );
        }
    }

    /// The split into pushes does not change any output bit.
    #[test]
    fn chunking_does_not_matter() {
        let x = input();
        let mut whole = Vec::new();
        Resampler::new(&RESAMPLE_147, 160).process(&x, &mut whole);
        for sizes in [&[1usize][..], &[3, 7, 160, 1], &[147], &[1000, 1, 2]] {
            let mut r = Resampler::new(&RESAMPLE_147, 160);
            let mut out = Vec::new();
            let (mut i, mut k) = (0, 0);
            while i < x.len() {
                let n = sizes[k % sizes.len()].min(x.len() - i);
                r.process(&x[i..i + n], &mut out);
                i += n;
                k += 1;
            }
            assert_eq!(out.len(), whole.len());
            assert!(out
                .iter()
                .zip(&whole)
                .all(|(a, b)| a.to_bits() == b.to_bits()));
        }
    }

    /// Output count: ceil(n * 147 / 160) for n inputs (output m needs input
    /// floor(m * 160 / 147)); DC passes at unity after the delay; the delay is whole.
    #[test]
    fn length_dc_and_delay() {
        let n = 48_000usize;
        let mut out = Vec::new();
        let mut r = Resampler::new(&RESAMPLE_147, 160);
        r.process(&vec![0.25; n], &mut out);
        assert_eq!(out.len(), (n * 147).div_ceil(160));
        let d = Resampler::delay(&RESAMPLE_147, 160);
        assert_eq!(d, 182);
        for &v in &out[2 * d + 10..out.len() - 10] {
            assert!((v - 0.25).abs() < 1e-12, "{v}");
        }
    }
}
