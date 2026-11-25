// SPDX-License-Identifier: MIT OR Apache-2.0
//! Headroom and modulator stability, for every combination of noise-shaping band, modulator
//! order and DSD output rate the library accepts, at the default input limit.
//!
//! The signals are adversarial PCM: clipped sines, DC, white and pink noise, random
//! full-scale samples, squares up to the Nyquist frequency, a full-scale 20 kHz sine at
//! 352.8 kHz, full-scale steps and impulses; from 88.2 and 352.8 kHz, and through the
//! 48 kHz-family resampler from 48, 96 and 384 kHz (the full set at 48 kHz); sines at 0 dB
//! SACD (full scale with `gain_db = 0`, 6 dB above the default: no clipped state and no
//! reset); and DSD tones held at the Super Audio CD peak level from DSD64, DSD128 and
//! DSD256.
//!
//! Three rules:
//! - At the defaults, legal input is not limited, and it never clips a modulator state or
//!   resets the modulator. Legal: PCM within full scale whose true peak is at most +6 dBTP,
//!   and DSD whose waveform after the input filter stays within 100 % modulation. Random
//!   full-scale samples and white noise peaking at full scale have true peaks above
//!   +6 dBTP (up to +8.0 dBTP in the 60 s study): they may be limited, and still must not
//!   overload the modulator.
//! - At the louder setting `gain_db = -3` (the default of earlier builds) every accepted
//!   combination limits what exceeds the limit and never clips a state or resets. A
//!   combination that cannot meet this is not accepted (`accepted_orders`).
//! - At the default order the same holds 6 dB louder still (`gain_db = +3`).
//!
//! See docs/modulator-design.md for the 60 s study and the error each signal leaves in the
//! audio band.

use dsd_upsample::dsd2pcm::io::DsdWrite;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{accepted_orders, Band, InputFormat, Options, Output, Stream};

/// Seconds per signal: long enough for many periods of every signal and several steps.
const SECONDS: f64 = if cfg!(debug_assertions) { 0.2 } else { 1.5 };

struct Rng(u64);

impl Rng {
    /// Uniform in [-1, 1) (SplitMix64).
    fn uni(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^= z >> 31;
        (z >> 11) as f64 / (1u64 << 52) as f64 - 1.0
    }
}

/// Scales `x` so that its peak is `peak` (full scale = 1.0).
fn peak_to(mut x: Vec<f64>, peak: f64) -> Vec<f64> {
    let m = x.iter().fold(0.0f64, |m, v| m.max(v.abs()));
    x.iter_mut().for_each(|v| *v *= peak / m);
    x
}

/// Pink noise (Paul Kellet's refined filter on uniform white noise).
fn pink(n: usize, rng: &mut Rng) -> Vec<f64> {
    let mut b = [0.0f64; 7];
    (0..n)
        .map(|_| {
            let w = rng.uni();
            b[0] = 0.99886 * b[0] + w * 0.0555179;
            b[1] = 0.99332 * b[1] + w * 0.0750759;
            b[2] = 0.96900 * b[2] + w * 0.1538520;
            b[3] = 0.86650 * b[3] + w * 0.3104856;
            b[4] = 0.55000 * b[4] + w * 0.5329522;
            b[5] = -0.7616 * b[5] - w * 0.0168980;
            let y = b.iter().sum::<f64>() + w * 0.5362;
            b[6] = w * 0.115926;
            y
        })
        .collect()
}

/// Square of frequency `f` (exact two-sample and four-sample patterns at fs/2 and fs/4).
fn square(fs: f64, f: f64, n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| {
            let s = if f == fs / 2.0 {
                i % 2 == 0
            } else if f == fs / 4.0 {
                (i / 2) % 2 == 0
            } else {
                (2.0 * std::f64::consts::PI * f * (i as f64 + 0.5) / fs).sin() >= 0.0
            };
            if s {
                1.0
            } else {
                -1.0
            }
        })
        .collect()
}

