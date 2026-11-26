// SPDX-License-Identifier: MIT OR Apache-2.0
//! Live heap per conversion, counted exactly: a host that converts many times in one
//! process gets every byte back after each conversion, on every way a conversion can end,
//! and no worker thread outlives it. Linux only (reads /proc/self).
//!
//! The referee is a counting global allocator: the live byte count is updated inside each
//! allocator call, so nothing is sampled and no event can be lost. After one warm-up pass
//! (one conversion of each kind: the one-time allocations), the live count after every
//! conversion, workers joined, must EQUAL the baseline, byte for byte, and the thread count
//! must be back to its baseline. No margin: the smallest leak it detects is 1 byte.
//!
//! Kinds: whole conversions of each input class (DSD256 and DSD64 stereo, 6-channel DSD64,
//! PCM at 88.2 kHz and 48 kHz, DSD to PCM, the serial path); the failure paths (cancelled,
//! the sink failing, a source ending early); hostile files (truncated, a header declaring
//! no samples over real data, a header declaring far more samples than the file holds, and
//! bytes that are no DSF at all).
//!
//! Positive controls run first and must FAIL the same check (rules: a gate never seen to
//! fail proves nothing): 4,096 bytes leaked per conversion; 16 bytes leaked on the
//! sink-error path only; a thread left running past its conversion. If a control passes,
//! the test fails.
//!
//! This test has its own `main` (`harness = false`), so no test-harness thread allocates
//! while it measures. `HEAP_FLAT_N` sets the rounds of the gate run (default 3; each round
//! converts every kind once). `HEAP_FLAT_INPUT` names a DSF file to use for the whole
//! conversions of DSF input instead of the generated DSD256 one. `HEAP_FLAT_TSV` names a
//! file to write the gate run's per-conversion series to.

#[cfg(not(target_os = "linux"))]
fn main() {
    println!("heap_flat: Linux only (reads /proc/self); nothing to do");
}

#[cfg(target_os = "linux")]
fn main() {
    linux::main();
}

