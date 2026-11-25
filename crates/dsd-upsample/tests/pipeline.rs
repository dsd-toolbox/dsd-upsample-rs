// SPDX-License-Identifier: MIT OR Apache-2.0
//! End-to-end conversion tests and golden hashes.
//!
//! The golden SHA-256 values hold in debug and release builds and on every platform; a
//! change to them is a change to the output and must be deliberate.

use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
use dsd_upsample::dsd2pcm::io::{DsdRead, PcmRead};
use dsd_upsample::dsd2pcm::wav::{WavFormat, WavReader};
use dsd_upsample::dsd2pcm::Input;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{convert, Options, Output};
use sha2::{Digest, Sha256};
use std::io::Cursor;

fn sine(level_db: f64, seconds: f64) -> Sine {
    Sine {
        freq: 1000,
        level_db,
        seconds,
        channels: 2,
    }
}

fn dsd_input(mult: u32, s: &Sine) -> Vec<u8> {
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), s.channels, 44_100 * mult, None).unwrap();
    testsignal::write_dsd_to(&mut w, mult, s).unwrap();
    w.into_inner().into_inner()
}

fn run(input: Input, mult: u32, opts: &Options) -> (Vec<u8>, dsd_upsample::Report) {
    let ch = match &input {
        Input::Dsd(r) => r.info().channels,
        Input::Pcm(r) => r.info().channels,
    };
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), ch, 44_100 * mult, None).unwrap();
    let rep = convert(input, &mut w, opts).unwrap();
    (w.into_inner().into_inner(), rep)
}

fn hex(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|x| format!("{x:02x}"))
        .collect()
}

fn dsf_in(bytes: Vec<u8>) -> Input {
    Input::Dsd(Box::new(DsfReader::new(Cursor::new(bytes)).unwrap()))
}

struct Case {
    name: &'static str,
    in_mult: u32,
    out_mult: u32,
    order: usize,
    dither: bool,
}

const CASES: &[Case] = &[
    Case {
        name: "dsd64-to-dsd128-o7",
        in_mult: 64,
        out_mult: 128,
        order: 7,
        dither: false,
    },
    Case {
        name: "dsd64-to-dsd256-o7",
        in_mult: 64,
        out_mult: 256,
        order: 7,
        dither: false,
    },
    Case {
        name: "dsd64-to-dsd256-o5-dither",
        in_mult: 64,
        out_mult: 256,
        order: 5,
        dither: true,
    },
    Case {
        name: "dsd256-to-dsd128-o6",
        in_mult: 256,
        out_mult: 128,
        order: 6,
        dither: false,
    },
    Case {
        name: "dsd64-to-dsd128-o6",
        in_mult: 64,
        out_mult: 128,
        order: 6,
        dither: false,
    },
    Case {
        name: "dsd64-to-dsd256-o6",
        in_mult: 64,
        out_mult: 256,
        order: 6,
        dither: false,
    },
    Case {
        name: "dsd128-to-dsd256-o8",
        in_mult: 128,
        out_mult: 256,
        order: 8,
        dither: false,
    },
    Case {
        name: "dsd256-to-dsd128-o7-dither",
        in_mult: 256,
        out_mult: 128,
        order: 7,
        dither: true,
    },
];

const GOLDEN: &[(&str, &str)] = &[
    (
        "dsd64-to-dsd128-o7",
        "d8014df13f37d1d66b9cd6dd1b2067ac14cd2bcfd0fe5643d57c15e89e376858",
    ),
    (
        "dsd64-to-dsd256-o7",
        "b4925914d07540cbb58ca17fca3025682d3f692d5407fbc5056371c9f37971a7",
    ),
    (
        "dsd64-to-dsd256-o5-dither",
        "9891072901af2d14f1cf5d99ee94236416f8503310757292bc2669e1f9248792",
    ),
    (
        "dsd256-to-dsd128-o6",
        "d0e8ca28875635dfacc1ab0b2185f56c377f0a1c754e6a4092b966e3aaf11fda",
    ),
    (
        "dsd64-to-dsd128-o6",
        "877da956287c9604056cdb67b6d6aede4c74d6379f32ca35cf75bec9fcc392bf",
    ),
    (
        "dsd64-to-dsd256-o6",
        "4cfadce3c7585d4f7441a0f532fc1741792d5916fc6d482c28deca8b22e76180",
    ),
    (
        "dsd128-to-dsd256-o8",
        "781703027b71895ae64d3fe30876c82abeda99a546929d3d38f5f77284933ede",
    ),
    (
        "dsd256-to-dsd128-o7-dither",
        "e0df852013546044294efe46acaf8fbb57f6b7f3e0eadd819f33ccad03544837",
    ),
];

