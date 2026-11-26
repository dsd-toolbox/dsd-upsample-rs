// SPDX-License-Identifier: MIT OR Apache-2.0
//! Golden hashes for consumers: SHA-256 of conversions at the default settings
//! (`Options::new`), so that a program embedding this library can pin the engine's bytes in
//! its own tests and see when they change.
//!
//! ```sh
//! cargo run --release -p dsd-upsample --example golden                 # built-in signals
//! cargo run --release -p dsd-upsample --example golden -- --rate 256 a.dsf b.flac
//! ```
//!
//! Output, tab-separated: `engine_id  case  sha256  output samples per channel`. Built-in
//! cases are synthetic test tones (stereo and 5.1); a file case is the DSF file that the
//! library's `convert_file` writes for that input at the default settings, as the command
//! line tool does without options. The stereo built-in cases are the crate's own golden
//! hashes (`tests/pipeline.rs`), checked by this example's test.

use dsd_upsample::dsd2pcm::dsf::{DsfReader, DsfWriter};
use dsd_upsample::dsd2pcm::wav::{WavFormat, WavReader};
use dsd_upsample::dsd2pcm::Input;
use dsd_upsample::testsignal::{self, Sine};
use dsd_upsample::{convert, convert_file, engine_id, Options, Output};
use sha2::{Digest, Sha256};
use std::io::Cursor;
use std::path::{Path, PathBuf};

fn hex(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|x| format!("{x:02x}"))
        .collect()
}

fn sine(channels: u16) -> Sine {
    Sine {
        freq: 1000,
        level_db: -6.0,
        seconds: 0.05,
        channels,
    }
}

/// One built-in case: name, DSF output bytes, output samples per channel.
fn builtin_case(name: &str) -> (Vec<u8>, u64) {
    let (input, ch, mult): (Input, u16, u32) = match name {
        "dsd64-2ch-to-dsd128"
        | "dsd64-2ch-to-dsd256"
        | "dsd64-6ch-to-dsd128"
        | "dsd64-6ch-to-dsd256" => {
            let ch = if name.contains("-6ch-") { 6 } else { 2 };
            let mult = if name.ends_with("256") { 256 } else { 128 };
            let mut w = DsfWriter::new(Cursor::new(Vec::new()), ch, 2_822_400, None).unwrap();
            testsignal::write_dsd_to(&mut w, 64, &sine(ch)).unwrap();
            let r = DsfReader::new(Cursor::new(w.into_inner().into_inner())).unwrap();
            (Input::Dsd(Box::new(r)), ch, mult)
        }
        "pcm88k-2ch-to-dsd128" | "pcm48k-2ch-to-dsd128" | "pcm44k-6ch-to-dsd256" => {
            let (fs, ch, mult) = match name {
                "pcm88k-2ch-to-dsd128" => (88_200, 2, 128),
                "pcm48k-2ch-to-dsd128" => (48_000, 2, 128),
                _ => (44_100, 6, 256),
            };
            let wav =
                testsignal::write_wav_to(Cursor::new(Vec::new()), fs, WavFormat::I24, &sine(ch))
                    .unwrap()
                    .into_inner();
            let r = WavReader::new(Cursor::new(wav)).unwrap();
            (Input::Pcm(Box::new(r)), ch, mult)
        }
        other => panic!("no built-in case {other}"),
    };
    let mut w = DsfWriter::new(Cursor::new(Vec::new()), ch, 44_100 * mult, None).unwrap();
    let rep = convert(input, &mut w, &Options::new(Output::Dsd { mult })).unwrap();
    (w.into_inner().into_inner(), rep.out_samples)
}

const BUILTIN: &[&str] = &[
    "dsd64-2ch-to-dsd128",
    "dsd64-2ch-to-dsd256",
    "dsd64-6ch-to-dsd128",
    "dsd64-6ch-to-dsd256",
    "pcm88k-2ch-to-dsd128",
    "pcm48k-2ch-to-dsd128",
    "pcm44k-6ch-to-dsd256",
];