#[cfg(target_os = "linux")]
mod linux {
    use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
    use dsd_upsample::dsd2pcm::io::{DsdInfo, DsdRead, DsdWrite};
    use dsd_upsample::dsd2pcm::wav::WavFormat;
    use dsd_upsample::dsd2pcm::{Error, Input, PcmRate};
    use dsd_upsample::testsignal::{self, Sine};
    use dsd_upsample::{convert, convert_file, convert_file_with, is_cancelled, Options, Output};
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::io::Cursor;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicUsize, Ordering::Relaxed};
    use std::time::{Duration, Instant};

    static LIVE: AtomicUsize = AtomicUsize::new(0);
    static PEAK: AtomicUsize = AtomicUsize::new(0);

    struct Counting;

    fn add(n: usize) {
        let live = LIVE.fetch_add(n, Relaxed) + n;
        PEAK.fetch_max(live, Relaxed);
    }

    // SAFETY: every call is passed to the system allocator unchanged; only counters are kept.
    unsafe impl GlobalAlloc for Counting {
        unsafe fn alloc(&self, l: Layout) -> *mut u8 {
            let p = System.alloc(l);
            if !p.is_null() {
                add(l.size());
            }
            p
        }
        unsafe fn alloc_zeroed(&self, l: Layout) -> *mut u8 {
            let p = System.alloc_zeroed(l);
            if !p.is_null() {
                add(l.size());
            }
            p
        }
        unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
            LIVE.fetch_sub(l.size(), Relaxed);
            System.dealloc(p, l);
        }
        unsafe fn realloc(&self, p: *mut u8, l: Layout, new: usize) -> *mut u8 {
            let q = System.realloc(p, l, new);
            if !q.is_null() {
                // The caller owns the block across this call, so the two updates cannot be
                // interleaved with another thread's use of the same block.
                LIVE.fetch_sub(l.size(), Relaxed);
                add(new);
            }
            q
        }
    }

    #[global_allocator]
    static A: Counting = Counting;

    fn threads() -> usize {
        std::fs::read_dir("/proc/self/task").unwrap().count()
    }

    /// Waits up to 2 s for the thread count to reach `baseline` (a joined thread can stay
    /// listed in /proc for a moment while the kernel reaps it); returns the ms waited.
    fn settle(baseline: usize) -> usize {
        let mut waited = 0;
        while threads() != baseline && waited < 200 {
            std::thread::sleep(Duration::from_millis(10));
            waited += 1;
        }
        waited * 10
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
                sample_rate: 11_289_600,
                samples: 1 << 32,
            }
        }
        fn read_bytes(&mut self, max: usize, out: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
            if self.0 == 0 {
                return Ok(0);
            }
            self.0 -= 1;
            let n = max.min(32_768);
            for o in out.iter_mut() {
                o.extend(std::iter::repeat_n(0x69, n));
            }
            Ok(n)
        }
    }

    /// What a conversion must end with.
    #[derive(Clone, Copy, PartialEq)]
    enum End {
        Ok,
        Cancelled,
        Err,
        /// Hostile input: refused or converted, both acceptable; never a panic.
        Either,
    }

    struct Kind {
        name: &'static str,
        end: End,
    }

    const fn k(name: &'static str, end: End) -> Kind {
        Kind { name, end }
    }

    const KINDS: [Kind; 14] = [
        k("dsd256-stereo", End::Ok),
        k("dsd64-stereo", End::Ok),
        k("dsd64-6ch", End::Ok),
        k("pcm88k2", End::Ok),
        k("pcm48k-resampled", End::Ok),
        k("dsd-to-pcm", End::Ok),
        k("serial-path", End::Ok),
        k("cancelled", End::Cancelled),
        k("sink-error", End::Err),
        k("short-source", End::Err),
        k("truncated-file", End::Either),
        k("zero-declared", End::Err),
        k("over-declared", End::Either),
        k("not-dsf", End::Err),
    ];

    /// A deliberate fault, for the positive controls.
    #[derive(Clone, Copy, Debug)]
    enum Fault {
        None,
        /// Leak this many bytes after every conversion.
        LeakEvery(usize),
        /// Leak this many bytes after every conversion of this kind.
        LeakOn(&'static str, usize),
        /// Leave a thread running for this long after every conversion of this kind.
        StrayThreadOn(&'static str, Duration),
    }

    struct Inputs {
        dir: PathBuf,
        dsd256: PathBuf,
        dsd64: PathBuf,
        six: PathBuf,
        wav88: PathBuf,
        wav48: PathBuf,
        truncated: PathBuf,
        zero_declared: PathBuf,
        over_declared: PathBuf,
        not_dsf: PathBuf,
    }

    fn sine(channels: u16, seconds: f64) -> Sine {
        Sine {
            freq: 997,
            level_db: -6.0,
            seconds,
            channels,
        }
    }

    fn inputs() -> Inputs {
        let dir = std::env::temp_dir().join(format!("dsdup-heapflat-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = |n: &str| dir.join(n);
        // DSD256 stereo is the class whose decimator history grows twice.
        let dsd256 = match std::env::var_os("HEAP_FLAT_INPUT") {
            Some(f) => PathBuf::from(f),
            None => {
                testsignal::write_dsd(&p("in256.dsf"), 256, &sine(2, 0.5)).unwrap();
                p("in256.dsf")
            }
        };
        testsignal::write_dsd(&p("in64.dsf"), 64, &sine(2, 0.5)).unwrap();
        testsignal::write_dsd(&p("six.dsf"), 64, &sine(6, 0.25)).unwrap();
        testsignal::write_wav(&p("in88.wav"), 88_200, WavFormat::I24, &sine(2, 0.5)).unwrap();
        testsignal::write_wav(&p("in48.wav"), 48_000, WavFormat::I24, &sine(2, 0.5)).unwrap();
        let good = std::fs::read(p("in64.dsf")).unwrap();
        // Cut in the middle of the data chunk.
        std::fs::write(p("truncated.dsf"), &good[..good.len() * 3 / 5]).unwrap();
        // The fmt chunk's sample count (bytes 64..72 of a DSF file) set to 0 over real data,
        // and to 2^40 over the same data.
        let mut zero = good.clone();
        zero[64..72].copy_from_slice(&0u64.to_le_bytes());
        std::fs::write(p("zero.dsf"), &zero).unwrap();
        let mut over = good.clone();
        over[64..72].copy_from_slice(&(1u64 << 40).to_le_bytes());
        std::fs::write(p("over.dsf"), &over).unwrap();
        let junk: Vec<u8> = (0..65_536u32)
            .map(|i| (i.wrapping_mul(2_654_435_761) >> 13) as u8)
            .collect();
        std::fs::write(p("junk.dsf"), &junk).unwrap();
        Inputs {
            dsd256,
            dsd64: p("in64.dsf"),
            six: p("six.dsf"),
            wav88: p("in88.wav"),
            wav48: p("in48.wav"),
            truncated: p("truncated.dsf"),
            zero_declared: p("zero.dsf"),
            over_declared: p("over.dsf"),
            not_dsf: p("junk.dsf"),
            dir,
        }
    }

    /// One conversion of `kind`; returns how it ended.
    fn one(kind: usize, ins: &Inputs) -> End {
        let out_dsf = ins.dir.join("out.dsf");
        let d128 = Options::new(Output::Dsd { mult: 128 });
        assert!(d128.threads, "the pipelined path is the default");
        let class = |r: dsd_upsample::Result<dsd_upsample::Report>| match r {
            Ok(_) => End::Ok,
            Err(e) if is_cancelled(&e) => End::Cancelled,
            Err(_) => End::Err,
        };
        let file = |inp: &Path, out: &Path, o: &Options| class(convert_file(inp, out, o));
        match KINDS[kind].name {
            "dsd256-stereo" => file(&ins.dsd256, &out_dsf, &d128),
            "dsd64-stereo" => file(
                &ins.dsd64,
                &out_dsf,
                &Options::new(Output::Dsd { mult: 256 }),
            ),
            "dsd64-6ch" => file(&ins.six, &out_dsf, &d128),
            "pcm88k2" => file(&ins.wav88, &out_dsf, &d128),
            "pcm48k-resampled" => file(
                &ins.wav48,
                &out_dsf,
                &Options::new(Output::Dsd { mult: 64 }),
            ),
            "dsd-to-pcm" => file(
                &ins.dsd64,
                &ins.dir.join("out.wav"),
                &Options::new(Output::Pcm(PcmRate::Hz176400)),
            ),
            "serial-path" => {
                let mut o = d128;
                o.threads = false;
                file(&ins.dsd64, &out_dsf, &o)
            }
            "cancelled" => {
                let mut calls = 0;
                class(convert_file_with(
                    &ins.dsd256,
                    &out_dsf,
                    &d128,
                    Some(&mut |_, _| {
                        calls += 1;
                        calls < 3
                    }),
                ))
            }
            "sink-error" => {
                let f = std::fs::File::open(&ins.dsd256).unwrap();
                let r = DsfReader::new(std::io::BufReader::new(f)).unwrap();
                class(convert(
                    Input::Dsd(Box::new(r)),
                    &mut FailingSink { left: 2 },
                    &d128,
                ))
            }
            "short-source" => {
                let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 128, None).unwrap();
                class(convert(Input::Dsd(Box::new(Short(5))), &mut w, &d128))
            }
            "truncated-file" => file(&ins.truncated, &out_dsf, &d128),
            "zero-declared" => file(&ins.zero_declared, &out_dsf, &d128),
            "over-declared" => file(&ins.over_declared, &out_dsf, &d128),
            "not-dsf" => file(&ins.not_dsf, &out_dsf, &d128),
            k => unreachable!("{k}"),
        }
    }

    struct Row {
        kind: usize,
        end: End,
        live_ret: isize,
        live: isize,
        peak: usize,
        thr_ret: usize,
        thr: usize,
        settle_ms: usize,
    }

    /// Warm-up (if `warm`), then `rounds` rounds of every kind with `fault` injected. Returns
    /// the rows and the failures of the heap-flat and thread checks (empty: flat).
    fn run(ins: &Inputs, rounds: usize, fault: Fault, warm: bool) -> (Vec<Row>, Vec<String>) {
        let inject = |kind: usize| match fault {
            Fault::None => {}
            Fault::LeakEvery(n) => std::mem::forget(vec![0u8; n]),
            Fault::LeakOn(k, n) => {
                if KINDS[kind].name == k {
                    std::mem::forget(vec![0u8; n]);
                }
            }
            Fault::StrayThreadOn(k, d) => {
                if KINDS[kind].name == k {
                    drop(std::thread::spawn(move || std::thread::sleep(d)));
                }
            }
        };
        let threads0 = threads();
        let mut failures = Vec::new();
        // Warm-up: the one-time allocations (lazily built tables, this thread's state).
        for (kind, k) in KINDS.iter().enumerate().filter(|_| warm) {
            let end = one(kind, ins);
            if k.end != End::Either && end != k.end {
                failures.push(format!("warm-up {}: ended {}", k.name, name(end)));
            }
            settle(threads0);
        }
        let n = rounds * KINDS.len();
        let mut rows: Vec<Row> = Vec::with_capacity(n);
        let base = LIVE.load(Relaxed);
        for i in 0..n {
            let kind = i % KINDS.len();
            PEAK.store(LIVE.load(Relaxed), Relaxed);
            let end = one(kind, ins);
            inject(kind);
            let (live_ret, thr_ret) = (LIVE.load(Relaxed), threads());
            let settle_ms = settle(threads0);
            let k = &KINDS[kind];
            if k.end != End::Either && end != k.end {
                failures.push(format!(
                    "conversion {} ({}): ended {}",
                    i + 1,
                    k.name,
                    name(end)
                ));
            }
            rows.push(Row {
                kind,
                end,
                live_ret: live_ret as isize - base as isize,
                live: LIVE.load(Relaxed) as isize - base as isize,
                peak: PEAK.load(Relaxed).saturating_sub(base),
                thr_ret,
                thr: threads(),
                settle_ms,
            });
        }
        for (i, r) in rows.iter().enumerate() {
            if r.live != 0 || r.thr != threads0 {
                failures.push(format!(
                    "conversion {} ({}): live heap {:+} B and {} threads after it, baseline {} threads",
                    i + 1,
                    KINDS[r.kind].name,
                    r.live,
                    r.thr,
                    threads0
                ));
            }
        }
        // The queues are bounded, so the peak of one kind varies only with the blocks in
        // flight (thread timing): it must not climb from round to round.
        for (kind, k) in KINDS.iter().enumerate() {
            let p: Vec<usize> = rows
                .iter()
                .filter(|r| r.kind == kind)
                .map(|r| r.peak)
                .collect();
            if let (Some(&lo), Some(&hi)) = (p.iter().min(), p.iter().max()) {
                if hi > 2 * lo + (4 << 20) {
                    failures.push(format!(
                        "{}: peak live heap between {lo} and {hi} B",
                        k.name
                    ));
                }
            }
        }
        (rows, failures)
    }

    fn name(e: End) -> &'static str {
        match e {
            End::Ok => "ok",
            End::Cancelled => "cancelled",
            End::Err => "error",
            End::Either => "either",
        }
    }

    fn tsv(rows: &[Row]) -> String {
        let mut s = String::from(
            "n\tkind\tended\tlive_at_return\tlive_settled\tpeak\tthreads_at_return\tthreads_settled\tsettle_ms\n",
        );
        for (i, r) in rows.iter().enumerate() {
            s += &format!(
                "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n",
                i + 1,
                KINDS[r.kind].name,
                name(r.end),
                r.live_ret,
                r.live,
                r.peak,
                r.thr_ret,
                r.thr,
                r.settle_ms
            );
        }
        s
    }

    pub fn main() {
        let t0 = Instant::now();
        let rounds: usize = std::env::var("HEAP_FLAT_N")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(3);
        assert!(rounds >= 1, "HEAP_FLAT_N must be at least 1");
        let ins = inputs();
        let mut bad = Vec::new();
        let mut checks = 0;

        // Positive controls: each must be caught by the same checks as the gate, where the
        // fault is: every row for the per-conversion leak, exactly 16 B from the first
        // sink-error conversion on (and 0 before it), the thread count after a cancelled one.
        type Expect = fn(&[Row], usize) -> bool;
        let controls: [(&str, Fault, Expect); 3] = [
            (
                "leak 4096 B per conversion",
                Fault::LeakEvery(4096),
                |rows, _| {
                    rows.iter()
                        .enumerate()
                        .all(|(i, r)| r.live == 4096 * (i as isize + 1))
                },
            ),
            (
                "leak 16 B on the sink-error path only",
                Fault::LeakOn("sink-error", 16),
                |rows, _| {
                    let k = KINDS.iter().position(|k| k.name == "sink-error").unwrap();
                    rows.iter()
                        .all(|r| r.live == if r.kind < k { 0 } else { 16 })
                },
            ),
            (
                "thread left running 3 s after a cancelled conversion",
                Fault::StrayThreadOn("cancelled", Duration::from_secs(3)),
                |rows, t0| {
                    let k = KINDS.iter().position(|k| k.name == "cancelled").unwrap();
                    rows.iter().any(|r| r.kind == k && r.thr > t0)
                },
            ),
        ];
        let mut failed = 0;
        for (i, (what, fault, expect)) in controls.into_iter().enumerate() {
            checks += 1;
            let t = threads();
            let (rows, failures) = run(&ins, 1, fault, i == 0);
            let located = expect(&rows, t);
            match (failures.first(), located) {
                (Some(f), true) => println!(
                    "heap_flat: positive control \"{what}\": caught as expected, where injected ({} findings; first: {f})",
                    failures.len()
                ),
                (Some(_), false) => {
                    failed += 1;
                    bad.push(format!("positive control \"{what}\": failed, but not where the fault was injected:\n{}", tsv(&rows)));
                }
                (None, _) => {
                    failed += 1;
                    bad.push(format!("positive control \"{what}\" was NOT caught"));
                }
            }
            // The stray thread ends on its own; wait for it before the next run's baseline.
            if matches!(fault, Fault::StrayThreadOn(..)) {
                std::thread::sleep(Duration::from_millis(3100));
            }
        }

        // The gate.
        checks += 1;
        let (rows, failures) = run(&ins, rounds, Fault::None, true);
        let table = tsv(&rows);
        eprint!("heap_flat: gate run, {rounds} rounds of {} kinds; bytes relative to the baseline\n{table}", KINDS.len());
        if let Some(p) = std::env::var_os("HEAP_FLAT_TSV") {
            std::fs::write(p, &table).unwrap();
        }
        let max_peak = rows.iter().map(|r| r.peak).max().unwrap_or(0);
        let max_settle = rows.iter().map(|r| r.settle_ms).max().unwrap_or(0);
        if failures.is_empty() {
            println!(
                "heap_flat: gate PASS: {} conversions, live heap = baseline after every one ({} of {}), threads back every time (longest settle {max_settle} ms), largest peak {max_peak} B",
                rows.len(),
                rows.iter().filter(|r| r.live == 0).count(),
                rows.len()
            );
        } else {
            failed += 1;
            bad.extend(failures.iter().map(|f| format!("gate: {f}")));
        }
        std::fs::remove_dir_all(&ins.dir).unwrap();

        let secs = t0.elapsed().as_secs_f64();
        if bad.is_empty() {
            // The line test counters read (as libtest prints it): the three controls and the gate.
            println!("test result: ok. {checks} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in {secs:.2}s");
        } else {
            for b in &bad {
                println!("heap_flat: FAIL: {b}");
            }
            println!("test result: FAILED. {} passed; {failed} failed; 0 ignored; 0 measured; 0 filtered out; finished in {secs:.2}s", checks - failed);
            std::process::exit(1);
        }
    }
}