fn case_hash(c: &Case) -> (String, dsd_upsample::Report, Vec<u8>) {
    let s = sine(-6.0, 0.05);
    let input = dsd_input(c.in_mult, &s);
    let mut o = Options::new(Output::Dsd { mult: c.out_mult });
    o.order = c.order;
    o.dither = c.dither;
    let (out, rep) = run(dsf_in(input), c.out_mult, &o);
    (hex(&out), rep, out)
}

#[test]
fn golden_hashes() {
    let mut fails = Vec::new();
    for c in CASES {
        let (h, rep, out) = case_hash(c);
        // structure: exact output length and a quiet run
        let r = DsfReader::new(Cursor::new(out)).unwrap();
        let expect =
            (0.05f64 * f64::from(44_100 * c.in_mult)) as u64 / 8 * 8 * u64::from(c.out_mult)
                / u64::from(c.in_mult);
        assert_eq!(r.info().samples, expect, "{}", c.name);
        assert!(
            rep.counters.iter().all(|k| k.limited == 0 && k.resets == 0),
            "{} {:?}",
            c.name,
            rep.counters
        );
        match GOLDEN.iter().find(|(n, _)| *n == c.name) {
            Some((_, g)) if *g == h => {}
            Some((_, g)) => fails.push(format!("{}: got {h}, golden {g}", c.name)),
            None => fails.push(format!("{}: no golden, got {h}", c.name)),
        }
    }
    assert!(fails.is_empty(), "{}", fails.join("\n"));
}

/// DSD64 output: from PCM only, golden hash; DSD input is refused.
#[test]
fn dsd64_output_from_pcm() {
    let w = testsignal::write_wav_to(
        Cursor::new(Vec::new()),
        88_200,
        WavFormat::I24,
        &sine(-6.0, 0.05),
    )
    .unwrap()
    .into_inner();
    let frames = WavReader::new(Cursor::new(w.clone()))
        .unwrap()
        .info()
        .frames;
    let o = Options::new(Output::Dsd { mult: 64 });
    let (out, rep) = run(
        Input::Pcm(Box::new(WavReader::new(Cursor::new(w)).unwrap())),
        64,
        &o,
    );
    assert_eq!(rep.out_samples, frames * 32);
    assert!(rep.counters.iter().all(|k| k.limited == 0 && k.resets == 0));
    assert_eq!(hex(&out), GOLDEN_DSD64);
    let mut sink = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 64, None).unwrap();
    let dsd = dsd_input(128, &sine(-6.0, 0.01));
    assert!(convert(dsf_in(dsd), &mut sink, &o).is_err());
}

/// 48 kHz-family input (resampled by 147/160 first): golden hashes at DSD128, exact
/// length (`frames x output rate / input rate`, rounded down), a quiet run.
#[test]
fn golden_48k_family() {
    let mut fails = Vec::new();
    for (fs, golden) in [(48_000u32, GOLDEN_48K_DSD128), (96_000, GOLDEN_96K_DSD128)] {
        let w = testsignal::write_wav_to(
            Cursor::new(Vec::new()),
            fs,
            WavFormat::I24,
            &sine(-6.0, 0.05),
        )
        .unwrap()
        .into_inner();
        let r = WavReader::new(Cursor::new(w.clone())).unwrap();
        let frames = r.info().frames;
        let (out, rep) = run(
            Input::Pcm(Box::new(r)),
            128,
            &Options::new(Output::Dsd { mult: 128 }),
        );
        assert_eq!(rep.out_samples, frames * 5_644_800 / u64::from(fs));
        // the single-threaded pipeline gives the same bytes
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.threads = false;
        let r = WavReader::new(Cursor::new(w)).unwrap();
        assert_eq!(
            run(Input::Pcm(Box::new(r)), 128, &o).0,
            out,
            "{fs} Hz single thread"
        );
        assert!(rep.counters.iter().all(|k| k.limited == 0 && k.resets == 0));
        let h = hex(&out);
        if h != golden {
            fails.push(format!("{fs} Hz: got {h}, golden {golden}"));
        }
    }
    assert!(fails.is_empty(), "{}", fails.join("\n"));
}