/// The legal test signals at a PCM rate: (name, samples).
fn signals(fs: u32) -> Vec<(String, Vec<f64>)> {
    let fsf = f64::from(fs);
    let n = (SECONDS * fsf) as usize;
    let mut rng = Rng(0x5EED ^ u64::from(fs));
    let t = |i: usize| i as f64 / fsf;
    let tau = 2.0 * std::f64::consts::PI;
    let mut v: Vec<(String, Vec<f64>)> = Vec::new();
    if fs == 88_200 || fs == 48_000 {
        for k in [2.0, 4.0] {
            for f in [1000.0, 5000.0, 10_000.0] {
                let x = (0..n)
                    .map(|i| (k * (tau * f * t(i)).sin()).clamp(-1.0, 1.0))
                    .collect();
                v.push((format!("sine {f} Hz x{k} clipped"), x));
            }
        }
        for d in [0.5, 0.75, 1.0, -1.0] {
            v.push((format!("DC {d}"), vec![d; n]));
        }
        for db in [0.0, -3.0] {
            let g = 10f64.powf(db / 20.0);
            let w = (0..n).map(|_| rng.uni()).collect();
            v.push((format!("white {db} dBFS"), peak_to(w, g)));
            let p = pink(n, &mut rng);
            v.push((format!("pink {db} dBFS"), peak_to(p, g)));
        }
    } else {
        v.push((
            "sine 20 kHz full scale".into(),
            (0..n).map(|i| (tau * 20_000.0 * t(i)).sin()).collect(),
        ));
    }
    v.push((
        "random +-full scale".into(),
        (0..n)
            .map(|_| if rng.uni() < 0.0 { -1.0 } else { 1.0 })
            .collect(),
    ));
    for f in [1000.0, 10_000.0, fsf / 4.0, fsf / 2.0] {
        v.push((format!("square {f} Hz"), square(fsf, f, n)));
    }
    // full-scale steps every 0.1 s, and single-sample full-scale impulses 100 times a second
    let half = fs as usize / 10;
    v.push((
        "steps".into(),
        (0..n)
            .map(|i| if (i / half) % 2 == 0 { 1.0 } else { -1.0 })
            .collect(),
    ));
    v.push((
        "impulses".into(),
        (0..n)
            .map(|i| {
                if i % (fs as usize / 100) == 0 {
                    1.0
                } else {
                    0.0
                }
            })
            .collect(),
    ));
    v
}

/// Signals converted together, as the channels of one stream.
type Group = std::sync::Arc<Vec<(String, Vec<f64>)>>;

/// The counters of one conversion: (name, limited, clipped, resets) per signal.
type Counts = Vec<(String, u64, u64, u64)>;

/// One conversion: up to six signals as the channels of one stream.
struct Job {
    band: Band,
    order: usize,
    mult: u32,
    fs: u32,
    gain_db: Option<f64>,
    sigs: Group,
}

/// Every (band, order, output rate) the library accepts.
fn accepted() -> Vec<(Band, usize, u32)> {
    let mut v = Vec::new();
    for band in [Band::Audio] {
        for mult in [64, 128, 256] {
            for &order in accepted_orders(band, mult) {
                v.push((band, order, mult));
            }
        }
    }
    v
}

/// Sines at 0 dB SACD: full scale at 88.2 kHz, converted with a gain of 0 dB.
fn holds() -> Vec<(String, Vec<f64>)> {
    let fs = 88_200.0;
    let n = (SECONDS * fs) as usize;
    [1000.0, 10_000.0, 20_000.0]
        .into_iter()
        .map(|f| {
            let x = (0..n)
                .map(|i| (2.0 * std::f64::consts::PI * f * i as f64 / fs).sin())
                .collect();
            (format!("sine {f} Hz at 0 dB SACD"), x)
        })
        .collect()
}

/// Converts a job at the default input limit; returns (name, limited, clipped, resets) per
/// signal.
fn run(j: &Job) -> Counts {
    let mut o = Options::new(Output::Dsd { mult: j.mult });
    o.band = j.band;
    o.order = j.order;
    if let Some(g) = j.gain_db {
        o.gain_db = g;
    }
    let ch = j.sigs.len() as u16;
    let mut s = Stream::new(InputFormat::Pcm { rate: j.fs }, ch, &o).unwrap();
    let mut sink = |_: &[Vec<u8>]| Ok(());
    let step = 8192;
    let n = j.sigs[0].1.len();
    let mut a = 0;
    while a < n {
        let b = (a + step).min(n);
        let chans: Vec<&[f64]> = j.sigs.iter().map(|(_, x)| &x[a..b]).collect();
        s.push_pcm(&chans, &mut sink).unwrap();
        a = b;
    }
    s.finish(&mut sink).unwrap();
    j.sigs
        .iter()
        .zip(s.counters())
        .map(|((name, _), k)| (name.clone(), k.limited, k.clipped, k.resets))
        .collect()
}

