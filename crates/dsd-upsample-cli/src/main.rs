// SPDX-License-Identifier: MIT OR Apache-2.0
//! `dsd-upsample IN OUT --rate 64|128|256|pcm88|pcm176|pcm352 [options]`
//! `dsd-upsample IN... --out-dir DIR --rate ... [--format dsf|dff|wav] [--jobs N] [options]`
//! `dsd-upsample gen OUT [--rate 64|128|256 | --fs HZ] [--freq HZ] [--level DB] [--seconds S]`

mod args;

use args::{before_end, options, shown, split, usage, Args, Fail};
use dsd_upsample::dsd2pcm::wav::WavFormat;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{convert_file_to, Container, FileOutput, Options, Output};
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Instant;

const USAGE: &str = "usage:
  dsd-upsample IN OUT --rate 64|128|256 [--order 5..8] [--gain DB] [--cutoff 30|40|wide]
                      [--dither] [--limit FRACTION] [--single-thread]
                      [--format dsf|dff] [--tag KEY=VALUE]... [--no-overwrite]
  dsd-upsample IN OUT.wav --rate pcm88|pcm176|pcm352 [--cutoff 30|40|wide] [--gain DB]
  dsd-upsample IN... --out-dir DIR --rate ... [--format dsf|dff|wav] [--jobs N] [options]
  dsd-upsample gen OUT.dsf|OUT.dff [--rate 64|128|256] [--freq HZ] [--level DB] [--seconds S] [--channels N]
  dsd-upsample gen OUT.wav --fs HZ [--freq HZ] [--level DB] [--seconds S] [--channels N] [--bits 16|24|32|f32|f64]

IN is DSF, DFF (DSD64..DSD256), WAV or FLAC (44.1, 88.2, 176.4, 352.8 kHz, or 48, 96, 192, 384 kHz, which are
resampled by 147/160 first); --rate 64 needs PCM input. DSD output format follows the OUT extension (.dsf or .dff). Defaults: --order 6, --limit 0.51, --gain -6 (0 for PCM output). --rate 128 accepts --order 5 to 7.
The default gain leaves 6 dB of headroom: PCM true peaks up to +6 dBTP and DSD up to 100 % modulation are not limited. A higher --gain is louder; samples above the limit are then limited and counted.
The modulator's noise-shaping zeros lie over 0-20 kHz (1 kHz SINAD at -3 dB SACD, 64-bit float input: 118.2, 157.1 and
195.8 dB at DSD64, DSD128 and DSD256; 188.0 dB at DSD256 from a 32-bit source).
DSD64 input is decimated with a 140 dB Kaiser filter; --cutoff selects dsd2pcm's
filters instead (the PCM-output filters; PCM output default 40). gen levels are dB re 0 dB SACD for DSD (at most +3.1, the Super Audio CD peak level; above 0 a second-order modulator makes the tone, with more noise in the audio band) and
dBFS for WAV. With --out-dir, every IN is converted to DIR/<name>.<format> (default dsf,
wav for PCM rates), --jobs files at a time (default: CPU threads / 4); --suffix TEXT goes
between the name and the extension; --json prints one JSON object per line on stdout: a
progress event (input, percent) every 5 % and a done event per file (input, output, ok,
error; for a converted file also samples, limited, clipped, resets, clamped and warning).
--format sets the
container regardless of OUT's name. --tag (repeatable) writes an ID3v2 tag into DSF output,
replacing the source's: title, artist, album, albumartist, track, disc, date, genre,
composer, comment, or any other key (stored as a user text frame). --no-overwrite fails
instead of replacing an existing OUT. -- ends the options: every later argument is a file
name, even one starting with -. --help (-h) prints this text, --version (-V) the version.

Exit status: 0 success, 1 a conversion or I/O error (in batch mode: any file failed),
2 a usage error (the command line is invalid; nothing was converted), 130 interrupted
(Ctrl-C before every conversion finished; unfinished outputs are removed).";

/// A conversion error: [`Fail::Interrupted`] if Ctrl-C cancelled it.
fn run_error(e: dsd_upsample::Error) -> Fail {
    if dsd_upsample::is_cancelled(&e) {
        Fail::Interrupted
    } else {
        Fail::Run(e.to_string())
    }
}

