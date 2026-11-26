// SPDX-License-Identifier: MIT OR Apache-2.0
//! H1, channel independence: a 1-channel [`Stream`] fed one channel gives the bytes (and
//! counters) of that channel in a multichannel [`Stream`], for DSD and PCM input. A host that
//! converts channels separately (or a cache keyed per channel) relies on it.
//!
//! Without dither it holds for every channel. With dither it holds for channel 0 only: the
//! dither generator of channel `c` is seeded with `c` (`convert.rs`, `build`), so channel
//! `c > 0` of a multichannel stream gets other dither than a 1-channel stream of the same
//! samples. `dither_is_seeded_by_channel_index` pins that behaviour.

use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
use dsd_upsample::dsd2pcm::io::DsdRead;
use dsd_upsample::modulator::Counters;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{InputFormat, Options, Output, Stream};
use std::io::Cursor;

const CHANNELS: usize = 6;
/// Push size in input bytes (DSD) or frames (PCM): not a divisor of the internal chunk.
const PUSH: usize = 3001;

/// One channel of DSD64 per entry: a different frequency and level each, from the crate's
/// test-tone generator.
fn dsd_channels(seconds: f64) -> Vec<Vec<u8>> {
    (0..CHANNELS)
        .map(|c| {
            let s = Sine {
                freq: 440 + 997 * c as u32,
                level_db: -3.0 - 2.0 * c as f64,
                seconds,
                channels: 1,
            };
            let mut w = DsfWriter::new(Cursor::new(Vec::new()), 1, 2_822_400, None).unwrap();
            testsignal::write_dsd_to(&mut w, 64, &s).unwrap();
            let mut r = DsfReader::new(Cursor::new(w.into_inner().into_inner())).unwrap();
            let mut ch = vec![Vec::new()];
            while r.read_bytes(1 << 20, &mut ch).unwrap() > 0 {}
            ch.pop().unwrap()
        })
        .collect()
}

/// One channel of PCM per entry: a different frequency and level each.
fn pcm_channels(fs: u32, seconds: f64) -> Vec<Vec<f64>> {
    let n = (f64::from(fs) * seconds) as usize;
    (0..CHANNELS)
        .map(|c| {
            let f = 300.0 + 1234.5 * c as f64;
            let a = 0.4 / (1.0 + c as f64);
            (0..n)
                .map(|i| a * (2.0 * std::f64::consts::PI * f * i as f64 / f64::from(fs)).sin())
                .collect()
        })
        .collect()
}

#[derive(Clone, Copy)]
enum Data<'a> {
    Dsd(&'a [Vec<u8>]),
    Pcm(&'a [Vec<f64>]),
}

/// Streams the channels `which` of `data` through one Stream; returns each channel's
/// output bytes and counters.
fn stream(
    fmt: InputFormat,
    data: Data<'_>,
    which: &[usize],
    o: &Options,
) -> (Vec<Vec<u8>>, Vec<Counters>) {
    let mut st = Stream::new(fmt, which.len() as u16, o).unwrap();
    let mut out = vec![Vec::new(); which.len()];
    let mut emit = |b: &[Vec<u8>]| -> dsd_upsample::Result<()> {
        for (o, x) in out.iter_mut().zip(b) {
            o.extend_from_slice(x);
        }
        Ok(())
    };
    match data {
        Data::Dsd(d) => {
            let n = d[0].len();
            for i in (0..n).step_by(PUSH) {
                let e = (i + PUSH).min(n);
                let parts: Vec<&[u8]> = which.iter().map(|&c| &d[c][i..e]).collect();
                st.push_dsd(&parts, &mut emit).unwrap();
            }
        }
        Data::Pcm(d) => {
            let n = d[0].len();
            for i in (0..n).step_by(PUSH) {
                let e = (i + PUSH).min(n);
                let parts: Vec<&[f64]> = which.iter().map(|&c| &d[c][i..e]).collect();
                st.push_pcm(&parts, &mut emit).unwrap();
            }
        }
    }
    st.finish(&mut emit).unwrap();
    let counters = st.counters();
    (out, counters)
}

fn same_counters(a: &Counters, b: &Counters) -> bool {
    a.limited == b.limited && a.clipped == b.clipped && a.resets == b.resets
}

/// For every channel count in `counts`, which channels of the multichannel stream differ
/// from a 1-channel stream of the same samples (bytes or counters).
fn mismatches(fmt: InputFormat, data: Data<'_>, o: &Options, counts: &[usize]) -> Vec<String> {
    let mut bad = Vec::new();
    let singles: Vec<(Vec<u8>, Counters)> = (0..CHANNELS)
        .map(|c| {
            let (mut b, k) = stream(fmt, data, &[c], o);
            (b.pop().unwrap(), k.into_iter().next().unwrap())
        })
        .collect();
    for (c, (b, _)) in singles.iter().enumerate() {
        assert!(!b.is_empty(), "channel {c}: no output");
    }
    for &n in counts {
        let which: Vec<usize> = (0..n).collect();
        let (multi, counters) = stream(fmt, data, &which, o);
        for c in 0..n {
            if multi[c] != singles[c].0 || !same_counters(&counters[c], &singles[c].1) {
                bad.push(format!("{n}-channel stream, channel {c}"));
            }
        }
    }
    bad
}

fn opts(mult: u32, dither: bool) -> Options {
    let mut o = Options::new(Output::Dsd { mult });
    o.dither = dither;
    o
}

const DSD64: InputFormat = InputFormat::Dsd { rate: 2_822_400 };

#[test]
fn one_channel_stream_equals_that_channel_dsd() {
    let d = dsd_channels(0.1);
    for mult in [128, 256] {
        let bad = mismatches(DSD64, Data::Dsd(&d), &opts(mult, false), &[2, CHANNELS]);
        assert!(bad.is_empty(), "DSD64 to DSD{mult}: {bad:?}");
    }
}

#[test]
fn one_channel_stream_equals_that_channel_pcm() {
    // 88.2 kHz (44.1 kHz family) and 48 kHz (through the resampler); DSD64 output from PCM.
    for (fs, mult) in [(88_200u32, 128u32), (48_000, 256), (44_100, 64)] {
        let d = pcm_channels(fs, 0.1);
        let fmt = InputFormat::Pcm { rate: fs };
        let bad = mismatches(fmt, Data::Pcm(&d), &opts(mult, false), &[2, CHANNELS]);
        assert!(bad.is_empty(), "{fs} Hz to DSD{mult}: {bad:?}");
    }
}

/// With dither, channel 0 matches and every other channel differs: the dither seed is the
/// channel index. (Finding H1 for consumers: convert channels separately only without
/// dither, the default.)
#[test]
fn dither_is_seeded_by_channel_index() {
    let want: Vec<String> = (1..CHANNELS)
        .map(|c| format!("{CHANNELS}-channel stream, channel {c}"))
        .collect();
    let d = dsd_channels(0.1);
    let bad = mismatches(DSD64, Data::Dsd(&d), &opts(128, true), &[CHANNELS]);
    assert_eq!(bad, want, "DSD64 to DSD128 with dither");
    let p = pcm_channels(88_200, 0.1);
    let fmt = InputFormat::Pcm { rate: 88_200 };
    let bad = mismatches(fmt, Data::Pcm(&p), &opts(128, true), &[CHANNELS]);
    assert_eq!(bad, want, "88.2 kHz to DSD128 with dither");
}
