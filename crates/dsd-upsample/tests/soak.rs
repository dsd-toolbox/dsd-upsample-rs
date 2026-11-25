// SPDX-License-Identifier: MIT OR Apache-2.0
//! Soak test: many conversions in one process. After every conversion, including
//! cancelled and failed ones, the thread count returns to its baseline (no worker outlives a
//! conversion), and resident memory plateaus. Linux only (reads /proc/self).
//!
//! `SOAK_N` sets the number of conversions (default 64, threads only; the release gate ran
//! 1,200; at least 8, one of each kind). The memory check runs from 800 conversions: before
//! that the allocator's arenas are still filling and RSS rises without any leak.
#![cfg(target_os = "linux")]

use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
use dsd_upsample::dsd2pcm::io::{DsdInfo, DsdRead, DsdWrite};
use dsd_upsample::dsd2pcm::wav::{WavFormat, WavReader};
use dsd_upsample::dsd2pcm::{Error, Input, PcmRate};
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{
    convert, convert_file_with, convert_with, is_cancelled, InputFormat, Options, Output, Stream,
};
use std::io::Cursor;

fn threads() -> usize {
    std::fs::read_dir("/proc/self/task").unwrap().count()
}

fn rss_kb() -> u64 {
    let s = std::fs::read_to_string("/proc/self/status").unwrap();
    s.lines()
        .find_map(|l| l.strip_prefix("VmRSS:"))
        .and_then(|v| v.trim().trim_end_matches("kB").trim().parse().ok())
        .unwrap()
}

fn sine(ch: u16, seconds: f64, level_db: f64) -> Sine {
    Sine {
        freq: 997,
        level_db,
        seconds,
        channels: ch,
    }
}

fn dsf_bytes(mult: u32, s: &Sine) -> Vec<u8> {
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), s.channels, 44_100 * mult, None).unwrap();
    testsignal::write_dsd_to(&mut w, mult, s).unwrap();
    w.into_inner().into_inner()
}

fn wav_bytes(fs: u32, s: &Sine) -> Vec<u8> {
    testsignal::write_wav_to(Cursor::new(Vec::new()), fs, WavFormat::I24, s)
        .unwrap()
        .into_inner()
}

/// A sink that fails after `left` writes.
struct FailingSink {
    left: usize,
}

impl DsdWrite for FailingSink {
    fn write_bytes(&mut self, _: &[Vec<u8>]) -> dsd_upsample::Result<()> {
        if self.left == 0 {
            return Err(Error::Io(std::io::Error::other("disk full (test)")));
        }
        self.left -= 1;
        Ok(())
    }
    fn finish(&mut self, _: u64) -> dsd_upsample::Result<()> {
        Ok(())
    }
}

/// A source that ends long before its declared length.
struct Short(u32);

impl DsdRead for Short {
    fn info(&self) -> DsdInfo {
        DsdInfo {
            channels: 2,
            sample_rate: 2_822_400,
            samples: 1 << 30,
        }
    }
    fn read_bytes(&mut self, max: usize, out: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
        if self.0 == 0 {
            return Ok(0);
        }
        self.0 -= 1;
        let n = max.min(4096);
        for o in out.iter_mut() {
            o.extend(std::iter::repeat_n(0x69, n));
        }
        Ok(n)
    }
}

