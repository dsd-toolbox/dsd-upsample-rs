// SPDX-License-Identifier: MIT OR Apache-2.0
//! The streaming converter gives the bytes of a whole-file conversion, however the input is
//! split; misuse is an error; progress is reported and can cancel.

use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
use dsd_upsample::dsd2pcm::io::{DsdRead, DsdWrite, PcmRead};
use dsd_upsample::dsd2pcm::wav::{WavFormat, WavReader};
use dsd_upsample::dsd2pcm::Input;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{convert, convert_with, is_cancelled, InputFormat, Options, Output, Stream};
use std::io::Cursor;

const SIZES: [usize; 5] = [1, 777, 5000, 32_768, 100_001];

fn sine(ch: u16, seconds: f64) -> Sine {
    Sine {
        freq: 997,
        level_db: -3.0,
        seconds,
        channels: ch,
    }
}

fn whole(input: Input, ch: u16, mult: u32, o: &Options) -> Vec<u8> {
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), ch, 44_100 * mult, None).unwrap();
    convert(input, &mut w, o).unwrap();
    w.into_inner().into_inner()
}

fn dsf(mult: u32, s: &Sine) -> Vec<u8> {
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), s.channels, 44_100 * mult, None).unwrap();
    testsignal::write_dsd_to(&mut w, mult, s).unwrap();
    w.into_inner().into_inner()
}

/// Streams `push` calls into a DSF and returns its bytes.
fn streamed(
    fmt: InputFormat,
    ch: u16,
    mult: u32,
    o: &Options,
    push: impl Fn(&mut Stream, &mut dyn FnMut(&[Vec<u8>]) -> dsd_upsample::Result<()>),
) -> Vec<u8> {
    let mut s = Stream::new(fmt, ch, o).unwrap();
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), ch, 44_100 * mult, None).unwrap();
    let mut emit = |b: &[Vec<u8>]| w.write_bytes(b);
    push(&mut s, &mut emit);
    let n = s.finish(&mut emit).unwrap();
    w.finish(n).unwrap();
    w.into_inner().into_inner()
}

#[test]
fn stream_matches_whole_file_dsd() {
    let s = sine(2, 0.3);
    let bytes = dsf(64, &s);
    for dither in [false, true] {
        let mut o = Options::new(Output::Dsd { mult: 256 });
        o.dither = dither;
        let want = whole(
            Input::Dsd(Box::new(
                DsfReader::new(Cursor::new(bytes.clone())).unwrap(),
            )),
            2,
            256,
            &o,
        );
        let mut r = DsfReader::new(Cursor::new(bytes.clone())).unwrap();
        let mut chans = vec![Vec::new(); 2];
        while r.read_bytes(1 << 20, &mut chans).unwrap() > 0 {}
        for size in SIZES {
            let got = streamed(
                InputFormat::Dsd { rate: 2_822_400 },
                2,
                256,
                &o,
                |st, emit| {
                    let n = chans[0].len();
                    let mut i = 0;
                    while i < n {
                        let j = (i + size).min(n);
                        let parts: Vec<&[u8]> = chans.iter().map(|c| &c[i..j]).collect();
                        st.push_dsd(&parts, emit).unwrap();
                        i = j;
                    }
                },
            );
            assert!(got == want, "dither {dither}, pushes of {size}");
        }
    }
}

/// Streamed PCM gives the bytes of the whole-file conversion, for 44.1 kHz-family input and
/// 48 kHz-family input (through the resampler), however the input is split.
#[test]
fn stream_matches_whole_file_pcm() {
    for fs in [88_200u32, 48_000, 192_000] {
        let s = sine(3, 0.3);
        let wav = testsignal::write_wav_to(Cursor::new(Vec::new()), fs, WavFormat::F64, &s)
            .unwrap()
            .into_inner();
        let o = Options::new(Output::Dsd { mult: 128 });
        let want = whole(
            Input::Pcm(Box::new(WavReader::new(Cursor::new(wav.clone())).unwrap())),
            3,
            128,
            &o,
        );
        let mut r = WavReader::new(Cursor::new(wav)).unwrap();
        let mut chans = vec![Vec::new(); 3];
        while r.read_frames(1 << 20, &mut chans).unwrap() > 0 {}
        for size in SIZES {
            let got = streamed(InputFormat::Pcm { rate: fs }, 3, 128, &o, |st, emit| {
                for k in (0..chans[0].len()).step_by(size) {
                    let e = (k + size).min(chans[0].len());
                    let parts: Vec<&[f64]> = chans.iter().map(|c| &c[k..e]).collect();
                    st.push_pcm(&parts, emit).unwrap();
                }
            });
            assert!(got == want, "{fs} Hz, pushes of {size}");
        }
    }
}