/// A 48 kHz-family input whose length gives a whole number of output samples that is not a
/// multiple of 8: the output keeps exactly `frames x output rate / input rate` samples
/// (rounded down) and ends in a partial byte. (44.1 kHz-family PCM always gives whole bytes.)
#[test]
fn odd_length_48k_family_input() {
    use dsd_upsample::dsd2pcm::wav::WavWriter;
    for (fs, frames) in [(48_000u32, 48_001u64), (96_000, 96_007), (192_000, 4_001)] {
        let mut w = WavWriter::new(Cursor::new(Vec::new()), WavFormat::F64, 2, fs).unwrap();
        let mut raw = Vec::new();
        for i in 0..frames {
            let v = 0.25 * ((i % 100) as f64 / 50.0 - 1.0);
            raw.extend_from_slice(&v.to_le_bytes());
            raw.extend_from_slice(&(-v).to_le_bytes());
        }
        w.write_raw(&raw).unwrap();
        w.finish().unwrap();
        let wav = w.into_inner().into_inner();
        let want = frames * 5_644_800 / u64::from(fs);
        assert_ne!(want % 8, 0, "{fs} Hz: the case must end in a partial byte");
        for threads in [true, false] {
            let mut o = Options::new(Output::Dsd { mult: 128 });
            o.threads = threads;
            let r = WavReader::new(Cursor::new(wav.clone())).unwrap();
            assert_eq!(r.info().frames, frames);
            let (out, rep) = run(Input::Pcm(Box::new(r)), 128, &o);
            assert_eq!(rep.out_samples, want, "{fs} Hz");
            let d = DsfReader::new(Cursor::new(out)).unwrap();
            assert_eq!(d.info().samples, want, "{fs} Hz, threads {threads}");
        }
    }
}

const GOLDEN_48K_DSD128: &str = "191a08647386714d1d7885fca14bcb42dff5fdfa25004dc718fc08fca3dd10e9";
const GOLDEN_96K_DSD128: &str = "09540d32f97873002a369877c2bccdcaa95958d0cec40c8ec61d851bd1ca8736";

const GOLDEN_DSD64: &str = "b3732c8225081399059d50c884bc6adbe3da0de1c0871cfb7d7b397ac866db28";

#[test]
fn wav_inputs_convert() {
    for (fs, fmt) in [
        (44_100u32, WavFormat::I16),
        (88_200, WavFormat::I24),
        (176_400, WavFormat::F32),
        (352_800, WavFormat::F64),
        (48_000, WavFormat::I16),
        (96_000, WavFormat::I24),
        (192_000, WavFormat::F32),
        (384_000, WavFormat::F64),
    ] {
        let w =
            testsignal::write_wav_to(Cursor::new(Vec::new()), fs, fmt, &sine(-6.0, 0.02)).unwrap();
        let r = WavReader::new(Cursor::new(w.into_inner())).unwrap();
        let frames = r.info().frames;
        let (out, rep) = run(
            Input::Pcm(Box::new(r)),
            128,
            &Options::new(Output::Dsd { mult: 128 }),
        );
        let r = DsfReader::new(Cursor::new(out)).unwrap();
        assert_eq!(r.info().samples, frames * 5_644_800 / u64::from(fs), "{fs}");
        assert!(
            rep.counters.iter().all(|k| k.limited == 0 && k.resets == 0),
            "{fs}"
        );
    }
}