/// Set by Ctrl-C (or SIGTERM/SIGHUP): conversions stop through their progress callbacks,
/// which removes their temporary files.
static CANCEL: AtomicBool = AtomicBool::new(false);

/// Set when every conversion has ended: a Ctrl-C after that changes nothing.
static FINISHED: AtomicBool = AtomicBool::new(false);

fn cancelled() -> bool {
    CANCEL.load(Ordering::Relaxed)
}

/// The first Ctrl-C cancels cleanly; a second one quits at once (a temporary
/// `NAME.partN.EXT` file may then stay behind).
fn install_cancel_handler() {
    static SIGNALS: AtomicUsize = AtomicUsize::new(0);
    // Without a handler (it can fail only if another one is installed), Ctrl-C keeps its
    // default effect.
    let _ = ctrlc::set_handler(|| {
        if FINISHED.load(Ordering::SeqCst) {
            return;
        }
        if SIGNALS.fetch_add(1, Ordering::SeqCst) > 0 {
            std::process::exit(130);
        }
        CANCEL.store(true, Ordering::SeqCst);
        eprintln!("dsd-upsample: stopping; press Ctrl-C again to quit at once");
    });
}

/// The report of one conversion, as printed lines.
fn report(rep: &dsd_upsample::Report, secs: f64) -> String {
    let mut s = format!(
        "{} Hz -> {} Hz: {:.2} s of audio in {:.2} s, {:.2}x real time",
        rep.in_rate,
        rep.out_rate,
        rep.seconds,
        secs,
        rep.seconds / secs.max(1e-9)
    );
    for (c, k) in rep.counters.iter().enumerate() {
        s += &format!(
            "\n  channel {c}: limited {} clipped {} resets {}",
            k.limited, k.clipped, k.resets
        );
    }
    if let Some(l) = limited_line(limited_total(rep), limited_of(rep)) {
        s += &format!("\n  {l}");
    }
    if !rep.pcm_clipped.is_empty() {
        s += &format!(
            "\n  samples clamped to 24 bits per channel: {:?}",
            rep.pcm_clipped
        );
    }
    s
}

/// Samples limited before the modulator, all channels together.
fn limited_total(rep: &dsd_upsample::Report) -> u64 {
    rep.counters.iter().map(|k| k.limited).sum()
}

/// Samples that went through the limiter, all channels together.
fn limited_of(rep: &dsd_upsample::Report) -> u64 {
    rep.out_samples * rep.counters.len() as u64
}

/// The summary line for limited samples: their count and share. `None` when nothing was
/// limited, so that every limited sample shows in the normal output, however few.
fn limited_line(limited: u64, of: u64) -> Option<String> {
    if limited == 0 {
        return None;
    }
    let pct = 100.0 * limited as f64 / of.max(1) as f64;
    // small shares keep two significant digits
    let pct = if pct >= 0.01 {
        format!("{pct:.2}")
    } else {
        format!("{pct:.1e}")
    };
    Some(format!(
        "limited: {limited} of {of} samples ({pct} %) were above the input limit; a lower --gain avoids it"
    ))
}

/// Share of a channel's samples limited before the modulator at or above which the report
/// warns.
const LIMITED_WARN_SHARE: f64 = 0.01;
/// Input mean (fraction of full scale) at or above which the warning names a DC offset as
/// the likely cause.
const DC_WARN: f64 = 0.1;

/// A warning when a large share of the samples was limited, with the likely cause.
fn limit_warning(rep: &dsd_upsample::Report) -> Option<String> {
    let n = rep.out_samples.max(1) as f64;
    let shares: Vec<f64> = rep.counters.iter().map(|c| c.limited as f64 / n).collect();
    let worst = shares.iter().copied().fold(0.0, f64::max);
    if worst < LIMITED_WARN_SHARE {
        return None;
    }
    let per: Vec<String> = shares
        .iter()
        .enumerate()
        .map(|(c, v)| format!("channel {c} {:.1} %", 100.0 * v))
        .collect();
    let mut w = format!(
        "{:.1} % of the samples were limited before the modulator ({})",
        100.0 * worst,
        per.join(", ")
    );
    let dc = rep
        .input_mean
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.abs().total_cmp(&b.1.abs()))
        .filter(|(_, m)| m.abs() >= DC_WARN);
    match dc {
        Some((c, m)) => {
            w += &format!(
                "; the source has a DC offset (mean {m:+.2} of full scale on channel {c}), \
                 which uses up the modulator's headroom; check the source, or lower --gain"
            )
        }
        None => w += "; the source is loud for the modulator's input limit; lower --gain",
    }
    Some(w)
}