/// What a run must show besides no clipped state and no reset.
#[derive(Clone, Copy, PartialEq)]
enum Limited {
    /// Nothing limited, except on the signals whose true peak is above +6 dBTP.
    NoneOnLegal,
    /// The limiter may work (a louder setting).
    Allowed,
}

/// Signals of [`signals`] whose true peak exceeds +6 dBTP: outside the legal set, so the
/// limiter may work on them at the defaults.
fn beyond_true_peak(name: &str) -> bool {
    name.starts_with("random") || name == "white 0 dBFS"
}

/// Runs the jobs, at most one per CPU thread at a time; fails on any clipped state or
/// reset, and with [`Limited::NoneOnLegal`] on any limited sample of a legal signal.
fn check(jobs: &[Job], what: &str, rule: Limited) {
    let threads = std::thread::available_parallelism().map_or(4, |n| n.get());
    let next = std::sync::atomic::AtomicUsize::new(0);
    let results: Vec<(usize, Counts)> = std::thread::scope(|sc| {
        let hs: Vec<_> = (0..threads.min(jobs.len()))
            .map(|_| {
                sc.spawn(|| {
                    let mut out = Vec::new();
                    loop {
                        let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        let Some(j) = jobs.get(i) else { break };
                        out.push((i, run(j)));
                    }
                    out
                })
            })
            .collect();
        hs.into_iter().flat_map(|h| h.join().unwrap()).collect()
    });
    let mut bad = Vec::new();
    let mut signals = 0;
    for (i, res) in results {
        let j = &jobs[i];
        for (name, limited, clipped, resets) in res {
            signals += 1;
            let limited_legal =
                rule == Limited::NoneOnLegal && limited > 0 && !beyond_true_peak(&name);
            if resets > 0 || clipped > 0 || limited_legal {
                bad.push(format!(
                    "DSD{} {:?} order {} from {} Hz, {name}: limited {limited} clipped {clipped} resets {resets}",
                    j.mult, j.band, j.order, j.fs
                ));
            }
        }
    }
    println!("{what}: {signals} signals in {} conversions", jobs.len());
    assert!(
        bad.is_empty(),
        "limited legal input or modulator overload on {what} input:\n{}",
        bad.join("\n")
    );
}

/// The signal set at every PCM rate, in groups of six: (rate, group).
fn groups() -> Vec<(u32, Group)> {
    let mut v = Vec::new();
    for fs in [88_200, 352_800, 48_000, 96_000, 384_000] {
        for group in signals(fs).chunks(6) {
            v.push((fs, Group::new(group.to_vec())));
        }
    }
    v
}

/// The signal set for one combination, with `gain_db` if given.
fn jobs_for(
    groups: &[(u32, Group)],
    band: Band,
    order: usize,
    mult: u32,
    gain_db: Option<f64>,
) -> Vec<Job> {
    groups
        .iter()
        .map(|(fs, sigs)| Job {
            band,
            order,
            mult,
            fs: *fs,
            gain_db,
            sigs: sigs.clone(),
        })
        .collect()
}

/// The jobs of every accepted combination: the PCM set with `gain_db`, or the sines at
/// 0 dB SACD (`holds`: full scale with a gain of 0 dB).
fn all_combinations(gain_db: Option<f64>, holds_only: bool) -> Vec<Job> {
    let combos = accepted();
    // the defaults are among them, and the list is the measured one
    for mult in [64, 128, 256] {
        let d = Options::new(Output::Dsd { mult });
        assert!(combos.contains(&(d.band, d.order, mult)));
    }
    assert_eq!(combos.len(), 11);
    let groups = groups();
    let holds = Group::new(holds());
    let mut jobs = Vec::new();
    for (band, order, mult) in combos {
        if !holds_only {
            jobs.extend(jobs_for(&groups, band, order, mult, gain_db));
            continue;
        }
        jobs.push(Job {
            band,
            order,
            mult,
            fs: 88_200,
            gain_db: Some(0.0),
            sigs: holds.clone(),
        });
    }
    jobs
}

/// At the defaults, every accepted combination of band, order and output rate: legal input
/// is not limited, and nothing clips a modulator state or resets.
#[test]
fn legal_input_is_not_limited_and_never_overloads_at_the_defaults() {
    assert_eq!(dsd_upsample::DEFAULT_GAIN_DB, -6.0);
    for mult in [64, 128, 256] {
        assert_eq!(Options::new(Output::Dsd { mult }).gain_db, -6.0);
    }
    check(
        &all_combinations(None, false),
        "legal",
        Limited::NoneOnLegal,
    );
}

