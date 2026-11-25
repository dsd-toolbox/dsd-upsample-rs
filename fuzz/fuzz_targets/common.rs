// SPDX-License-Identifier: MIT OR Apache-2.0
// Shared by the fuzz targets: settings and sizes taken from the fuzzer's bytes.
#![allow(dead_code)]

use dsd_upsample::{InputFormat, Options, Output};

pub struct Bytes<'a>(pub &'a [u8]);

impl Bytes<'_> {
    pub fn u8(&mut self) -> u8 {
        let (b, rest) = self.0.split_first().map_or((0, &[][..]), |(b, r)| (*b, r));
        self.0 = rest;
        b
    }
    pub fn u16(&mut self) -> u16 {
        u16::from(self.u8()) | (u16::from(self.u8()) << 8)
    }
    pub fn take(&mut self, n: usize) -> &[u8] {
        let n = n.min(self.0.len());
        let (a, b) = self.0.split_at(n);
        self.0 = b;
        a
    }
}

/// Settings, mostly valid but sometimes not (errors are fine, panics are not).
pub fn options(b: &mut Bytes<'_>) -> Options {
    let mult = [128, 256, 64, 512][usize::from(b.u8() % 4)];
    let mut o = Options::new(Output::Dsd { mult });
    o.order = usize::from(b.u8() % 10);
    o.gain_db = [-3.0, 0.0, 24.0, -120.0, 6.0, f64::NAN, 30.0, -200.0][usize::from(b.u8() % 8)];
    o.input_limit = [None, Some(0.6), Some(0.1), Some(1.0), Some(0.0), Some(f64::NAN)]
        [usize::from(b.u8() % 6)];
    o.dither = b.u8() % 2 == 1;
    o.threads = b.u8() % 2 == 1;
    o.cutoff = [
        None,
        Some(dsd_upsample::dsd2pcm::Cutoff::Low),
        Some(dsd_upsample::dsd2pcm::Cutoff::Standard),
        Some(dsd_upsample::dsd2pcm::Cutoff::Wide),
    ][usize::from(b.u8() % 4)];
    o
}

pub fn format(b: &mut Bytes<'_>) -> InputFormat {
    let dsd = [2_822_400, 5_644_800, 11_289_600, 0, 44_100];
    let pcm = [
        44_100, 88_200, 176_400, 352_800, 48_000, 96_000, 192_000, 384_000, 32_000, 0,
    ];
    if b.u8() % 2 == 0 {
        InputFormat::Dsd { rate: dsd[usize::from(b.u8()) % dsd.len()] }
    } else {
        InputFormat::Pcm { rate: pcm[usize::from(b.u8()) % pcm.len()] }
    }
}