/// The fields a done event adds for a converted file.
fn done_fields(rep: &dsd_upsample::Report) -> Vec<(&'static str, J<'static>)> {
    let mut total = dsd_upsample::modulator::Counters::default();
    for c in &rep.counters {
        total.add(c);
    }
    vec![
        ("samples", J::N(rep.out_samples)),
        ("limited", J::N(total.limited)),
        ("clipped", J::N(total.clipped)),
        ("resets", J::N(total.resets)),
        ("clamped", J::N(rep.pcm_clipped.iter().sum())),
    ]
}

fn run_convert(a: &Args) -> Result<(), Fail> {
    let o = options(a)?;
    let format = match a.get("format") {
        None => None,
        Some("dsf") => Some(Container::Dsf),
        Some("dff") => Some(Container::Dff),
        Some("wav") => Some(Container::Wav),
        Some(f) => return Err(usage(format!("--format {f}: dsf, dff or wav"))),
    };
    if a.get_os("out-dir").is_some() {
        return run_batch(a, &o);
    }
    if a.get("jobs").is_some() || a.get_os("suffix").is_some() || a.flag("--json") {
        return Err(usage("--jobs, --suffix and --json need --out-dir"));
    }
    let [inp, out] = &a.pos[..] else {
        return Err(usage("need IN and OUT"));
    };
    let container = match format {
        Some(c) => c,
        None => Container::from_path(out).map_err(|e| usage(e.to_string()))?,
    };
    match (container, o.output) {
        (Container::Wav, Output::Dsd { .. }) => {
            return Err(usage("DSD output needs a .dsf or .dff file (or --format)"))
        }
        (Container::Dsf | Container::Dff, Output::Pcm(_)) => {
            return Err(usage("PCM output needs a .wav file (or --format wav)"))
        }
        _ => {}
    }
    if !a.tags.is_empty() && container != Container::Dsf {
        return Err(usage("--tag is for DSF output only"));
    }
    if same_file(inp, out) {
        return Err(usage(format!("output {} is the input file", shown(out))));
    }
    let file = FileOutput {
        container: format,
        tags: a.tags.clone(),
        no_overwrite: a.flag("--no-overwrite"),
    };
    let t = Instant::now();
    let mut tick = |_: u64, _: u64| !cancelled();
    let rep = convert_file_to(inp, out, &o, &file, Some(&mut tick)).map_err(run_error)?;
    eprintln!("{}", report(&rep, t.elapsed().as_secs_f64()));
    if let Some(w) = limit_warning(&rep) {
        eprintln!("dsd-upsample: warning: {w}");
    }
    Ok(())
}

