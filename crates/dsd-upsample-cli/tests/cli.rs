// SPDX-License-Identifier: MIT OR Apache-2.0
//! The command line tool end to end: file names that are not UTF-8, and Ctrl-C.

use std::path::{Path, PathBuf};
use std::process::Command;

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_dsd-upsample"))
}

fn scratch(name: &str) -> PathBuf {
    let d =
        Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("cli-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn names(dir: &Path) -> Vec<Vec<u8>> {
    let mut v: Vec<Vec<u8>> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().into_encoded_bytes())
        .collect();
    v.sort();
    v
}

/// `--version` and `-V` print the version on stdout and succeed, whatever else is given.
#[test]
fn version() {
    let want = format!("dsd-upsample {}\n", env!("CARGO_PKG_VERSION"));
    for args in [
        &["--version"][..],
        &["-V"],
        &["in.dsf", "--rate", "--version"],
        &["gen", "-V"],
    ] {
        let o = bin().args(args).output().unwrap();
        assert!(o.status.success(), "{args:?}");
        assert_eq!(String::from_utf8(o.stdout).unwrap(), want, "{args:?}");
    }
}

/// Latin-1 file names (bytes that are not UTF-8) work in single and batch mode, as inputs,
/// outputs, output directory and suffix (Linux file systems take any bytes).
#[cfg(target_os = "linux")]
#[test]
fn latin1_file_names() {
    use std::ffi::OsStr;
    use std::os::unix::ffi::OsStrExt;
    let d = scratch("latin1");
    let inp = d.join(OsStr::from_bytes(b"caf\xe9.dsf"));
    let st = bin()
        .arg("gen")
        .arg(&inp)
        .args(["--rate", "64", "--seconds", "0.05"])
        .status()
        .unwrap();
    assert!(st.success());
    let out = d.join(OsStr::from_bytes(b"caf\xe9 \xbb 128.dsf"));
    let o = bin()
        .arg(&inp)
        .arg(&out)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(out.is_file());
    let dir = d.join(OsStr::from_bytes(b"sortie \xe0"));
    std::fs::create_dir(&dir).unwrap();
    let o = bin()
        .arg(&inp)
        .arg("--out-dir")
        .arg(&dir)
        .arg("--suffix")
        .arg(OsStr::from_bytes(b"-\xe9"))
        .args(["--rate", "256", "--json"])
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(names(&dir), [b"caf\xe9-\xe9.dsf".to_vec()]);
    // the report shows the name lossily, without failing
    assert!(String::from_utf8_lossy(&o.stderr).contains("caf\u{fffd}"));
    // an option value that must be text is an error, not a panic
    let o = bin()
        .arg(&inp)
        .arg(&out)
        .arg("--rate")
        .arg(OsStr::from_bytes(b"\xff"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("not valid UTF-8"));
    std::fs::remove_dir_all(&d).unwrap();
}

/// Ctrl-C (SIGINT) part-way: exit status 130, no output and no temporary file left, and an
/// existing output untouched. Deterministic: the signal is sent only after the first
/// `--json` progress event (5 % of an 8 s input converted to DSD256 on one thread), so the
/// conversion is under way and far from done; no timing or polling of the output file.
#[cfg(unix)]
#[test]
fn ctrl_c_removes_the_partial_output() {
    use std::io::BufRead;
    let d = scratch("sigint");
    let inp = d.join("in.dsf");
    let st = bin()
        .arg("gen")
        .arg(&inp)
        .args(["--rate", "64", "--seconds", "8"])
        .status()
        .unwrap();
    assert!(st.success());
    let od = d.join("out");
    std::fs::create_dir(&od).unwrap();
    let out = od.join("in.dsf");
    for existing in [false, true] {
        if existing {
            std::fs::write(&out, b"keep me").unwrap();
        }
        let mut child = bin()
            .arg(&inp)
            .arg("--out-dir")
            .arg(&od)
            .args(["--rate", "256", "--single-thread", "--jobs", "1", "--json"])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        // Block until the first progress event: the conversion has started and wrote 5 %.
        let mut lines = std::io::BufReader::new(child.stdout.take().unwrap()).lines();
        let first = lines.next().expect("no output before exit").unwrap();
        assert!(
            first.contains(r#""event":"progress""#),
            "first event: {first}"
        );
        let kill = Command::new("kill")
            .args(["-INT", &child.id().to_string()])
            .status()
            .unwrap();
        assert!(kill.success());
        let rest: Vec<String> = lines.map(|l| l.unwrap()).collect();
        let o = child.wait_with_output().unwrap();
        assert_eq!(
            o.status.code(),
            Some(130),
            "events after the signal: {rest:?}; stderr: {}",
            String::from_utf8_lossy(&o.stderr)
        );
        let want: Vec<Vec<u8>> = if existing {
            assert_eq!(std::fs::read(&out).unwrap(), b"keep me");
            vec![b"in.dsf".to_vec()]
        } else {
            vec![]
        };
        assert_eq!(names(&od), want);
        assert_eq!(names(&d), vec![b"in.dsf".to_vec(), b"out".to_vec()]);
    }
    std::fs::remove_dir_all(&d).unwrap();
}

/// `--help` and `-h` print the usage (with the exit statuses) on stdout and succeed,
/// whatever else is given before `--`.
#[test]
fn help() {
    for args in [
        &["--help"][..],
        &["-h"],
        &["in.dsf", "--rate", "999", "--help"],
        &["gen", "-h"],
    ] {
        let o = bin().args(args).output().unwrap();
        assert_eq!(o.status.code(), Some(0), "{args:?}");
        let out = String::from_utf8(o.stdout).unwrap();
        assert!(out.starts_with("usage:"), "{args:?}: {out}");
        assert!(out.contains("Exit status: 0 success, 1"), "{args:?}");
        assert!(o.stderr.is_empty(), "{args:?}");
    }
}

/// Exit statuses: 2 for a usage error (nothing converted), 1 for a conversion or I/O error.
#[test]
fn exit_statuses() {
    let d = scratch("exit");
    let inp = d.join("in.dsf");
    assert!(bin()
        .arg("gen")
        .arg(&inp)
        .args(["--seconds", "0.05"])
        .status()
        .unwrap()
        .success());
    let out = d.join("out.dsf");
    let usage: &[&[&str]] = &[
        &["--rate", "999"],                     // bad rate
        &["--rate", "128", "--order", "9"],     // the library's range check
        &["--rate", "128", "--order", "8"],     // order 8 is not accepted at DSD128
        &["--rate", "128", "--gain", "99"],     // the library's range check
        &["--rate", "128", "--limit", "2"],     // the library's range check
        &["--rate", "128", "--bogus", "1"],     // unknown option
        &["--rate", "128", "--band", "wide"],   // not an option of this release
        &["--rate", "128", "--band", "audio"],  // not an option of this release
        &["--rate", "128", "--format", "flac"], // bad format
        &["--rate", "128", "--jobs", "2"],      // batch option without --out-dir
        &["--rate", "pcm88"],                   // PCM output to .dsf
    ];
    for extra in usage {
        let o = bin().arg(&inp).arg(&out).args(*extra).output().unwrap();
        assert_eq!(o.status.code(), Some(2), "{extra:?}");
        assert!(
            String::from_utf8_lossy(&o.stderr).contains("usage:"),
            "{extra:?}"
        );
        assert!(!out.exists(), "{extra:?}");
    }
    // IN without OUT
    let o = bin().arg(&inp).args(["--rate", "128"]).output().unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("need IN and OUT"));
    // the output is the input
    let o = bin()
        .arg(&inp)
        .arg(&inp)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    // conversion and I/O errors
    let missing = d.join("missing.dsf");
    let o = bin()
        .arg(&missing)
        .arg(&out)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert!(!String::from_utf8_lossy(&o.stderr).contains("usage:"));
    std::fs::write(d.join("junk.dsf"), b"not a DSF file").unwrap();
    let o = bin()
        .arg(d.join("junk.dsf"))
        .arg(&out)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1));
    // batch: any file failing is 1; the good one is still converted
    let dir = d.join("batch");
    std::fs::create_dir(&dir).unwrap();
    let o = bin()
        .arg(&inp)
        .arg(&missing)
        .arg("--out-dir")
        .arg(&dir)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert_eq!(names(&dir), [b"in.dsf".to_vec()]);
    // success
    let o = bin()
        .arg(&inp)
        .arg(&out)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(0));
    std::fs::remove_dir_all(&d).unwrap();
}

