// SPDX-License-Identifier: MIT OR Apache-2.0
//! File output: the conversion writes a temporary `NAME.partN.EXT` next to the output and
//! renames it on success, so a failed, cancelled or panicking conversion leaves no partial
//! file, an existing output survives a failed run, and `no_overwrite` never replaces a file
//! that appears during the conversion.

use dsd_upsample::dsd2pcm::dsf::DsfWriter;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{convert_file_to, is_cancelled, FileOutput, Options, Output};
use std::io::Cursor;
use std::path::{Path, PathBuf};

fn scratch(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("dsdup-out-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// A DSD64 DSF input of `seconds`, written to `dir/in.dsf`.
fn input(dir: &Path, seconds: f64) -> PathBuf {
    let s = Sine {
        freq: 1000,
        level_db: -6.0,
        seconds,
        channels: 2,
    };
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), 2, 44_100 * 64, None).unwrap();
    testsignal::write_dsd_to(&mut w, 64, &s).unwrap();
    let p = dir.join("in.dsf");
    std::fs::write(&p, w.into_inner().into_inner()).unwrap();
    p
}

/// File names in `dir`, sorted.
fn names(dir: &Path) -> Vec<String> {
    let mut v: Vec<String> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    v.sort();
    v
}

fn opts(threads: bool) -> Options {
    let mut o = Options::new(Output::Dsd { mult: 128 });
    o.threads = threads;
    o
}

/// A cancel, an error and a panic part-way leave neither the output nor a temporary file.
#[test]
fn failure_midway_leaves_no_file_and_no_temp() {
    let d = scratch("fail");
    let inp = input(&d, 0.5);
    let out = d.join("out.dsf");
    for threads in [false, true] {
        // cancel after the first chunk
        let mut calls = 0;
        let r = convert_file_to(
            &inp,
            &out,
            &opts(threads),
            &FileOutput::default(),
            Some(&mut |_, _| {
                calls += 1;
                assert!(
                    d.join("out.part1.dsf").exists(),
                    "writes to the temporary name"
                );
                assert!(!out.exists(), "nothing under the final name yet");
                calls < 2
            }),
        );
        assert!(r.as_ref().is_err_and(is_cancelled), "{r:?}");
        assert_eq!(names(&d), ["in.dsf"]);
        // a panic in the callback unwinds through the conversion
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            convert_file_to(
                &inp,
                &out,
                &opts(threads),
                &FileOutput::default(),
                Some(&mut |_, _| panic!("host failure")),
            )
        }));
        assert!(r.is_err());
        assert_eq!(names(&d), ["in.dsf"]);
    }
    // PCM output: cancelled part-way
    let wav = d.join("out.wav");
    let mut calls = 0;
    let r = convert_file_to(
        &inp,
        &wav,
        &Options::new(Output::Pcm(dsd_upsample::dsd2pcm::PcmRate::Hz176400)),
        &FileOutput::default(),
        Some(&mut |_, _| {
            calls += 1;
            calls < 2
        }),
    );
    assert!(r.as_ref().is_err_and(is_cancelled), "{r:?}");
    assert_eq!(names(&d), ["in.dsf"]);
    // an input that ends before its header says: an error during the conversion
    let bytes = std::fs::read(&inp).unwrap();
    let short = d.join("short.dsf");
    std::fs::write(&short, &bytes[..bytes.len() * 2 / 3]).unwrap();
    let r = convert_file_to(&short, &out, &opts(true), &FileOutput::default(), None);
    assert!(r.is_err(), "{r:?}");
    assert_eq!(names(&d), ["in.dsf", "short.dsf"]);
    std::fs::remove_dir_all(&d).unwrap();
}

/// An existing output is left as it was by a failed run, and replaced by a successful one.
#[test]
fn existing_output_survives_a_failed_run() {
    let d = scratch("keep");
    let inp = input(&d, 0.2);
    let out = d.join("out.dsf");
    std::fs::write(&out, b"the good old output").unwrap();
    let mut calls = 0;
    let r = convert_file_to(
        &inp,
        &out,
        &opts(true),
        &FileOutput::default(),
        Some(&mut |_, _| {
            calls += 1;
            calls < 2
        }),
    );
    assert!(r.as_ref().is_err_and(is_cancelled), "{r:?}");
    assert_eq!(std::fs::read(&out).unwrap(), b"the good old output");
    assert_eq!(names(&d), ["in.dsf", "out.dsf"]);
    // success replaces it with the same bytes as a fresh output
    convert_file_to(&inp, &out, &opts(true), &FileOutput::default(), None).unwrap();
    let fresh = d.join("fresh.dsf");
    convert_file_to(&inp, &fresh, &opts(true), &FileOutput::default(), None).unwrap();
    assert_eq!(std::fs::read(&out).unwrap(), std::fs::read(&fresh).unwrap());
    assert_eq!(names(&d), ["fresh.dsf", "in.dsf", "out.dsf"]);
    std::fs::remove_dir_all(&d).unwrap();
}

/// A temporary name in use is skipped (N counts up) and left alone.
#[test]
fn temporary_names_count_up() {
    let d = scratch("names");
    let inp = input(&d, 0.1);
    let out = d.join("out.dsf");
    std::fs::write(d.join("out.part1.dsf"), b"someone else's").unwrap();
    let mut seen = false;
    convert_file_to(
        &inp,
        &out,
        &opts(false),
        &FileOutput::default(),
        Some(&mut |_, _| {
            seen |= d.join("out.part2.dsf").exists();
            true
        }),
    )
    .unwrap();
    assert!(seen);
    assert_eq!(
        std::fs::read(d.join("out.part1.dsf")).unwrap(),
        b"someone else's"
    );
    assert_eq!(names(&d), ["in.dsf", "out.dsf", "out.part1.dsf"]);
    std::fs::remove_dir_all(&d).unwrap();
}

/// no_overwrite: an existing output is refused up front; one that appears during the
/// conversion is not replaced at the end (the race), and no temporary file is left.
#[test]
fn no_overwrite_race() {
    let d = scratch("race");
    let inp = input(&d, 0.2);
    let out = d.join("out.dsf");
    let file = FileOutput {
        no_overwrite: true,
        ..FileOutput::default()
    };
    // free name: converted
    convert_file_to(&inp, &out, &opts(true), &file, None).unwrap();
    let converted = std::fs::read(&out).unwrap();
    // existing: refused before any work, untouched
    let mut called = false;
    let r = convert_file_to(
        &inp,
        &out,
        &opts(true),
        &file,
        Some(&mut |_, _| {
            called = true;
            true
        }),
    );
    let e = r.unwrap_err();
    assert!(
        matches!(&e, dsd_upsample::Error::Io(io) if io.kind() == std::io::ErrorKind::AlreadyExists),
        "{e:?}"
    );
    assert!(!called);
    assert_eq!(std::fs::read(&out).unwrap(), converted);
    // appears during the conversion: the racer's file wins
    std::fs::remove_file(&out).unwrap();
    let mut first = true;
    let r = convert_file_to(
        &inp,
        &out,
        &opts(true),
        &file,
        Some(&mut |_, _| {
            if first {
                std::fs::write(&out, b"racer").unwrap();
                first = false;
            }
            true
        }),
    );
    let e = r.unwrap_err();
    assert!(
        matches!(&e, dsd_upsample::Error::Io(io) if io.kind() == std::io::ErrorKind::AlreadyExists),
        "{e:?}"
    );
    assert_eq!(std::fs::read(&out).unwrap(), b"racer");
    assert_eq!(names(&d), ["in.dsf", "out.dsf"]);
    std::fs::remove_dir_all(&d).unwrap();
}