/// A JSON value for [`emit_json`].
enum J<'a> {
    S(&'a str),
    T(&'a str),
    P(&'a Path),
    N(u64),
    B(bool),
}

/// A JSON string literal. Paths that aren't valid UTF-8 are shown lossily.
fn json_str(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    o.push('"');
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            c if (c as u32) < 0x20 || c == '\u{2028}' || c == '\u{2029}' => {
                o.push_str(&format!("\\u{:04x}", c as u32))
            }
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

/// Prints one JSON object as a line on stdout (one write, so lines from several workers
/// don't interleave).
fn emit_json(fields: &[(&str, J<'_>)]) {
    use std::io::Write;
    let body: Vec<String> = fields
        .iter()
        .map(|(k, v)| {
            let v = match v {
                J::S(s) | J::T(s) => json_str(s),
                J::P(p) => json_str(&p.to_string_lossy()),
                J::N(n) => n.to_string(),
                J::B(b) => b.to_string(),
            };
            format!("{}:{v}", json_str(k))
        })
        .collect();
    let line = format!("{{{}}}\n", body.join(","));
    let _ = std::io::stdout().lock().write_all(line.as_bytes());
}

/// Whether `a` and `b` name the same existing file: the same path, a symlink or a hard
/// link (device and inode on Unix, volume serial number and file index on Windows).
fn same_file(a: &Path, b: &Path) -> bool {
    same_file::is_same_file(a, b).unwrap_or(false)
}

/// Converts every input into `--out-dir`, `--jobs` files at a time.
fn run_batch(a: &Args, o: &Options) -> Result<(), Fail> {
    if !a.tags.is_empty() {
        return Err(usage("--tag is for single files, not --out-dir"));
    }
    let dir = PathBuf::from(a.get_os("out-dir").unwrap_or_default());
    if !dir.is_dir() {
        return Err(usage(format!("--out-dir {}: not a directory", shown(&dir))));
    }
    if a.pos.is_empty() {
        return Err(usage("need at least one IN"));
    }
    let ext = match (a.get("format"), o.output) {
        (None, Output::Dsd { .. }) => "dsf",
        (None, Output::Pcm(_)) => "wav",
        (Some(f @ ("dsf" | "dff")), Output::Dsd { .. }) => f,
        (Some("wav"), Output::Pcm(_)) => "wav",
        (Some(f), _) => return Err(usage(format!("--format {f} does not fit --rate"))),
    };
    let mut jobs: Vec<(PathBuf, PathBuf)> = Vec::new();
    for inp in &a.pos {
        let stem = inp
            .file_stem()
            .ok_or_else(|| usage(format!("{}: no file name", shown(inp))))?;
        let suffix = a.get_os("suffix").unwrap_or_default();
        if suffix.to_string_lossy().contains(['/', '\\']) {
            return Err(usage("--suffix may not contain a path separator"));
        }
        let mut name = stem.to_os_string();
        name.push(suffix);
        name.push(".");
        name.push(ext);
        let out = dir.join(name);
        // Case-insensitive: on macOS and Windows, A.dsf and a.dsf are one file.
        let key = out.to_string_lossy().to_lowercase();
        if jobs
            .iter()
            .any(|(_, o)| o.to_string_lossy().to_lowercase() == key)
        {
            return Err(usage(format!(
                "two inputs would both write {}; convert them separately",
                shown(&out)
            )));
        }
        jobs.push((inp.clone(), out));
    }
    // No job may write a file that is any job's input.
    for (_, out) in &jobs {
        if let Some(inp) = a.pos.iter().find(|i| same_file(i, out)) {
            return Err(usage(format!(
                "{} would overwrite the input {}",
                shown(out),
                shown(inp)
            )));
        }
    }
    let json = a.flag("--json");
    let cpus = std::thread::available_parallelism().map_or(1, |n| n.get());
    let workers = a.num("jobs", (cpus / 4).max(1))?.clamp(1, jobs.len());
    let next = std::sync::atomic::AtomicUsize::new(0);
    let failed = std::sync::atomic::AtomicUsize::new(0);
    let stopped = std::sync::atomic::AtomicUsize::new(0);
    let converted = std::sync::atomic::AtomicUsize::new(0);
    // limited samples, samples, and files with limited samples
    let limited = std::sync::Mutex::new((0u64, 0u64, 0usize));
    let audio = std::sync::Mutex::new(0.0f64);
    let t = Instant::now();
    std::thread::scope(|s| {
        let mut handles = Vec::with_capacity(workers);
        for _ in 0..workers {
            handles.push(s.spawn(|| loop {
                if cancelled() {
                    break;
                }
                let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                let Some((inp, out)) = jobs.get(i) else { break };
                let t = Instant::now();
                let file = FileOutput {
                    no_overwrite: a.flag("--no-overwrite"),
                    ..FileOutput::default()
                };
                let mut last = 0u64;
                let mut tick = |done: u64, total: u64| {
                    let pct = (done * 100).checked_div(total).unwrap_or(100);
                    if json && pct >= last + 5 {
                        last = pct - pct % 5;
                        emit_json(&[
                            ("event", J::S("progress")),
                            ("input", J::P(inp)),
                            ("percent", J::N(last)),
                        ]);
                    }
                    !cancelled()
                };
                match convert_file_to(inp, out, o, &file, Some(&mut tick)) {
                    Ok(rep) => {
                        converted.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        *audio.lock().expect("lock") += rep.seconds;
                        {
                            let mut l = limited.lock().expect("lock");
                            l.0 += limited_total(&rep);
                            l.1 += limited_of(&rep);
                            l.2 += usize::from(limited_total(&rep) > 0);
                        }
                        let warning = limit_warning(&rep);
                        if json {
                            let mut f = vec![
                                ("event", J::S("done")),
                                ("input", J::P(inp)),
                                ("output", J::P(out)),
                                ("ok", J::B(true)),
                            ];
                            f.extend(done_fields(&rep));
                            if let Some(w) = &warning {
                                f.push(("warning", J::T(w)));
                            }
                            emit_json(&f);
                        }
                        eprintln!(
                            "{} -> {}: {}",
                            shown(inp),
                            shown(out),
                            report(&rep, t.elapsed().as_secs_f64())
                        );
                        if let Some(w) = &warning {
                            eprintln!("{}: warning: {w}", shown(inp));
                        }
                    }
                    Err(e) => {
                        if dsd_upsample::is_cancelled(&e) {
                            stopped.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        } else {
                            failed.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        }
                        if json {
                            emit_json(&[
                                ("event", J::S("done")),
                                ("input", J::P(inp)),
                                ("output", J::P(out)),
                                ("ok", J::B(false)),
                                ("error", J::T(&e.to_string())),
                            ]);
                        }
                        eprintln!("{}: {e}", shown(inp));
                    }
                }
            }));
        }
        // The scope waits for each worker's closure; joining also waits for the threads
        // themselves, so none is still exiting when the summary is printed.
        for h in handles {
            h.join().expect("batch worker panicked");
        }
    });
    let secs = t.elapsed().as_secs_f64();
    let audio = *audio.lock().expect("lock");
    let failed = failed.into_inner();
    let converted = converted.into_inner();
    let stopped = stopped.into_inner();
    eprintln!(
        "{} of {} files converted, {:.1} s of audio in {:.2} s, {:.2}x real time ({workers} at a time)",
        converted,
        jobs.len(),
        audio,
        secs,
        audio / secs.max(1e-9)
    );
    let (lim, of, files) = *limited.lock().expect("lock");
    if let Some(l) = limited_line(lim, of) {
        eprintln!("{l} ({files} of {converted} converted files)");
    }
    // Interrupted only if Ctrl-C stopped a conversion or kept one from starting; a Ctrl-C
    // after every file ended changes nothing.
    if stopped > 0 || converted + failed < jobs.len() {
        return Err(Fail::Interrupted);
    }
    if failed > 0 {
        return Err(Fail::Run(format!("{failed} file(s) failed")));
    }
    Ok(())
}

fn run_gen(a: &Args) -> Result<(), Fail> {
    let [out] = &a.pos[..] else {
        return Err(usage("gen needs OUT"));
    };
    let s = Sine {
        freq: a.num("freq", 1000u32)?,
        level_db: a.num("level", -6.0f64)?,
        seconds: a.num("seconds", 5.0f64)?,
        channels: a.num("channels", 2u16)?,
    };
    let is_wav = Path::new(out)
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("wav"));
    let r = if is_wav {
        if a.get("rate").is_some() {
            return Err(usage(
                "--rate is for DSF and DFF test tones; use --fs for WAV",
            ));
        }
        let fmt = match a.get("bits").unwrap_or("24") {
            "16" => WavFormat::I16,
            "24" => WavFormat::I24,
            "32" => WavFormat::I32,
            "f32" => WavFormat::F32,
            "f64" => WavFormat::F64,
            v => return Err(usage(format!("bits {v}: 16, 24, 32, f32 or f64"))),
        };
        testsignal::write_wav(out, a.num("fs", 44_100u32)?, fmt, &s)
    } else {
        if a.get("fs").is_some() || a.get("bits").is_some() {
            return Err(usage("--fs and --bits are for WAV test tones (OUT.wav)"));
        }
        testsignal::write_dsd(out, a.num("rate", 64u32)?, &s)
    };
    r.map_err(|e| Fail::Run(e.to_string()))
}

/// Runs the command line (without the program name); `--help` and `--version` are handled
/// by the caller.
fn run(args: &[OsString]) -> Result<(), Fail> {
    if args.first().is_some_and(|a| a == "gen") {
        split(&args[1..], true).and_then(|a| run_gen(&a))
    } else {
        split(args, false).and_then(|a| run_convert(&a))
    }
}

fn main() -> ExitCode {
    // OsString: a path that isn't valid UTF-8 is a valid path.
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    // --version and --help win over everything else before `--`, as packagers' checks
    // expect.
    if before_end(&args).any(|a| a == "--version" || a == "-V") {
        println!("dsd-upsample {}", env!("CARGO_PKG_VERSION"));
        return ExitCode::SUCCESS;
    }
    if before_end(&args).any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return ExitCode::SUCCESS;
    }
    if args.first().is_none_or(|a| a != "gen") {
        install_cancel_handler();
    }
    let res = run(&args);
    FINISHED.store(true, Ordering::SeqCst);
    finish(res)
}

/// Reports the outcome on stderr and gives the exit status. Ctrl-C counts only when it
/// stopped a conversion ([`Fail::Interrupted`]), not when it came after the work ended.
fn finish(res: Result<(), Fail>) -> ExitCode {
    let Err(f) = res else {
        return ExitCode::SUCCESS;
    };
    match &f {
        Fail::Usage(e) => eprintln!("dsd-upsample: {e}\n\n{USAGE}"),
        Fail::Run(e) => eprintln!("dsd-upsample: {e}"),
        Fail::Interrupted => {
            eprintln!("dsd-upsample: interrupted; unfinished outputs were removed")
        }
    }
    ExitCode::from(f.code())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn os(args: &[&str]) -> Vec<OsString> {
        args.iter().map(OsString::from).collect()
    }

    /// Ctrl-C decides the exit status only when it stopped a conversion. One test, because
    /// it sets the process-wide cancel flag.
    #[test]
    fn ctrl_c_counts_only_while_converting() {
        let d = std::env::temp_dir().join(format!("dsdup-cli-unit-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        let inp = d.join("in.dsf");
        let s = Sine {
            freq: 1000,
            level_db: -6.0,
            seconds: 0.05,
            channels: 1,
        };
        testsignal::write_dsd(&inp, 64, &s).unwrap();
        let (i, o) = (inp.to_str().unwrap(), d.join("out.dsf"));
        let o = o.to_str().unwrap();
        let outdir = d.join("batch");
        std::fs::create_dir(&outdir).unwrap();
        let single = os(&[i, o, "--rate", "128"]);
        let batch = os(&[i, "--out-dir", outdir.to_str().unwrap(), "--rate", "128"]);
        for args in [&single, &batch] {
            // every conversion ended before the Ctrl-C: success
            CANCEL.store(false, Ordering::SeqCst);
            let res = run(args);
            CANCEL.store(true, Ordering::SeqCst);
            assert!(res.is_ok(), "{args:?}: {res:?}");
            assert_eq!(finish(res), ExitCode::SUCCESS);
            // a Ctrl-C before or during the conversion: interrupted (130)
            let res = run(args);
            assert!(matches!(res, Err(Fail::Interrupted)), "{args:?}: {res:?}");
            assert_eq!(finish(res), ExitCode::from(130));
        }
        CANCEL.store(false, Ordering::SeqCst);
        std::fs::remove_dir_all(&d).unwrap();
    }

    /// Exit statuses of the failure kinds.
    #[test]
    fn exit_codes() {
        assert_eq!(Fail::Usage(String::new()).code(), 2);
        assert_eq!(Fail::Run(String::new()).code(), 1);
        assert_eq!(Fail::Interrupted.code(), 130);
    }
}