/// `--` ends the options: file names starting with `-` (even `--`) work after it, and
/// `--help` or `--version` after it are file names.
#[test]
fn double_dash_ends_options() {
    let d = scratch("dashdash");
    let st = bin()
        .current_dir(&d)
        .args(["gen", "--seconds", "0.05", "--", "-in.dsf"])
        .status()
        .unwrap();
    assert!(st.success());
    assert!(d.join("-in.dsf").is_file());
    let o = bin()
        .current_dir(&d)
        .args(["--rate", "128", "--", "-in.dsf", "--out.dsf"])
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(d.join("--out.dsf").is_file());
    // without `--`, "--out.dsf" is an (unknown) option
    let o = bin()
        .current_dir(&d)
        .args(["-in.dsf", "--out.dsf", "--rate", "128"])
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("unknown option --out.dsf"));
    // --help after `--` is a file name, not a request for help
    let o = bin()
        .current_dir(&d)
        .args(["--rate", "128", "--", "-in.dsf", "--help"])
        .output()
        .unwrap();
    assert_eq!(
        o.status.code(),
        Some(2),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert!(o.stdout.is_empty());
    assert!(String::from_utf8_lossy(&o.stderr).contains(".dsf, .dff or .wav"));
    std::fs::remove_dir_all(&d).unwrap();
}

