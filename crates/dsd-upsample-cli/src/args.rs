// SPDX-License-Identifier: MIT OR Apache-2.0
//! Argument parsing: splitting the command line and reading the conversion options. No
//! files are touched here, so the fuzz target `cli_args` can include this file and feed
//! it arbitrary argument vectors.

use dsd_upsample::dsd2pcm::decimator::{Cutoff, PcmRate};
use dsd_upsample::{Options, Output};
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

/// Why the tool stops early, with its exit status.
#[derive(Debug)]
pub(crate) enum Fail {
    /// The command line is invalid (exit status 2); nothing was converted.
    Usage(String),
    /// A conversion or I/O error (exit status 1).
    Run(String),
    /// Ctrl-C stopped a conversion before it finished (exit status 130).
    Interrupted,
}

impl Fail {
    pub(crate) fn code(&self) -> u8 {
        match self {
            Fail::Usage(_) => 2,
            Fail::Run(_) => 1,
            Fail::Interrupted => 130,
        }
    }
}

pub(crate) fn usage(msg: impl Into<String>) -> Fail {
    Fail::Usage(msg.into())
}

pub(crate) struct Args {
    pub(crate) pos: Vec<PathBuf>,
    pub(crate) kv: Vec<(String, String)>,
    /// Options whose values are paths or parts of file names, kept as given (they need
    /// not be UTF-8).
    pub(crate) os_kv: Vec<(String, OsString)>,
    pub(crate) tags: Vec<(String, String)>,
    pub(crate) flags: Vec<String>,
}

/// Options whose value is kept as an [`OsString`].
pub(crate) const OS_OPTIONS: [&str; 2] = ["out-dir", "suffix"];

/// Options of a conversion that take a value (`--tag` among them).
pub(crate) const CONVERT_VALUES: [&str; 10] = [
    "rate", "order", "gain", "cutoff", "limit", "format", "tag", "out-dir", "jobs", "suffix",
];
/// Options of a conversion without a value.
pub(crate) const CONVERT_FLAGS: [&str; 4] = ["dither", "single-thread", "no-overwrite", "json"];
/// Options of `gen`, all with a value.
pub(crate) const GEN_VALUES: [&str; 7] =
    ["rate", "fs", "freq", "level", "seconds", "channels", "bits"];

/// The arguments before `--` (where `--help` and `--version` are looked for).
pub(crate) fn before_end(args: &[OsString]) -> impl Iterator<Item = &OsString> {
    args.iter().take_while(|a| *a != "--")
}

/// Splits the arguments of a conversion or (`gen`) of the test signal generator. Arguments
/// are [`OsString`]s: positional arguments (paths) and the values of [`OS_OPTIONS`] need
/// not be valid UTF-8; option names and other values must be. An argument starting with
/// `--` is an option; after a bare `--`, every argument is positional. Options of the other
/// mode and unknown options are usage errors.
pub(crate) fn split(args: &[OsString], gen: bool) -> Result<Args, Fail> {
    let (values, flags): (&[&str], &[&str]) = if gen {
        (&GEN_VALUES, &[])
    } else {
        (&CONVERT_VALUES, &CONVERT_FLAGS)
    };
    let mut a = Args {
        pos: Vec::new(),
        kv: Vec::new(),
        os_kv: Vec::new(),
        tags: Vec::new(),
        flags: Vec::new(),
    };
    let utf8 = |what: &str, v: &OsString| -> Result<String, Fail> {
        v.to_str().map(str::to_string).ok_or_else(|| {
            usage(format!(
                "{what}: {} is not valid UTF-8",
                shown(Path::new(v))
            ))
        })
    };
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        if arg == "--" {
            a.pos.extend(it.by_ref().map(PathBuf::from));
            break;
        }
        if !arg.as_encoded_bytes().starts_with(b"--") {
            a.pos.push(PathBuf::from(arg));
            continue;
        }
        let s = utf8("option", arg)?;
        let k = &s[2..];
        if flags.contains(&k) {
            a.flags.push(s);
        } else if values.contains(&k) {
            let v = it
                .next()
                .ok_or_else(|| usage(format!("{s} needs a value")))?;
            if k == "tag" {
                let v = utf8("--tag", v)?;
                let (key, val) = v
                    .split_once('=')
                    .ok_or_else(|| usage(format!("--tag {v}: expected KEY=VALUE")))?;
                a.tags.push((key.to_string(), val.to_string()));
            } else if OS_OPTIONS.contains(&k) {
                a.os_kv.push((k.to_string(), v.clone()));
            } else {
                a.kv.push((k.to_string(), utf8(&s, v)?));
            }
        } else if gen && (CONVERT_VALUES.contains(&k) || CONVERT_FLAGS.contains(&k)) {
            return Err(usage(format!(
                "{s} is a conversion option; it does not apply to gen"
            )));
        } else if !gen && GEN_VALUES.contains(&k) {
            return Err(usage(format!(
                "{s} is a gen option (test signals); it does not apply to a conversion"
            )));
        } else {
            return Err(usage(format!("unknown option {s}")));
        }
    }
    Ok(a)
}