/// Non-finite samples are limited (to 0) and the modulator keeps running. Each one spreads
/// over the filters' span first, so the limited stretch is longer through the 48 kHz-family
/// resampler (397 taps) than from 44.1 kHz: docs/resampler-design.md quotes these lengths.
#[test]
fn non_finite_pcm_is_limited_not_stuck() {
    let o = Options::new(Output::Dsd { mult: 128 });
    for (fs, max_ms) in [(44_100usize, 6.0), (48_000, 14.0)] {
        let mut st = Stream::new(InputFormat::Pcm { rate: fs as u32 }, 1, &o).unwrap();
        let mut x: Vec<f64> = (0..fs)
            .map(|i| 0.3 * ((i % 100) as f64 / 50.0 - 1.0))
            .collect();
        x[fs / 10] = f64::NAN;
        x[fs / 2] = f64::INFINITY;
        x[9 * fs / 10] = f64::NEG_INFINITY;
        let mut ones = 0u64;
        let mut total = 0u64;
        let mut emit = |b: &[Vec<u8>]| {
            for &v in &b[0] {
                ones += u64::from(v.count_ones());
                total += 8;
            }
            Ok(())
        };
        st.push_pcm(&[&x], &mut emit).unwrap();
        st.finish(&mut emit).unwrap();
        let limited = st.counters()[0].limited;
        let ms = limited as f64 / 3.0 / 5_644.8;
        eprintln!("{fs} Hz: {limited} samples limited, {ms:.2} ms per non-finite sample");
        assert!(limited > 0, "{fs} Hz");
        assert!(ms < max_ms, "{fs} Hz: {ms} ms per non-finite sample");
        // Still modulating: neither stuck at 0 nor at 1.
        assert!(
            ones > total / 4 && ones < total * 3 / 4,
            "{fs} Hz: {ones} of {total}"
        );
    }
}

/// Streamed 48 kHz-family input of an odd length: `finish` returns a sample count that is not
/// a multiple of 8, the last byte is partial (its padding bits are the idle pattern), and
/// the split into pushes changes nothing.
#[test]
fn odd_length_48k_family_ends_in_a_partial_byte() {
    let o = Options::new(Output::Dsd { mult: 128 });
    for (fs, frames) in [(48_000u32, 48_001usize), (96_000, 96_007), (192_000, 4_001)] {
        let x: Vec<f64> = (0..frames)
            .map(|i| 0.25 * ((i % 100) as f64 / 50.0 - 1.0))
            .collect();
        let want = frames as u64 * 5_644_800 / u64::from(fs);
        assert_ne!(want % 8, 0);
        let mut outs = Vec::new();
        for step in [frames, 777] {
            let mut st = Stream::new(InputFormat::Pcm { rate: fs }, 1, &o).unwrap();
            let mut bytes = Vec::new();
            let n = {
                let mut emit = |b: &[Vec<u8>]| {
                    bytes.extend_from_slice(&b[0]);
                    Ok(())
                };
                for c in x.chunks(step) {
                    st.push_pcm(&[c], &mut emit).unwrap();
                }
                st.finish(&mut emit).unwrap()
            };
            assert_eq!(n, want, "{fs} Hz");
            assert_eq!(bytes.len() as u64, want.div_ceil(8), "{fs} Hz");
            outs.push(bytes);
        }
        assert_eq!(outs[0], outs[1], "{fs} Hz");
        let pad = (8 - want % 8) as u32;
        let mask = ((1u16 << pad) - 1) as u8;
        assert_eq!(outs[0].last().unwrap() & mask, 0x69 & mask, "{fs} Hz");
    }
}

#[test]
fn misuse_is_an_error() {
    let o = Options::new(Output::Dsd { mult: 128 });
    let mut st = Stream::new(InputFormat::Dsd { rate: 2_822_400 }, 2, &o).unwrap();
    let mut emit = |_: &[Vec<u8>]| Ok(());
    assert!(st.push_dsd(&[&[0x69; 4]], &mut emit).is_err());
    assert!(st.push_dsd(&[&[0x69; 4], &[0x69; 5]], &mut emit).is_err());
    assert!(st.push_pcm(&[&[0.0; 4], &[0.0; 4]], &mut emit).is_err());
    st.push_dsd(&[&[0x69; 4], &[0x69; 4]], &mut emit).unwrap();
    assert_eq!(st.finish(&mut emit).unwrap(), 32 * 2);
    assert!(st.finish(&mut emit).is_err());
    assert!(st.push_dsd(&[&[0x69; 4], &[0x69; 4]], &mut emit).is_err());
    for (fmt, ch) in [
        (InputFormat::Dsd { rate: 44_100 }, 2),
        (InputFormat::Pcm { rate: 32_000 }, 2),
        (InputFormat::Pcm { rate: 47_999 }, 2),
        (InputFormat::Pcm { rate: 0 }, 2),
        (InputFormat::Dsd { rate: 2_822_400 }, 0),
        (InputFormat::Dsd { rate: 2_822_400 }, 7),
    ] {
        assert!(Stream::new(fmt, ch, &o).is_err(), "{fmt:?} {ch}");
    }
}