/// Sines at 0 dB SACD, which takes a gain 6 dB above the default: every accepted
/// combination holds them without a clipped state or a reset. The limiter may touch a few
/// samples where a tone starts (8 to 30 samples of the 20 kHz tone in this run).
#[test]
fn sines_at_0_db_sacd_never_overload_any_accepted_combination() {
    check(&all_combinations(None, true), "0 dB SACD", Limited::Allowed);
}

/// The louder setting, 3 dB above the default (the default of earlier builds), on every
/// accepted combination: the limiter works, and nothing clips a state or resets.
#[test]
fn louder_setting_never_overloads_any_accepted_combination() {
    check(
        &all_combinations(Some(-3.0), false),
        "louder",
        Limited::Allowed,
    );
}

/// The same signals 9 dB louder than the default gain (out of specification), at the
/// default order.
#[test]
fn hot_input_is_limited_without_overload() {
    let groups = groups();
    let mut jobs = Vec::new();
    for mult in [64, 128, 256] {
        let o = Options::new(Output::Dsd { mult });
        jobs.extend(jobs_for(&groups, o.band, o.order, mult, Some(3.0)));
    }
    check(&jobs, "hot", Limited::Allowed);
}

/// Collects one channel of DSD bytes.
struct Bytes(Vec<u8>);

impl DsdWrite for Bytes {
    fn write_bytes(&mut self, data: &[Vec<u8>]) -> dsd_upsample::Result<()> {
        self.0.extend_from_slice(&data[0]);
        Ok(())
    }
    fn finish(&mut self, _samples: u64) -> dsd_upsample::Result<()> {
        Ok(())
    }
}

/// DSD tones held at the Super Audio CD peak level, from DSD64, DSD128 and DSD256, to every
/// accepted DSD128 and DSD256 combination at the defaults: nothing limited, clipped or
/// reset. The tones are 1, 10 and 19 kHz at +3.1 dB SACD (71.4 % modulation) from the
/// test-signal generator, whose second-order modulator carries that level without
/// overload.
#[test]
fn dsd_tones_at_the_sacd_peak_level_are_not_limited() {
    let mut bad = Vec::new();
    let mut n = 0;
    for in_mult in [64u32, 128, 256] {
        let tones: Vec<(String, Vec<u8>)> = [(1000, 3.1), (10_000, 3.1), (19_000, 3.1)]
            .into_iter()
            .map(|(freq, level_db)| {
                let s = Sine {
                    freq,
                    level_db,
                    seconds: SECONDS,
                    channels: 1,
                };
                let mut w = Bytes(Vec::new());
                let k = testsignal::write_dsd_counted(&mut w, in_mult, &s).unwrap();
                assert_eq!(k.clipped, 0, "the generator overloaded");
                (format!("{freq} Hz at {level_db:+} dB SACD"), w.0)
            })
            .collect();
        for (band, order, mult) in accepted() {
            if mult == 64 {
                continue; // DSD64 output is for PCM input
            }
            let mut o = Options::new(Output::Dsd { mult });
            o.band = band;
            o.order = order;
            let fmt = InputFormat::Dsd {
                rate: 44_100 * in_mult,
            };
            let mut s = Stream::new(fmt, tones.len() as u16, &o).unwrap();
            let mut sink = |_: &[Vec<u8>]| Ok(());
            let chans: Vec<&[u8]> = tones.iter().map(|(_, b)| b.as_slice()).collect();
            s.push_dsd(&chans, &mut sink).unwrap();
            s.finish(&mut sink).unwrap();
            for ((name, _), k) in tones.iter().zip(s.counters()) {
                n += 1;
                if k.limited > 0 || k.clipped > 0 || k.resets > 0 {
                    bad.push(format!(
                        "DSD{in_mult} to DSD{mult} order {order}, {name}: {k:?}"
                    ));
                }
            }
        }
    }
    println!("DSD tones: {n} conversions");
    assert!(bad.is_empty(), "limited or overloaded:\n{}", bad.join("\n"));
}

/// A sine of `amp` (full scale = 1.0; 64-bit float input may exceed it) with 10 ms raised
/// cosine fades, so that its true peak is `amp`: `phase` in turns.
fn faded_sine(fs: u32, freq: f64, phase: f64, amp: f64) -> Vec<f64> {
    let fsf = f64::from(fs);
    let n = (SECONDS * fsf) as usize;
    let fade = (0.01 * fsf) as usize;
    let tau = 2.0 * std::f64::consts::PI;
    (0..n)
        .map(|i| {
            let edge = i.min(n - 1 - i).min(fade) as f64 / fade as f64;
            let w = 0.5 - 0.5 * (std::f64::consts::PI * edge).cos();
            amp * w * (tau * (freq * i as f64 / fsf + phase)).sin()
        })
        .collect()
}

