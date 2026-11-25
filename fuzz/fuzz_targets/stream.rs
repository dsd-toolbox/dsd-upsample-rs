// SPDX-License-Identifier: MIT OR Apache-2.0
// Stream with arbitrary settings, channel counts and push sizes: never panics.
#![no_main]
use libfuzzer_sys::fuzz_target;
mod common;
use common::Bytes;
use dsd_upsample::{InputFormat, Stream};

fuzz_target!(|data: &[u8]| {
    let mut b = Bytes(data);
    let o = common::options(&mut b);
    let fmt = common::format(&mut b);
    let ch = u16::from(b.u8() % 8);
    let Ok(mut s) = Stream::new(fmt, ch, &o) else { return };
    let mut emit = |out: &[Vec<u8>]| {
        assert!(out.windows(2).all(|w| w[0].len() == w[1].len()));
        Ok(())
    };
    let mut pushes = 0;
    while !b.0.is_empty() && pushes < 64 {
        pushes += 1;
        let n = usize::from(b.u16() % 2048);
        // Sometimes the wrong channel count or unequal lengths.
        let nch = if b.u8() % 16 == 0 { usize::from(ch) + 1 } else { usize::from(ch) };
        let skew = usize::from(b.u8() % 32 == 0);
        let raw = b.take(n).to_vec();
        match fmt {
            InputFormat::Dsd { .. } => {
                let chans: Vec<Vec<u8>> =
                    (0..nch).map(|c| raw[..raw.len().saturating_sub(skew * c)].to_vec()).collect();
                let refs: Vec<&[u8]> = chans.iter().map(|c| &c[..]).collect();
                let _ = s.push_dsd(&refs, &mut emit);
            }
            InputFormat::Pcm { .. } => {
                let x: Vec<f64> = raw
                    .chunks(2)
                    .map(|p| match p {
                        [0xFF, 0xFF] => f64::NAN,
                        [0xFF, 0xFE] => f64::INFINITY,
                        [a, c] => (f64::from(u16::from(*a) | u16::from(*c) << 8) - 32768.0) / 16384.0,
                        _ => 0.0,
                    })
                    .collect();
                let chans: Vec<&[f64]> =
                    (0..nch).map(|c| &x[..x.len().saturating_sub(skew * c)]).collect();
                let _ = s.push_pcm(&chans, &mut emit);
            }
        }
    }
    // End with finish() or finish_exact() and a fuzzed count, sometimes above what was
    // pushed (a host may derive it from upstream offsets).
    let _ = s.delay();
    if b.u8() % 2 == 0 {
        let _ = s.finish(&mut emit);
    } else {
        let n = u64::from(b.u16()) * [1, 8, 1000, 1 << 40][usize::from(b.u8() % 4)];
        let _ = s.finish_exact(n, &mut emit);
    }
    let _ = s.finish(&mut emit);
    let _ = s.finish_exact(0, &mut emit);
});