/// The threaded pipeline gives the bytes of the single-threaded run, over many input
/// chunks, for DSD and WAV input, six channels and dither.
#[test]
fn same_output_single_and_multi_threaded() {
    let six = Sine {
        channels: 6,
        ..sine(-3.0, 0.4)
    };
    let wav = testsignal::write_wav_to(Cursor::new(Vec::new()), 44_100, WavFormat::I24, &six)
        .unwrap()
        .into_inner();
    let dsd = dsd_input(64, &six);
    let inputs = || -> [Input; 2] {
        [
            dsf_in(dsd.clone()),
            Input::Pcm(Box::new(WavReader::new(Cursor::new(wav.clone())).unwrap())),
        ]
    };
    for dither in [false, true] {
        let mut o = Options::new(Output::Dsd { mult: 256 });
        o.dither = dither;
        for (a, b) in inputs().into_iter().zip(inputs()) {
            o.threads = true;
            let (x, rx) = run(a, 256, &o);
            o.threads = false;
            let (y, ry) = run(b, 256, &o);
            assert!(x == y, "dither {dither}");
            assert_eq!(rx.counters, ry.counters);
        }
    }
}

#[test]
fn hot_input_is_limited_not_unstable() {
    let input = dsd_input(64, &sine(2.5, 0.05));
    let mut o = Options::new(Output::Dsd { mult: 256 });
    o.gain_db = 6.0;
    let (_, rep) = run(dsf_in(input), 256, &o);
    assert!(
        rep.counters.iter().all(|k| k.limited > 0),
        "{:?}",
        rep.counters
    );
}

#[test]
fn bad_options_are_errors() {
    let input = dsd_input(64, &sine(-6.0, 0.01));
    for o in [
        Options {
            order: 4,
            ..Options::new(Output::Dsd { mult: 256 })
        },
        Options {
            gain_db: 30.0,
            ..Options::new(Output::Dsd { mult: 256 })
        },
        Options {
            input_limit: Some(0.0),
            ..Options::new(Output::Dsd { mult: 128 })
        },
        Options::new(Output::Dsd { mult: 512 }),
    ] {
        let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
        assert!(convert(dsf_in(input.clone()), &mut w, &o).is_err());
    }
}