/// Options of the other mode are refused with a message naming the mode, not ignored.
#[test]
fn options_of_the_other_mode_are_refused() {
    let d = scratch("modes");
    let inp = d.join("in.dsf");
    assert!(bin()
        .arg("gen")
        .arg(&inp)
        .args(["--seconds", "0.05"])
        .status()
        .unwrap()
        .success());
    let out = d.join("out.dsf");
    for (args, msg) in [
        (&["--freq", "440"][..], "--freq is a gen option"),
        (&["--seconds", "1"], "--seconds is a gen option"),
        (&["--fs", "44100"], "--fs is a gen option"),
        (&["--bits", "16"], "--bits is a gen option"),
    ] {
        let o = bin()
            .arg(&inp)
            .arg(&out)
            .args(["--rate", "128"])
            .args(args)
            .output()
            .unwrap();
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        assert!(String::from_utf8_lossy(&o.stderr).contains(msg), "{args:?}");
        assert!(!out.exists());
    }
    let tone = d.join("t.dsf");
    let wav = d.join("t.wav");
    for (file, args, msg) in [
        (
            &tone,
            &["--order", "6"][..],
            "--order is a conversion option",
        ),
        (&tone, &["--dither"], "--dither is a conversion option"),
        (
            &tone,
            &["--out-dir", "x"],
            "--out-dir is a conversion option",
        ),
        (&tone, &["--tag", "title=x"], "--tag is a conversion option"),
        (&tone, &["--fs", "44100"], "--fs and --bits are for WAV"),
        (&tone, &["--bits", "16"], "--fs and --bits are for WAV"),
        (&wav, &["--rate", "128"], "--rate is for DSF and DFF"),
        (&tone, &["--nope", "1"], "unknown option --nope"),
    ] {
        let o = bin().arg("gen").arg(file).args(args).output().unwrap();
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        assert!(String::from_utf8_lossy(&o.stderr).contains(msg), "{args:?}");
        assert!(!file.exists(), "{args:?}");
    }
    std::fs::remove_dir_all(&d).unwrap();
}

/// Generates a DSD64 test tone with `gen`.
fn gen_tone(path: &Path, level: &str, seconds: &str) {
    assert!(bin()
        .arg("gen")
        .arg(path)
        .args(["--rate", "64", "--level", level, "--seconds", seconds])
        .status()
        .unwrap()
        .success());
}

/// One JSON line's value for `key`, as written: a number, `true`/`false` or a quoted string.
fn json_value<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let at = line.find(&format!("\"{key}\":"))? + key.len() + 3;
    let rest = &line[at..];
    let end = match rest.strip_prefix('"') {
        Some(r) => r.find('"')? + 2,
        None => rest.find([',', '}'])?,
    };
    Some(&rest[..end])
}