/// Converts a file at the default settings to a temporary DSF; returns its hash and length.
fn file_case(path: &Path, mult: u32, tmp: &Path) -> Result<(String, u64), String> {
    let out = tmp.join(format!("golden-{}.dsf", std::process::id()));
    let rep = convert_file(path, &out, &Options::new(Output::Dsd { mult }))
        .map_err(|e| format!("{}: {e}", path.display()));
    let bytes = std::fs::read(&out);
    let _ = std::fs::remove_file(&out);
    let rep = rep?;
    let bytes = bytes.map_err(|e| format!("{}: {e}", out.display()))?;
    Ok((hex(&bytes), rep.out_samples))
}

fn main() {
    let mut args = std::env::args().skip(1);
    let mut mult = 128u32;
    let mut files: Vec<PathBuf> = Vec::new();
    while let Some(a) = args.next() {
        match a.as_str() {
            "--rate" => {
                mult = match args.next().as_deref() {
                    Some("128") => 128,
                    Some("256") => 256,
                    _ => {
                        eprintln!("golden: --rate takes 128 or 256");
                        std::process::exit(2);
                    }
                }
            }
            "-h" | "--help" => {
                println!(
                    "golden [--rate 128|256] [FILE...]: SHA-256 of default-setting conversions"
                );
                return;
            }
            _ => files.push(PathBuf::from(a)),
        }
    }
    let id = engine_id();
    if files.is_empty() {
        for name in BUILTIN {
            let (bytes, n) = builtin_case(name);
            println!("{id}\t{name}\t{}\t{n}", hex(&bytes));
        }
        return;
    }
    let tmp = std::env::temp_dir();
    let mut failed = false;
    for f in &files {
        match file_case(f, mult, &tmp) {
            Ok((h, n)) => println!("{id}\t{}@dsd{mult}\t{h}\t{n}", f.display()),
            Err(e) => {
                eprintln!("golden: {e}");
                failed = true;
            }
        }
    }
    if failed {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use dsd_upsample::dsd2pcm::io::DsdRead;

    /// The stereo built-in cases are the crate's own golden hashes (tests/pipeline.rs:
    /// dsd64-to-dsd128-o6, dsd64-to-dsd256-o6, golden_48k_family 48 kHz), so this tool and
    /// the test suite agree on every platform CI runs.
    #[test]
    fn stereo_cases_are_the_crate_goldens() {
        for (name, want) in [
            (
                "dsd64-2ch-to-dsd128",
                "877da956287c9604056cdb67b6d6aede4c74d6379f32ca35cf75bec9fcc392bf",
            ),
            (
                "dsd64-2ch-to-dsd256",
                "4cfadce3c7585d4f7441a0f532fc1741792d5916fc6d482c28deca8b22e76180",
            ),
            (
                "pcm48k-2ch-to-dsd128",
                "191a08647386714d1d7885fca14bcb42dff5fdfa25004dc718fc08fca3dd10e9",
            ),
        ] {
            assert_eq!(hex(&builtin_case(name).0), want, "{name}");
        }
    }

    /// Every built-in case converts, with the exact output length.
    #[test]
    fn every_case_runs() {
        for name in BUILTIN {
            let (bytes, n) = builtin_case(name);
            let r = DsfReader::new(Cursor::new(bytes)).unwrap();
            assert_eq!(r.info().samples, n, "{name}");
            assert!(n > 0, "{name}");
        }
    }

    /// A file case hashes the DSF that convert_file writes, and a missing file is an error.
    #[test]
    fn file_case_matches_convert_file() {
        let dir = std::env::temp_dir().join(format!("golden-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let input = dir.join("in.dsf");
        testsignal::write_dsd(&input, 64, &sine(2)).unwrap();
        let (h, n) = file_case(&input, 128, &dir).unwrap();
        let (want, wn) = builtin_case("dsd64-2ch-to-dsd128");
        // The file path writes the same audio; the DSF may differ only by a carried-over tag,
        // and a generated tone has none.
        assert_eq!((h, n), (hex(&want), wn));
        assert!(file_case(&dir.join("missing.dsf"), 128, &dir).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