/// Converting a file onto itself (same path, or a hard link) is refused and leaves it intact.
#[test]
fn output_onto_input_is_refused() {
    let dir = std::env::temp_dir().join(format!("dsdup-same-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let p = dir.join("in.dsf");
    let bytes = dsd_input(64, &sine(-6.0, 0.01));
    std::fs::write(&p, &bytes).unwrap();
    let o = Options::new(Output::Dsd { mult: 128 });
    assert!(dsd_upsample::convert_file(&p, &p, &o).is_err());
    #[cfg(unix)]
    {
        let link = dir.join("link.dsf");
        std::fs::hard_link(&p, &link).unwrap();
        assert!(dsd_upsample::convert_file(&p, &link, &o).is_err());
        std::fs::remove_file(&link).unwrap();
    }
    assert_eq!(std::fs::read(&p).unwrap(), bytes);
    std::fs::remove_file(&p).unwrap();
    std::fs::remove_dir(&dir).unwrap();
}

/// Hostile options are errors, never panics: non-finite gains and limits, every invalid
/// order and rate.
#[test]
fn hostile_options_are_errors() {
    let input = dsd_input(64, &sine(-6.0, 0.01));
    let base = Options::new(Output::Dsd { mult: 256 });
    let mut bad = Vec::new();
    for g in [
        f64::NAN,
        f64::INFINITY,
        f64::NEG_INFINITY,
        24.000_001,
        -120.5,
        1e308,
    ] {
        bad.push(Options { gain_db: g, ..base });
    }
    for l in [f64::NAN, 0.0, -0.5, 1.000_001, f64::INFINITY] {
        bad.push(Options {
            input_limit: Some(l),
            ..base
        });
    }
    for order in [0, 1, 4, 9, usize::MAX] {
        bad.push(Options { order, ..base });
    }
    for mult in [0, 1, 32, 127, 512, 1024, u32::MAX] {
        bad.push(Options::new(Output::Dsd { mult }));
    }
    for o in bad {
        let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
        assert!(
            convert(dsf_in(input.clone()), &mut w, &o).is_err(),
            "{o:?} accepted"
        );
    }
}

/// Odd channel counts and empty inputs convert to the expected lengths.
#[test]
fn odd_channel_counts_and_empty_inputs() {
    for ch in [1u16, 3, 5] {
        let s = Sine {
            channels: ch,
            ..sine(-6.0, 0.02)
        };
        for input in [
            dsf_in(dsd_input(64, &s)),
            Input::Pcm(Box::new(
                WavReader::new(Cursor::new(
                    testsignal::write_wav_to(Cursor::new(Vec::new()), 88_200, WavFormat::I16, &s)
                        .unwrap()
                        .into_inner(),
                ))
                .unwrap(),
            )),
        ] {
            let (out, rep) = run(input, 128, &Options::new(Output::Dsd { mult: 128 }));
            let r = DsfReader::new(Cursor::new(out)).unwrap();
            assert_eq!(r.info().channels, ch);
            assert_eq!(rep.counters.len(), usize::from(ch));
        }
    }
    for threads in [true, false] {
        let mut o = Options::new(Output::Dsd { mult: 256 });
        o.threads = threads;
        let empty = dsd_input(64, &sine(-6.0, 0.0));
        let (out, rep) = run(dsf_in(empty), 256, &o);
        assert_eq!(rep.out_samples, 0);
        assert_eq!(DsfReader::new(Cursor::new(out)).unwrap().info().samples, 0);
    }
}

/// A source that delivers less than it declares ends with an error after a bounded
/// amount of output, rather than padding the output with silence to the declared length.
#[test]
fn short_input_is_an_error_not_endless_silence() {
    struct Short(u16);
    impl DsdRead for Short {
        fn info(&self) -> dsd_upsample::dsd2pcm::io::DsdInfo {
            dsd_upsample::dsd2pcm::io::DsdInfo {
                channels: self.0,
                sample_rate: 2_822_400,
                samples: 1 << 40,
            }
        }
        fn read_bytes(&mut self, _: usize, _: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
            Ok(0)
        }
    }
    for threads in [true, false] {
        let mut o = Options::new(Output::Dsd { mult: 256 });
        o.threads = threads;
        let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 256, None).unwrap();
        let r = convert(Input::Dsd(Box::new(Short(2))), &mut w, &o);
        assert!(r.is_err());
        let written = w.into_inner().into_inner().len();
        assert!(written < 64 << 20, "{written} bytes of silence");
        // Channel counts outside 1..=6 from a custom source are errors too.
        for ch in [0u16, 7, u16::MAX] {
            let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 256, None).unwrap();
            assert!(convert(Input::Dsd(Box::new(Short(ch))), &mut w, &o).is_err());
        }
    }
}