#[test]
fn progress_is_reported_and_cancels() {
    let bytes = dsf(64, &sine(2, 0.5));
    for threads in [true, false] {
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.threads = threads;
        let mut seen = Vec::new();
        let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
        let rep = convert_with(
            Input::Dsd(Box::new(
                DsfReader::new(Cursor::new(bytes.clone())).unwrap(),
            )),
            &mut w,
            &o,
            Some(&mut |done, total| {
                seen.push((done, total));
                true
            }),
        )
        .unwrap();
        assert!(seen.len() > 2);
        assert!(seen.windows(2).all(|p| p[0].0 <= p[1].0));
        assert_eq!(*seen.last().unwrap(), (rep.out_samples, rep.out_samples));
        let mut calls = 0;
        let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
        let r = convert_with(
            Input::Dsd(Box::new(
                DsfReader::new(Cursor::new(bytes.clone())).unwrap(),
            )),
            &mut w,
            &o,
            Some(&mut |_, _| {
                calls += 1;
                calls < 2
            }),
        );
        assert!(r.as_ref().is_err_and(is_cancelled), "{r:?}");
    }
}

/// finish_exact: the output length follows the declared input length, not the pushed
/// bytes; more than pushed is an error. delay() is the filters' delay.
#[test]
fn finish_exact_and_delay() {
    let o = Options::new(Output::Dsd { mult: 128 });
    let mut emit = |_: &[Vec<u8>]| Ok(());
    let mut st = Stream::new(InputFormat::Dsd { rate: 2_822_400 }, 1, &o).unwrap();
    assert!(st.delay() > 0);
    st.push_dsd(&[&[0x69; 100]], &mut emit).unwrap();
    assert!(Stream::new(InputFormat::Dsd { rate: 2_822_400 }, 1, &o)
        .unwrap()
        .finish_exact(1, &mut emit)
        .is_err());
    assert_eq!(st.finish_exact(797, &mut emit).unwrap(), 797 * 2);
}

/// finish_exact accepts only a declared length that drops the padding of the last byte
/// (DSD: from pushed - 7 to pushed samples; PCM: exactly the frames pushed). A shorter one
/// is an error and leaves the stream usable, so a later finish gives the right length.
#[test]
fn finish_exact_refuses_a_length_shorter_than_pushed() {
    let o = Options::new(Output::Dsd { mult: 128 });
    let dsd = InputFormat::Dsd { rate: 2_822_400 };
    let bytes = vec![0x69u8; 8192];
    let pushed = 8 * 8192u64;
    // the reviewer's case: 8192 bytes pushed, 8 * 4096 + 5 declared
    for declared in [8 * 4096 + 5, 0, pushed - 8] {
        let mut out = 0u64;
        let mut st = Stream::new(dsd, 1, &o).unwrap();
        st.push_dsd(&[&bytes], &mut |b: &[Vec<u8>]| {
            out += 8 * b[0].len() as u64;
            Ok(())
        })
        .unwrap();
        let mut emit = |b: &[Vec<u8>]| {
            out += 8 * b[0].len() as u64;
            Ok(())
        };
        let e = st.finish_exact(declared, &mut emit).unwrap_err();
        assert!(
            matches!(e, dsd_upsample::Error::InvalidArgument(_)),
            "{declared}: {e}"
        );
        assert!(e.to_string().contains("already pushed"), "{e}");
        // still unfinished: a valid finish completes it with the exact length
        assert_eq!(st.finish(&mut emit).unwrap(), pushed * 2);
        assert_eq!(out, pushed * 2);
    }
    // within the last byte: every length from pushed - 7 to pushed
    for declared in pushed - 7..=pushed {
        let mut out = 0u64;
        let mut emit = |b: &[Vec<u8>]| {
            out += 8 * b[0].len() as u64;
            Ok(())
        };
        let mut st = Stream::new(dsd, 1, &o).unwrap();
        st.push_dsd(&[&bytes], &mut emit).unwrap();
        assert_eq!(st.finish_exact(declared, &mut emit).unwrap(), declared * 2);
        // whole output bytes; the last one carries the remaining bits
        assert_eq!(out, (declared * 2).div_ceil(8) * 8);
    }
    // PCM: frames are whole, so only the pushed count is accepted
    let pcm = InputFormat::Pcm { rate: 44_100 };
    let x = vec![0.1f64; 1000];
    let mut emit = |_: &[Vec<u8>]| Ok(());
    let mut st = Stream::new(pcm, 1, &o).unwrap();
    st.push_pcm(&[&x], &mut emit).unwrap();
    assert!(st.finish_exact(999, &mut emit).is_err());
    assert!(st.finish_exact(1001, &mut emit).is_err());
    assert_eq!(st.finish_exact(1000, &mut emit).unwrap(), 1000 * 128);
}