/// Limited samples of one PCM signal at the defaults for an output rate.
fn limited_at_defaults(mult: u32, fs: u32, x: &[f64]) -> u64 {
    let o = Options::new(Output::Dsd { mult });
    let mut s = Stream::new(InputFormat::Pcm { rate: fs }, 1, &o).unwrap();
    let mut sink = |_: &[Vec<u8>]| Ok(());
    s.push_pcm(&[x], &mut sink).unwrap();
    s.finish(&mut sink).unwrap();
    let k = s.counters()[0];
    assert_eq!((k.clipped, k.resets), (0, 0));
    k.limited
}

/// The margin of the default gain, pinned: the defaults pass a PCM true peak of +6 dBTP
/// with nothing limited, with 0.17 dB to spare. A change of the default gain, the limit or
/// the level convention that takes this away fails here.
#[test]
fn default_headroom_covers_a_true_peak_of_plus_6_dbtp() {
    // PCM full scale is 0.5 (0 dB SACD) at a gain of 0 dB: the true peak that reaches the
    // limit at the defaults, in dBTP.
    let gain = 10f64.powf(dsd_upsample::DEFAULT_GAIN_DB / 20.0);
    let ceiling_db = 20.0 * (dsd_upsample::DEFAULT_INPUT_LIMIT / (0.5 * gain)).log10();
    assert!(
        (6.0..6.5).contains(&ceiling_db) && (ceiling_db - 6.172).abs() < 0.001,
        "the defaults limit above {ceiling_db:.3} dBTP"
    );
    let db = |d: f64| 10f64.powf(d / 20.0);
    // a 1 kHz sine, and a sine at a quarter of the sample rate sampled at 45 degrees (the
    // classic intersample over: its samples reach 0.707 of its peak)
    for (fs, freq, phase) in [(88_200, 1000.0, 0.0), (44_100, 11_025.0, 0.125)] {
        for mult in [64, 128, 256] {
            let at6 = limited_at_defaults(mult, fs, &faded_sine(fs, freq, phase, db(6.0)));
            assert_eq!(
                at6, 0,
                "{freq} Hz at +6 dBTP is limited at DSD{mult} ({at6} samples)"
            );
            let above = limited_at_defaults(mult, fs, &faded_sine(fs, freq, phase, db(6.4)));
            assert!(
                above > 0,
                "{freq} Hz at +6.4 dBTP is not limited at DSD{mult}"
            );
        }
    }
}

/// The level of the defaults: PCM full scale reaches the modulator at 25 % modulation
/// (-6 dB SACD), 6 dB below the reference alignment of a gain of 0 dB, where PCM full scale
/// is 0 dB SACD (50 % modulation). Measured as the density of ones of a full-scale DC input.
#[test]
fn pcm_full_scale_is_minus_6_db_sacd_at_the_defaults() {
    for (gain_db, modulation) in [(None, 0.5 * 10f64.powf(-6.0 / 20.0)), (Some(0.0), 0.5)] {
        let fs = 88_200;
        let x = vec![1.0f64; fs as usize];
        let mut o = Options::new(Output::Dsd { mult: 64 });
        if let Some(g) = gain_db {
            o.gain_db = g;
        }
        let mut s = Stream::new(InputFormat::Pcm { rate: fs }, 1, &o).unwrap();
        let mut bytes = Vec::new();
        let mut sink = |b: &[Vec<u8>]| {
            bytes.extend_from_slice(&b[0]);
            Ok(())
        };
        s.push_pcm(&[&x], &mut sink).unwrap();
        s.finish(&mut sink).unwrap();
        // the steady part: skip the first and the last tenth
        let mid = &bytes[bytes.len() / 10..bytes.len() * 9 / 10];
        let ones: u64 = mid.iter().map(|b| u64::from(b.count_ones())).sum();
        let density = ones as f64 / (8 * mid.len()) as f64;
        let measured = 2.0 * density - 1.0;
        assert!(
            (measured - modulation).abs() < 0.0005,
            "gain {gain_db:?}: full scale at {measured:.4} of full modulation, expected {modulation:.4}"
        );
    }
}