/// Work and output are bounded by the samples a source delivers, never by the length it
/// declares: a source that ends early is refused at its end, before any silence is made up
/// for the missing part (fuzzing found a source of no bytes that declared hours, or even
/// one second, of audio and was converted as idle until the declared length or the flush
/// limit).
#[test]
fn short_source_is_refused_before_any_made_up_output() {
    use dsd_upsample::dsd2pcm::io::{DsdInfo, DsdWrite, PcmInfo};
    /// Declares `declared` samples per channel, delivers `given` (DSD: bits; PCM: frames);
    /// PCM at `rate`.
    struct Src {
        declared: u64,
        given: u64,
        rate: u32,
    }
    impl DsdRead for Src {
        fn info(&self) -> DsdInfo {
            DsdInfo {
                channels: 2,
                sample_rate: 2_822_400,
                samples: self.declared,
            }
        }
        fn read_bytes(&mut self, max: usize, out: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
            let n = (self.given / 8).min(max as u64) as usize;
            self.given -= 8 * n as u64;
            for o in out.iter_mut() {
                o.extend(std::iter::repeat_n(0x69, n));
            }
            Ok(n)
        }
    }
    impl PcmRead for Src {
        fn info(&self) -> PcmInfo {
            PcmInfo {
                channels: 2,
                sample_rate: self.rate,
                frames: self.declared,
            }
        }
        fn read_frames(&mut self, max: usize, out: &mut [Vec<f64>]) -> dsd_upsample::Result<usize> {
            let n = self.given.min(max as u64) as usize;
            self.given -= n as u64;
            for o in out.iter_mut() {
                o.extend(std::iter::repeat_n(0.25, n));
            }
            Ok(n)
        }
    }
    /// Counts the bytes per channel it is given.
    struct Count(u64);
    impl DsdWrite for Count {
        fn write_bytes(&mut self, data: &[Vec<u8>]) -> dsd_upsample::Result<()> {
            self.0 += data[0].len() as u64;
            Ok(())
        }
        fn finish(&mut self, _: u64) -> dsd_upsample::Result<()> {
            Ok(())
        }
    }
    for threads in [false, true] {
        let mut o = Options::new(Output::Dsd { mult: 256 });
        o.threads = threads;
        // the 48 kHz rows go through the resampler: the declared length is checked in input
        // samples, before the rate change
        for (dsd, rate, declared) in [
            (true, 0, 2_822_400u64),
            (true, 0, 1 << 40),
            (false, 44_100, 44_100),
            (false, 44_100, 1 << 40),
            (false, 48_000, 48_000),
            (false, 48_000, 1 << 40),
        ] {
            // Output samples per input sample at DSD256: 4 from DSD64, 256 from 44.1 kHz,
            // 235.2 (rounded up) from 48 kHz.
            let per_in = match (dsd, rate) {
                (true, _) => 4,
                (false, 44_100) => 256,
                _ => 236,
            };
            for given in [0, if dsd { 8 * 65_536 } else { 8_192 }] {
                let src = Src {
                    declared,
                    given,
                    rate,
                };
                let input = if dsd {
                    Input::Dsd(Box::new(src))
                } else {
                    Input::Pcm(Box::new(src))
                };
                let mut sink = Count(0);
                let r = convert(input, &mut sink, &o);
                let case = format!(
                    "dsd={dsd} rate={rate} declared={declared} given={given} threads={threads}"
                );
                let e = r.expect_err(&case).to_string();
                assert!(e.contains("input ended after"), "{case}: {e}");
                // Never more output than the delivered input backs.
                assert!(
                    sink.0 * 8 <= given * per_in,
                    "{case}: {} bytes per channel",
                    sink.0
                );
            }
        }
    }
}

/// A source whose channels get different lengths from one read is refused, not a panic
/// (fuzzing: the input mean indexed every channel up to the count the source returned).
#[test]
fn unequal_channel_lengths_are_an_error() {
    use dsd_upsample::dsd2pcm::io::{DsdInfo, PcmInfo};
    /// Gives channel `c` `n - c` samples (or `n + c` when `longer`) and returns `n`.
    struct Skew {
        longer: bool,
    }
    impl Skew {
        fn len(&self, c: usize, n: usize) -> usize {
            if self.longer {
                n + c
            } else {
                n - c
            }
        }
    }
    impl DsdRead for Skew {
        fn info(&self) -> DsdInfo {
            DsdInfo {
                channels: 2,
                sample_rate: 2_822_400,
                samples: 8 * 4096,
            }
        }
        fn read_bytes(&mut self, _: usize, out: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
            for (c, o) in out.iter_mut().enumerate() {
                o.extend(std::iter::repeat_n(0x69, self.len(c, 4096)));
            }
            Ok(4096)
        }
    }
    impl PcmRead for Skew {
        fn info(&self) -> PcmInfo {
            PcmInfo {
                channels: 2,
                sample_rate: 44_100,
                frames: 1024,
            }
        }
        fn read_frames(&mut self, _: usize, out: &mut [Vec<f64>]) -> dsd_upsample::Result<usize> {
            for (c, o) in out.iter_mut().enumerate() {
                o.extend(std::iter::repeat_n(0.25, self.len(c, 1024)));
            }
            Ok(1024)
        }
    }
    for threads in [false, true] {
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.threads = threads;
        for dsd in [true, false] {
            for longer in [false, true] {
                let input = if dsd {
                    Input::Dsd(Box::new(Skew { longer }))
                } else {
                    Input::Pcm(Box::new(Skew { longer }))
                };
                let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
                let e = convert(input, &mut w, &o).unwrap_err().to_string();
                assert!(
                    e.contains("gave channel 1"),
                    "dsd={dsd} longer={longer}: {e}"
                );
            }
        }
    }
}