#[test]
fn soak_threads_return_and_memory_plateaus() {
    let n: usize = std::env::var("SOAK_N")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(64);
    assert!(
        n >= 8,
        "SOAK_N={n}: needs at least 8 conversions (one of each kind)"
    );
    let dir = std::env::temp_dir().join(format!("dsdup-soak-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let dsf64 = dsf_bytes(64, &sine(2, 0.4, -6.0));
    let dsf128 = dsf_bytes(128, &sine(2, 0.2, -6.0));
    // 44.1 kHz-family input and 48 kHz-family input (through the resampler), in turn
    let wavs = [
        wav_bytes(88_200, &sine(2, 0.4, -6.0)),
        wav_bytes(96_000, &sine(2, 0.4, -6.0)),
        wav_bytes(48_000, &sine(2, 0.4, -6.0)),
    ];
    let six = dsf_bytes(64, &sine(6, 0.2, -6.0));
    let dsf_path = dir.join("in.dsf");
    std::fs::write(&dsf_path, &dsf64).unwrap();

    let baseline = threads();
    let mut rss = Vec::with_capacity(n);
    let mut kinds = [0usize; 8];
    let mut settle_ms = 0;
    for i in 0..n {
        let kind = i % 8;
        let mult = [64, 128, 256][i % 3];
        let out_mult = if mult == 64 { 128 } else { mult };
        let mut o = Options::new(Output::Dsd { mult: out_mult });
        // every order the output rate accepts, in turn
        let orders = dsd_upsample::accepted_orders(o.band, out_mult);
        let order = orders[(i / 3) % orders.len()];
        o.order = order;
        o.threads = i % 2 == 0;
        o.dither = i % 5 == 0;
        let dsd =
            |b: &Vec<u8>| Input::Dsd(Box::new(DsfReader::new(Cursor::new(b.clone())).unwrap()));
        let sink = || DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 256, None).unwrap();
        match kind {
            // whole conversions: DSD64, DSD128 and WAV input (88.2, 96 and 48 kHz in turn),
            // 2 and 6 channels
            0 => {
                convert(dsd(&dsf64), &mut sink(), &o).unwrap();
            }
            1 => {
                convert(dsd(&dsf128), &mut sink(), &o).unwrap();
            }
            2 => {
                let mut o = o;
                o.output = Output::Dsd { mult };
                let wav = &wavs[(i / 8) % wavs.len()];
                let r = WavReader::new(Cursor::new(wav.clone())).unwrap();
                convert(Input::Pcm(Box::new(r)), &mut sink(), &o).unwrap();
            }
            3 => {
                let mut w = DsfWriter::new(Cursor::new(Vec::new()), 6, 44_100 * 128, None).unwrap();
                convert(dsd(&six), &mut w, &o).unwrap();
            }
            // cancelled part-way through
            4 => {
                let mut calls = 0;
                let r = convert_with(
                    dsd(&dsf64),
                    &mut sink(),
                    &o,
                    Some(&mut |_, _| {
                        calls += 1;
                        calls < 2
                    }),
                );
                assert!(r.as_ref().is_err_and(is_cancelled), "{r:?}");
            }
            // the sink fails part-way through, then a source that ends early
            5 => {
                let r = convert(dsd(&dsf64), &mut FailingSink { left: 1 }, &o);
                assert!(r.is_err());
                let r = convert(Input::Dsd(Box::new(Short(3))), &mut sink(), &o);
                assert!(r.is_err());
            }
            // streaming API, odd push sizes; every fourth one abandoned without finish
            6 => {
                let mut s = Stream::new(InputFormat::Dsd { rate: 2_822_400 }, 2, &o).unwrap();
                let mut r = DsfReader::new(Cursor::new(dsf64.clone())).unwrap();
                let mut chans = vec![Vec::new(); 2];
                while r.read_bytes(1 << 20, &mut chans).unwrap() > 0 {}
                let mut emit = |_: &[Vec<u8>]| Ok(());
                let step = 1 + (i * 7919) % 6000;
                for k in (0..chans[0].len()).step_by(step) {
                    let e = (k + step).min(chans[0].len());
                    s.push_dsd(&[&chans[0][k..e], &chans[1][k..e]], &mut emit)
                        .unwrap();
                }
                if i % 4 != 2 {
                    s.finish(&mut emit).unwrap();
                }
            }
            // file conversion to PCM, cancelled every other time
            _ => {
                let mut po = Options::new(Output::Pcm(PcmRate::Hz176400));
                po.threads = i % 2 == 0;
                let mut calls = 0;
                let r = convert_file_with(
                    &dsf_path,
                    &dir.join("out.wav"),
                    &po,
                    Some(&mut |_, _| {
                        calls += 1;
                        i % 16 != 7 || calls < 2
                    }),
                );
                assert!(r.is_ok() || r.as_ref().is_err_and(is_cancelled), "{r:?}");
            }
        }
        kinds[kind] += 1;
        // Workers are joined before a conversion returns, but the kernel can list a joined
        // thread in /proc for a moment while it is reaped: wait up to 2 s for the count to
        // settle. A leaked worker never leaves.
        let mut t = threads();
        let mut waited = 0;
        while t != baseline && waited < 200 {
            std::thread::sleep(std::time::Duration::from_millis(10));
            waited += 1;
            t = threads();
        }
        settle_ms = settle_ms.max(waited * 10);
        assert_eq!(
            t, baseline,
            "iteration {i} (kind {kind}): {t} threads, baseline {baseline}"
        );
        rss.push(rss_kb());
    }
    std::fs::remove_dir_all(&dir).unwrap();
    let marks: Vec<String> = (1..=10)
        .map(|k| format!("{}", rss[(k * n / 10).max(1) - 1]))
        .collect();
    eprintln!("soak: RSS kB at each 10 %: {}", marks.join(" "));
    // Plateau: per-conversion RSS swings with the allocator's arenas (tens of MB between
    // conversions), so compare averages, not peaks: the last quarter's mean RSS must not
    // exceed the second quarter's by more than 4 MiB. A leak grows steadily and fails this.
    let q = n / 4;
    let mean = |v: &[u64]| v.iter().sum::<u64>() / v.len() as u64;
    let early = mean(&rss[q..2 * q]);
    let late = mean(&rss[n - q..]);
    eprintln!(
        "soak: {n} conversions {kinds:?}, threads {baseline} -> {} every time (longest settle {settle_ms} ms), RSS kB first {} mean-q2 {early} mean-q4 {late} max {}",
        threads(),
        rss[0],
        rss.iter().max().unwrap()
    );
    if n < 800 {
        eprintln!("soak: memory check skipped below 800 conversions (arenas still filling)");
        return;
    }
    assert!(
        late <= early + 4096,
        "RSS grew: second-quarter mean {early} kB, last-quarter mean {late} kB"
    );
}
