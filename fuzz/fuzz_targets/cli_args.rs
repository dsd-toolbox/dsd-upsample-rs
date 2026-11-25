// SPDX-License-Identifier: MIT OR Apache-2.0
// The CLI's argument parser with arbitrary argument vectors, including arguments that are
// not valid UTF-8, in both modes (conversion and gen): never panics, refuses only with a
// usage error, and never converts or touches a file. The vector goes through the same
// steps as `main` up to the point where files are opened.
#![no_main]
use libfuzzer_sys::fuzz_target;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;

#[allow(dead_code)]
#[path = "../../crates/dsd-upsample-cli/src/args.rs"]
mod args;

/// Arguments the parser knows, so the fuzzer reaches the option paths quickly. An argument
/// of one byte below 0x30 picks one of these; anything else is taken as raw bytes.
const TOKENS: &[&str] = &[
    "--rate",
    "--order",
    "--gain",
    "--cutoff",
    "--limit",
    "--out-dir",
    "--format",
    "--jobs",
    "--suffix",
    "--tag",
    "--dither",
    "--single-thread",
    "--no-overwrite",
    "--json",
    "-h",
    "--help",
    "--version",
    "-V",
    "gen",
    "--fs",
    "--freq",
    "--level",
    "--seconds",
    "--channels",
    "--bits",
    "64",
    "128",
    "256",
    "pcm88",
    "pcm176",
    "pcm352",
    "wide",
    "30",
    "40",
    "dsf",
    "dff",
    "wav",
    "NaN",
    "inf",
    "-1e309",
    "1e309",
    "0",
    "-0",
    "title=x",
    "=",
    "--",
    "---",
];

fuzz_target!(|data: &[u8]| {
    // Arguments are separated by 0x00, which a real argument cannot contain.
    let argv: Vec<OsString> = data
        .split(|&b| b == 0)
        .map(|a| match a {
            [t] if usize::from(*t) < TOKENS.len() && *t < 0x30 => {
                OsString::from(TOKENS[usize::from(*t)])
            }
            raw => OsString::from_vec(raw.to_vec()),
        })
        .collect();
    // As main: --help and --version before `--` win, then `gen` picks the mode. Both modes
    // are tried on every vector, so mode-specific refusals are exercised either way.
    let _ = args::before_end(&argv).any(|a| a == "--version" || a == "-h");
    for gen in [false, true] {
        let rest = if gen && argv.first().is_some_and(|a| a == "gen") {
            &argv[1..]
        } else {
            &argv[..]
        };
        let a = match args::split(rest, gen) {
            Ok(a) => a,
            Err(f) => {
                // A refused command line is a usage error (exit status 2), never a run error.
                assert_eq!(f.code(), 2, "{f:?}");
                continue;
            }
        };
        // Every positional argument is one of the inputs, unchanged.
        for p in &a.pos {
            assert!(rest.iter().any(|r| r == p.as_os_str()));
            let _ = args::shown(p);
        }
        // Options read as main reads them; errors are fine, panics are not.
        if gen {
            let _ = a.num("freq", 1000u32);
            let _ = a.num("level", -6.0f64);
            let _ = a.num("seconds", 5.0f64);
            let _ = a.num("channels", 2u16);
            let _ = a.num("fs", 44_100u32);
            let _ = a.num("rate", 64u32);
            let _ = a.get("bits");
        } else {
            if let Err(f) = args::options(&a) {
                assert_eq!(f.code(), 2, "{f:?}");
            }
            let _ = a.get("format");
            let _ = a.num("jobs", 1usize);
            let _ = a.flag("--json");
            if let Some(d) = a.get_os("out-dir") {
                let _ = args::shown(std::path::Path::new(d));
            }
            let _ = a
                .get_os("suffix")
                .map(|s| s.to_string_lossy().contains(['/', '\\']));
        }
    }
});