/// An explicit container overrides the extension, and tags land in the DSF as ID3v2.
#[test]
fn file_output_container_and_tags() {
    use dsd_upsample::{convert_file_to, Container, FileOutput};
    let dir = std::env::temp_dir().join(format!("dsdup-tags-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let inp = dir.join("in.dsf");
    std::fs::write(&inp, dsd_input(64, &sine(-6.0, 0.01))).unwrap();
    let out = dir.join("out.tmp");
    let tags = vec![
        ("title".to_string(), "T".to_string()),
        ("SOURCE".to_string(), "x".to_string()),
    ];
    let file = FileOutput {
        container: Some(Container::Dsf),
        tags: tags.clone(),
        no_overwrite: false,
    };
    let o = Options::new(Output::Dsd { mult: 128 });
    convert_file_to(&inp, &out, &o, &file, None).unwrap();
    let r = DsfReader::new(std::io::BufReader::new(std::fs::File::open(&out).unwrap())).unwrap();
    assert_eq!(
        r.metadata(),
        Some(&dsd_upsample::id3::tag(&tags).unwrap()[..])
    );
    // DFF and WAV output take no tags
    for c in [Container::Dff, Container::Wav] {
        let f = FileOutput {
            container: Some(c),
            tags: tags.clone(),
            no_overwrite: false,
        };
        assert!(convert_file_to(&inp, &out, &o, &f, None).is_err());
    }
    // no_overwrite: the existing output is refused and left as it was
    let before = std::fs::read(&out).unwrap();
    let f = FileOutput {
        no_overwrite: true,
        ..FileOutput::default()
    };
    let dsf_out = dir.join("out.dsf");
    std::fs::write(&dsf_out, &before).unwrap();
    assert!(convert_file_to(&inp, &dsf_out, &o, &f, None).is_err());
    assert_eq!(std::fs::read(&dsf_out).unwrap(), before);
    std::fs::remove_dir_all(&dir).unwrap();
}

/// PCM output reports progress during the conversion and can be cancelled part-way.
#[test]
fn pcm_output_progress_and_cancel() {
    use dsd_upsample::dsd2pcm::PcmRate;
    let dir = std::env::temp_dir().join(format!("dsdup-pcmcancel-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let inp = dir.join("in.dsf");
    std::fs::write(&inp, dsd_input(64, &sine(-6.0, 1.0))).unwrap();
    let out = dir.join("out.wav");
    let o = Options::new(Output::Pcm(PcmRate::Hz176400));
    let mut calls = 0;
    let rep = dsd_upsample::convert_file_with(
        &inp,
        &out,
        &o,
        Some(&mut |done, total| {
            assert!(done <= total);
            calls += 1;
            true
        }),
    )
    .unwrap();
    assert!(calls > 2, "{calls} progress calls");
    assert_eq!(rep.out_rate, 176_400);
    let mut calls = 0;
    let r = dsd_upsample::convert_file_with(
        &inp,
        &out,
        &o,
        Some(&mut |_, _| {
            calls += 1;
            calls < 2
        }),
    );
    assert!(r.as_ref().is_err_and(dsd_upsample::is_cancelled), "{r:?}");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// DSD bytes (MSB first) of a first-order sigma-delta modulation of `x(n)`.
fn sdm_bytes(n_bits: usize, x: impl Fn(usize) -> f64) -> Vec<u8> {
    let (mut acc, mut y) = (0.0f64, 1.0f64);
    let mut out = vec![0u8; n_bits / 8];
    for i in 0..n_bits {
        acc += x(i) - y;
        y = if acc >= 0.0 { 1.0 } else { -1.0 };
        if y > 0.0 {
            out[i / 8] |= 0x80 >> (i % 8);
        }
    }
    out
}

/// A stereo DSD64 DSF in memory: channel 0 carries a DC offset of -0.71 of full modulation
/// under a 1 kHz tone (as one real release does), channel 1 the tone alone.
fn dc_offset_dsf(seconds: f64) -> Vec<u8> {
    let n = (2_822_400.0 * seconds) as usize / 8 * 8;
    let tone =
        |i: usize| 0.2 * (2.0 * std::f64::consts::PI * 1000.0 * i as f64 / 2_822_400.0).sin();
    let ch = [sdm_bytes(n, |i| -0.71 + tone(i)), sdm_bytes(n, tone)];
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 2_822_400, None).unwrap();
    use dsd_upsample::dsd2pcm::io::DsdWrite;
    w.write_bytes(&ch).unwrap();
    w.finish(n as u64).unwrap();
    w.into_inner().into_inner()
}

/// The report's input mean is the input's DC, per channel, for DSD and PCM input, in both
/// threading modes; it does not change the output.
#[test]
fn input_mean_measures_the_dc_offset() {
    let dsf = dc_offset_dsf(0.2);
    let mut outs = Vec::new();
    for threads in [true, false] {
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.threads = threads;
        // the louder setting: at the default gain this offset is not limited (below)
        o.gain_db = -3.0;
        let (out, rep) = run(dsf_in(dsf.clone()), 128, &o);
        assert_eq!(rep.input_mean.len(), 2);
        assert!(
            (rep.input_mean[0] + 0.71).abs() < 0.005,
            "{:?}",
            rep.input_mean
        );
        assert!(rep.input_mean[1].abs() < 0.005, "{:?}", rep.input_mean);
        // -0.71 at -3 dB is the 0.5 limit: the tone's negative half is limited.
        assert!(
            rep.counters[0].limited > rep.out_samples / 10,
            "{:?}",
            rep.counters
        );
        assert_eq!(rep.counters[1].limited, 0);
        outs.push(out);
    }
    assert_eq!(outs[0], outs[1]);
    // At the default gain (-6 dB) the offset and the tone, 0.91 of full modulation at the
    // peaks, stay below the limit: nothing is limited.
    let o = Options::new(Output::Dsd { mult: 128 });
    let (_, rep) = run(dsf_in(dsf.clone()), 128, &o);
    assert_eq!(rep.counters[0].limited, 0, "{:?}", rep.counters);
    assert_eq!(rep.counters[1].limited, 0, "{:?}", rep.counters);
    // PCM: the mean of the samples (a -6 dBFS sine: about 0).
    let s = sine(-6.0, 0.1);
    let wav = testsignal::write_wav_to(Cursor::new(Vec::new()), 44_100, WavFormat::F64, &s)
        .unwrap()
        .into_inner();
    let (_, rep) = run(
        Input::Pcm(Box::new(WavReader::new(Cursor::new(wav)).unwrap())),
        128,
        &Options::new(Output::Dsd { mult: 128 }),
    );
    assert!(
        rep.input_mean.iter().all(|m| m.abs() < 1e-3),
        "{:?}",
        rep.input_mean
    );
}

/// A DSF file whose header declares 0 samples but whose data chunk holds audio is refused,
/// with the header's count and the data size; an empty DSF still converts (to an empty
/// output).
#[test]
fn zero_sample_header_with_data_is_refused() {
    let d = std::env::temp_dir().join(format!("dsdup-zero-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    let mut bad = dsd_input(64, &sine(-6.0, 0.1));
    bad[64..72].copy_from_slice(&0u64.to_le_bytes());
    let data = u64::from_le_bytes(bad[84..92].try_into().unwrap()) - 12;
    let (inp, out) = (d.join("bad.dsf"), d.join("out.dsf"));
    std::fs::write(&inp, &bad).unwrap();
    let opts = Options::new(Output::Dsd { mult: 128 });
    let e = dsd_upsample::convert_file(&inp, &out, &opts).unwrap_err();
    let msg = e.to_string();
    assert!(
        msg.contains("declares 0 samples") && msg.contains(&format!("holds {data} bytes")),
        "{msg}"
    );
    assert!(!out.exists());
    let empty = d.join("empty.dsf");
    std::fs::write(&empty, dsd_input(64, &sine(-6.0, 0.0))).unwrap();
    let rep = dsd_upsample::convert_file(&empty, &out, &opts).unwrap();
    assert_eq!(rep.out_samples, 0);
    std::fs::remove_dir_all(&d).unwrap();
}