/// A DSF whose header says 0 samples while its data chunk holds audio is refused with exit
/// status 1, a message with the header's count and the data size, and no output (it used to
/// convert to an empty file without a word).
#[test]
fn zero_sample_header_is_refused() {
    let d = scratch("zero");
    let inp = d.join("in.dsf");
    gen_tone(&inp, "-6", "0.1");
    let mut b = std::fs::read(&inp).unwrap();
    b[64..72].copy_from_slice(&0u64.to_le_bytes());
    let data = u64::from_le_bytes(b[84..92].try_into().unwrap()) - 12;
    std::fs::write(&inp, &b).unwrap();
    let out = d.join("out.dsf");
    let o = bin()
        .arg(&inp)
        .arg(&out)
        .args(["--rate", "128"])
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&o.stderr);
    assert_eq!(o.status.code(), Some(1), "{err}");
    assert!(
        err.contains("declares 0 samples") && err.contains(&format!("holds {data} bytes")),
        "{err}"
    );
    assert_eq!(names(&d), [b"in.dsf".to_vec()]);
    std::fs::remove_dir_all(&d).unwrap();
}

/// `--json` done events carry the output length and the limiter, clip, reset and clamp
/// totals, and a warning when a large share of the samples was limited.
#[test]
fn json_done_events_carry_the_counters() {
    let d = scratch("json");
    let (quiet, loud) = (d.join("quiet.dsf"), d.join("loud.dsf"));
    gen_tone(&quiet, "-20", "0.1");
    gen_tone(&loud, "0", "0.1");
    let dir = d.join("out");
    std::fs::create_dir(&dir).unwrap();
    // +6 dB: the 0 dB SACD tone reaches twice the 0.5 limit at its peaks, the -20 dB one
    // stays far below it.
    let o = bin()
        .arg(&quiet)
        .arg(&loud)
        .args([
            "--rate",
            "128",
            "--gain",
            "6",
            "--json",
            "--jobs",
            "1",
            "--out-dir",
        ])
        .arg(&dir)
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let stdout = String::from_utf8(o.stdout).unwrap();
    let done: Vec<&str> = stdout
        .lines()
        .filter(|l| l.contains("\"event\":\"done\""))
        .collect();
    assert_eq!(done.len(), 2, "{stdout}");
    for l in &done {
        // 0.1 s of DSD64 to DSD128.
        assert_eq!(json_value(l, "samples"), Some("564480"), "{l}");
        for k in ["limited", "clipped", "resets", "clamped"] {
            let v = json_value(l, k).unwrap_or_else(|| panic!("no {k} in {l}"));
            assert!(v.parse::<u64>().is_ok(), "{l}");
        }
    }
    let q = done.iter().find(|l| l.contains("quiet")).unwrap();
    assert_eq!(json_value(q, "limited"), Some("0"), "{q}");
    assert_eq!(json_value(q, "warning"), None, "{q}");
    let l = done.iter().find(|l| l.contains("loud")).unwrap();
    let limited: u64 = json_value(l, "limited").unwrap().parse().unwrap();
    assert!(limited > 564480 / 10, "{l}");
    let w = json_value(l, "warning").unwrap_or_else(|| panic!("no warning in {l}"));
    assert!(
        w.contains("of the samples were limited") && w.contains("lower --gain"),
        "{w}"
    );
    assert!(!w.contains("DC offset"), "{w}");
    std::fs::remove_dir_all(&d).unwrap();
}

/// A source with a large DC offset (the input mean) gets a warning naming it, on stderr in
/// single-file mode; the output is converted unchanged.
#[test]
fn dc_offset_warning() {
    let d = scratch("dc");
    // Channel 0: a first-order sigma-delta stream of -0.71 DC plus a 1 kHz tone.
    let n = 2_822_400 / 10 / 8 * 8;
    let mut ch = vec![vec![0u8; n / 8]; 2];
    let (mut acc, mut y) = (0.0f64, 1.0f64);
    for i in 0..n {
        let x = -0.71 + 0.2 * (2.0 * std::f64::consts::PI * 1000.0 * i as f64 / 2_822_400.0).sin();
        acc += x - y;
        y = if acc >= 0.0 { 1.0 } else { -1.0 };
        if y > 0.0 {
            ch[0][i / 8] |= 0x80 >> (i % 8);
        }
    }
    ch[1] = vec![0x69; n / 8];
    let inp = d.join("dc.dsf");
    {
        use dsd_upsample::dsd2pcm::io::DsdWrite;
        let f = std::io::BufWriter::new(std::fs::File::create(&inp).unwrap());
        let mut w = dsd_upsample::dsd2pcm::dsf::DsfWriter::new(f, 2, 2_822_400, None).unwrap();
        w.write_bytes(&ch).unwrap();
        w.finish(n as u64).unwrap();
    }
    let out = d.join("out.dsf");
    let o = bin()
        .arg(&inp)
        .arg(&out)
        // the louder setting: at the default gain (-6 dB) this offset is not limited
        .args(["--rate", "128", "--gain", "-3"])
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&o.stderr);
    assert!(o.status.success(), "{err}");
    assert!(out.is_file());
    assert!(
        err.contains("warning:")
            && err.contains("DC offset (mean -0.71 of full scale on channel 0)"),
        "{err}"
    );
    std::fs::remove_dir_all(&d).unwrap();
}