impl Args {
    pub(crate) fn get(&self, k: &str) -> Option<&str> {
        self.kv
            .iter()
            .rev()
            .find(|(kk, _)| kk == k)
            .map(|(_, v)| v.as_str())
    }
    pub(crate) fn get_os(&self, k: &str) -> Option<&OsStr> {
        self.os_kv
            .iter()
            .rev()
            .find(|(kk, _)| kk == k)
            .map(|(_, v)| v.as_os_str())
    }
    pub(crate) fn num<T: std::str::FromStr>(&self, k: &str, default: T) -> Result<T, Fail> {
        match self.get(k) {
            None => Ok(default),
            Some(v) => v
                .parse()
                .map_err(|_| usage(format!("bad value for --{k}: {v}"))),
        }
    }
    pub(crate) fn flag(&self, f: &str) -> bool {
        self.flags.iter().any(|x| x == f)
    }
}

pub(crate) fn cutoff(a: &Args) -> Result<Option<Cutoff>, Fail> {
    Ok(match a.get("cutoff") {
        None => None,
        Some("30") => Some(Cutoff::Low),
        Some("40") => Some(Cutoff::Standard),
        Some("wide" | "80") => Some(Cutoff::Wide),
        Some(v) => return Err(usage(format!("cutoff {v}: 30, 40 or wide"))),
    })
}

/// The conversion settings, checked as the library would check them.
pub(crate) fn options(a: &Args) -> Result<Options, Fail> {
    let output = match a.get("rate").ok_or_else(|| usage("--rate is required"))? {
        "64" => Output::Dsd { mult: 64 },
        "128" => Output::Dsd { mult: 128 },
        "256" => Output::Dsd { mult: 256 },
        "pcm88" => Output::Pcm(PcmRate::Hz88200),
        "pcm176" => Output::Pcm(PcmRate::Hz176400),
        "pcm352" => Output::Pcm(PcmRate::Hz352800),
        v => {
            return Err(usage(format!(
                "rate {v}: 64, 128, 256, pcm88, pcm176 or pcm352"
            )))
        }
    };
    let mut o = Options::new(output);
    o.order = a.num("order", o.order)?;
    o.gain_db = a.num("gain", o.gain_db)?;
    o.cutoff = cutoff(a)?;
    o.dither = a.flag("--dither");
    o.threads = !a.flag("--single-thread");
    if let Some(l) = a.get("limit") {
        o.input_limit = Some(l.parse().map_err(|_| usage(format!("bad --limit {l}")))?);
    }
    o.validate().map_err(|e| usage(e.to_string()))?;
    Ok(o)
}

/// Invisible formatting characters that can disguise text: bidirectional controls and
/// zero-width characters (Unicode category Cf, the ones in common use).
pub(crate) fn is_format(c: char) -> bool {
    matches!(c, '\u{061C}' | '\u{200B}'..='\u{200F}' | '\u{202A}'..='\u{202E}'
        | '\u{2060}'..='\u{2064}' | '\u{2066}'..='\u{2069}' | '\u{FEFF}')
}

/// A path for the terminal: control and formatting characters escaped (names may come
/// from anywhere).
pub(crate) fn shown(p: &Path) -> String {
    p.to_string_lossy()
        .chars()
        .flat_map(|c| {
            if c.is_control() || is_format(c) {
                c.escape_default().collect::<Vec<_>>()
            } else {
                vec![c]
            }
        })
        .collect()
}