/// A mono 64-bit float WAV at 88.2 kHz: 0.2 s of a 1 kHz tone at -20 dBFS, with `burst`
/// samples at 3.0 (9.5 dB above full scale) in the middle if `burst` is not 0.
fn wav_with_burst(path: &Path, burst: usize) {
    use dsd_upsample::dsd2pcm::wav::{WavFormat, WavWriter};
    let fs = 88_200usize;
    let n = fs / 5;
    let mut raw = Vec::with_capacity(8 * n);
    for i in 0..n {
        let mut v = 0.1 * (2.0 * std::f64::consts::PI * 1000.0 * i as f64 / fs as f64).sin();
        if (n / 2..n / 2 + burst).contains(&i) {
            v = 3.0;
        }
        raw.extend_from_slice(&v.to_le_bytes());
    }
    let f = std::io::BufWriter::new(std::fs::File::create(path).unwrap());
    let mut w = WavWriter::new(f, WavFormat::F64, 1, fs as u32).unwrap();
    w.write_raw(&raw).unwrap();
    w.finish().unwrap();
}

/// Every limited sample shows in the normal output: a file with a few limited samples (far
/// below the 1 % of the warning) gets a summary line with their count and share, a file
/// with none gets no such line, and batch mode adds a total.
#[test]
fn limited_samples_are_reported_however_few() {
    let d = scratch("limited");
    let (clean, loud) = (d.join("clean.wav"), d.join("loud.wav"));
    wav_with_burst(&clean, 0);
    wav_with_burst(&loud, 40);
    let line = |err: &str| -> Option<(u64, u64)> {
        let l = err
            .lines()
            .find(|l| l.trim_start().starts_with("limited: "))?;
        let mut n = l.split_whitespace().filter_map(|w| w.parse::<u64>().ok());
        Some((n.next().unwrap(), n.next().unwrap()))
    };
    // single files
    for (inp, limited) in [(&clean, false), (&loud, true)] {
        let o = bin()
            .arg(inp)
            .arg(d.join("out.dsf"))
            .args(["--rate", "64"])
            .output()
            .unwrap();
        let err = String::from_utf8_lossy(&o.stderr);
        assert!(o.status.success(), "{err}");
        match line(&err) {
            None => assert!(!limited, "{err}"),
            Some((n, of)) => {
                // 0.2 s of DSD64, one channel; the burst is far below 1 % of it
                assert!(limited, "{err}");
                assert_eq!(of, 564_480, "{err}");
                assert!(n > 0 && n < of / 100, "{err}");
                assert!(err.contains(&format!("channel 0: limited {n} ")), "{err}");
                assert!(err.contains(" %) were above the input limit"), "{err}");
            }
        }
        assert!(!err.contains("warning"), "{err}");
    }
    // batch: the same line per file, and a total over the files
    let dir = d.join("out");
    std::fs::create_dir(&dir).unwrap();
    let o = bin()
        .arg(&clean)
        .arg(&loud)
        .args(["--rate", "64", "--jobs", "1", "--out-dir"])
        .arg(&dir)
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&o.stderr);
    assert!(o.status.success(), "{err}");
    let lines: Vec<&str> = err
        .lines()
        .filter(|l| l.trim_start().starts_with("limited: "))
        .collect();
    assert_eq!(lines.len(), 2, "{err}");
    assert!(lines[0].starts_with("  limited: "), "{err}");
    assert!(
        lines[1].starts_with("limited: ") && lines[1].ends_with("(1 of 2 converted files)"),
        "{err}"
    );
    assert!(lines[1].contains(" of 1128960 samples "), "{err}");
    // a clean batch has no such line
    let dir2 = d.join("out2");
    std::fs::create_dir(&dir2).unwrap();
    let o = bin()
        .arg(&clean)
        .args(["--rate", "64", "--out-dir"])
        .arg(&dir2)
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&o.stderr);
    assert!(o.status.success() && !err.contains("limited: "), "{err}");
    std::fs::remove_dir_all(&d).unwrap();
}
