// SPDX-License-Identifier: MIT OR Apache-2.0
//! Deterministic test signals: sines as DSD (DSF/DFF) or PCM WAV.
//!
//! The sine uses only IEEE-754 additions, multiplications and divisions in a fixed order
//! (exact integer phase reduction, then Taylor series), so test files are identical on
//! every platform and the golden hashes hold everywhere.

use crate::convert::DEFAULT_INPUT_LIMIT;
use crate::modulator::{Counters, Modulator};
use crate::tables;
use dsd2pcm::dff::DffWriter;
use dsd2pcm::dsf::DsfWriter;
use dsd2pcm::io::DsdWrite;
use dsd2pcm::wav::{WavFormat, WavWriter};
use dsd2pcm::{decimator::db_to_linear, Error, Result};
use std::fs::File;
use std::io::{BufWriter, Seek, Write};
use std::path::Path;

fn taylor_sin(t: f64) -> f64 {
    let t2 = t * t;
    let mut term = t;
    let mut sum = t;
    let mut k = 1.0f64;
    for _ in 0..12 {
        term = -term * t2 / ((k + 1.0) * (k + 2.0));
        sum += term;
        k += 2.0;
    }
    sum
}

fn taylor_cos(t: f64) -> f64 {
    let t2 = t * t;
    let mut term = 1.0f64;
    let mut sum = 1.0f64;
    let mut k = 0.0f64;
    for _ in 0..12 {
        term = -term * t2 / ((k + 1.0) * (k + 2.0));
        sum += term;
        k += 2.0;
    }
    sum
}

/// `sin(2 pi num / den)`, deterministic. `den` must be non-zero.
pub fn sin_turns(num: u64, den: u64) -> f64 {
    let den = u128::from(den.max(1));
    let q4 = 4 * (u128::from(num) % den);
    let quadrant = q4 / den;
    let r = q4 - quadrant * den;
    let theta = std::f64::consts::FRAC_PI_2 * (r as f64 / den as f64);
    match quadrant {
        0 => taylor_sin(theta),
        1 => taylor_cos(theta),
        2 => -taylor_sin(theta),
        _ => -taylor_cos(theta),
    }
}

/// A sine test signal.
#[derive(Clone, Copy, Debug)]
pub struct Sine {
    /// Frequency in Hz.
    pub freq: u32,
    /// Level in dB: re 0 dB SACD (50 % modulation) for DSD, re digital full scale for PCM.
    pub level_db: f64,
    /// Duration in seconds.
    pub seconds: f64,
    /// Channels (1..=6); every channel carries the same sine.
    pub channels: u16,
}

/// Highest level of a DSD test tone, in dB re 0 dB SACD: +3.1, the peak level of Super
/// Audio CD (71.4 % modulation).
pub const MAX_DSD_LEVEL_DB: f64 = 3.1;

/// Order of the modulator of DSD test tones up to 0 dB SACD: 7, accepted at every rate
/// (clean on every legal signal of the stability study), with a 1 kHz SINAD of 125.7,
/// 170.3 and 214.4 dB at DSD64, DSD128 and DSD256 (docs/modulator-design.md).
const TONE_ORDER: usize = 7;

/// State bounds of the second-order modulator used above 0 dB SACD. On tones up to
/// [`MAX_DSD_LEVEL_DB`] its integrators reach 2.6 and 7.1 at most (measured, 50 Hz to
/// 19 kHz at every rate); a sample beyond a bound counts as an overload.
const SECOND_ORDER_BOUNDS: [f64; 2] = [4.0, 12.0];

/// Writes a DSD sine (DSD64, DSD128 or DSD256 by `mult`) as DSF or DFF by extension. See
/// [`write_dsd_counted`] for the modulators and the level range.
pub fn write_dsd(path: &Path, mult: u32, s: &Sine) -> Result<()> {
    check_level(s)?; // before the file is created
    let rate = 44_100 * mult;
    let out = BufWriter::new(File::create(path)?);
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let mut sink: Box<dyn DsdWrite> = match ext.as_str() {
        "dsf" => Box::new(DsfWriter::new(out, s.channels, rate, None)?),
        "dff" => Box::new(DffWriter::new(out, s.channels, rate)?),
        _ => {
            return Err(Error::InvalidArgument(
                "DSD test signal needs .dsf or .dff".into(),
            ))
        }
    };
    write_dsd_to(sink.as_mut(), mult, s)
}

/// [`write_dsd`] into any DSD sink (which is finished).
pub fn write_dsd_to(sink: &mut dyn DsdWrite, mult: u32, s: &Sine) -> Result<()> {
    write_dsd_counted(sink, mult, s).map(drop)
}

/// Refuses a level above [`MAX_DSD_LEVEL_DB`] (written so that a level that is not a
/// number is refused too).
fn check_level(s: &Sine) -> Result<()> {
    if s.level_db <= MAX_DSD_LEVEL_DB {
        return Ok(());
    }
    Err(Error::InvalidArgument(format!(
        "DSD test signal level {} dB SACD: the maximum is +{MAX_DSD_LEVEL_DB} dB SACD (the \
         Super Audio CD peak level)",
        s.level_db
    )))
}

/// The second-order modulator of the tones above 0 dB SACD: two integrators and a one-bit
/// quantiser, noise transfer function (1 - z^-1)^2. It carries a tone at 71.4 % modulation
/// without overload, which the shipped tables (stable to 51 %) cannot; its noise in the
/// audio band is far higher than theirs (a 1 kHz tone at +3.1 dB SACD measures 72 dB above
/// the noise from 20 Hz to 20 kHz at DSD64, 87 dB at DSD128 and 102 dB at DSD256).
struct SecondOrder {
    x1: f64,
    x2: f64,
    over: u64,
}

impl SecondOrder {
    fn run(&mut self, u: &[f64], emit: &mut impl FnMut(bool)) {
        for &u in u {
            let bit = self.x2 >= 0.0;
            let v = if bit { 1.0 } else { -1.0 };
            self.x1 += u - v;
            self.x2 += self.x1 - v;
            if self.x1.abs() > SECOND_ORDER_BOUNDS[0] || self.x2.abs() > SECOND_ORDER_BOUNDS[1] {
                self.over += 1;
            }
            emit(bit);
        }
    }
}

enum Gen {
    Table(Box<Modulator>),
    Second(SecondOrder),
}

/// [`write_dsd_to`], returning the overload counters of the generator's own modulator.
/// They are zero for every level the generator accepts (a test checks it), so the stream
/// is a clean one.
///
/// Up to 0 dB SACD the modulator is this crate's order-7 one for that rate, at the default
/// input limit. From there to [`MAX_DSD_LEVEL_DB`] (+3.1 dB SACD, the Super Audio
/// CD peak level) it is a second-order modulator, which is stable at that level; its
/// in-band noise is much higher (72 dB below the tone at DSD64). Higher levels are
/// refused.
pub fn write_dsd_counted(sink: &mut dyn DsdWrite, mult: u32, s: &Sine) -> Result<Counters> {
    let table = tables::modulator(mult, TONE_ORDER, false).ok_or_else(|| {
        Error::InvalidArgument(format!("test signal rate DSD{mult}: 64, 128 or 256"))
    })?;
    check_level(s)?;
    let rate = 44_100 * mult;
    let amp = 0.5 * db_to_linear(s.level_db);
    let n = (s.seconds * f64::from(rate)) as u64 / 8 * 8;
    let mut m = if s.level_db <= 0.0 {
        Gen::Table(Box::new(Modulator::new(table, DEFAULT_INPUT_LIMIT)))
    } else {
        Gen::Second(SecondOrder {
            x1: 0.0,
            x2: 0.0,
            over: 0,
        })
    };
    let ch = usize::from(s.channels);
    let chunk = 1u64 << 16;
    let mut i = 0u64;
    let mut u = Vec::new();
    while i < n {
        let k = chunk.min(n - i);
        u.clear();
        u.extend((i..i + k).map(|j| amp * sin_turns(j * u64::from(s.freq), u64::from(rate))));
        let mut bytes = Vec::with_capacity((k / 8) as usize);
        let (mut acc, mut na) = (0u8, 0);
        let mut emit = |b: bool| {
            acc = (acc << 1) | u8::from(b);
            na += 1;
            if na == 8 {
                bytes.push(acc);
                acc = 0;
                na = 0;
            }
        };
        match &mut m {
            Gen::Table(m) => m.run(&u, &mut emit),
            Gen::Second(m) => m.run(&u, &mut emit),
        }
        sink.write_bytes(&vec![bytes; ch])?;
        i += k;
    }
    sink.finish(n)?;
    Ok(match m {
        Gen::Table(m) => m.counters,
        Gen::Second(m) => Counters {
            limited: 0,
            clipped: m.over,
            resets: 0,
        },
    })
}

/// Writes a PCM sine as WAV (`format`) at `fs` Hz.
pub fn write_wav(path: &Path, fs: u32, format: WavFormat, s: &Sine) -> Result<()> {
    let out = BufWriter::new(File::create(path)?);
    write_wav_to(out, fs, format, s).map(|_| ())
}

/// [`write_wav`] into any writer; returns it.
pub fn write_wav_to<W: Write + Seek>(w: W, fs: u32, format: WavFormat, s: &Sine) -> Result<W> {
    let mut wr = WavWriter::new(w, format, s.channels, fs)?;
    let amp = db_to_linear(s.level_db);
    let n = (s.seconds * f64::from(fs)) as u64;
    let mut raw = Vec::new();
    for j in 0..n {
        let v = amp * sin_turns(j * u64::from(s.freq), u64::from(fs));
        let mut one = Vec::new();
        match format {
            WavFormat::I16 => one.extend_from_slice(&((v * 32767.0).round() as i16).to_le_bytes()),
            WavFormat::I24 => {
                one.extend_from_slice(&((v * 8_388_607.0).round() as i32).to_le_bytes()[..3])
            }
            WavFormat::I32 => {
                one.extend_from_slice(&((v * 2_147_483_647.0).round() as i32).to_le_bytes())
            }
            WavFormat::F32 => one.extend_from_slice(&(v as f32).to_le_bytes()),
            WavFormat::F64 => one.extend_from_slice(&v.to_le_bytes()),
        }
        for _ in 0..s.channels {
            raw.extend_from_slice(&one);
        }
        if raw.len() > 1 << 20 {
            wr.write_raw(&raw)?;
            raw.clear();
        }
    }
    wr.write_raw(&raw)?;
    wr.finish()?;
    Ok(wr.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Null;

    impl DsdWrite for Null {
        fn write_bytes(&mut self, _: &[Vec<u8>]) -> Result<()> {
            Ok(())
        }
        fn finish(&mut self, _: u64) -> Result<()> {
            Ok(())
        }
    }

    /// The generator's own modulator never overloads at a level it accepts, and levels
    /// above the Super Audio CD peak level are refused.
    #[test]
    fn dsd_generator_is_clean_at_every_accepted_level() {
        let seconds = if cfg!(debug_assertions) { 0.1 } else { 1.0 };
        for mult in [64, 128, 256] {
            for freq in [50, 1000, 10_000, 19_000] {
                for level_db in [-60.0, -20.0, -6.0, -3.0, -0.1, 0.0, 0.1, 1.0, 2.0, 3.0, 3.1] {
                    let s = Sine {
                        freq,
                        level_db,
                        seconds,
                        channels: 1,
                    };
                    let k = write_dsd_counted(&mut Null, mult, &s).unwrap();
                    assert_eq!(
                        k,
                        Counters::default(),
                        "DSD{mult} {freq} Hz {level_db} dB SACD"
                    );
                }
            }
            for level_db in [3.11, 6.0, f64::INFINITY, f64::NAN] {
                let s = Sine {
                    freq: 1000,
                    level_db,
                    seconds: 0.01,
                    channels: 1,
                };
                let e = write_dsd_counted(&mut Null, mult, &s).unwrap_err();
                assert!(e.to_string().contains("+3.1 dB SACD"), "{e}");
            }
        }
    }

    #[test]
    fn sine_is_accurate() {
        for &(n, d) in &[
            (0u64, 7u64),
            (1, 4),
            (1, 12),
            (5, 12),
            (7, 8),
            (123_456, 1_000_000),
        ] {
            let want = (2.0 * std::f64::consts::PI * n as f64 / d as f64).sin();
            assert!((sin_turns(n, d) - want).abs() < 1e-15, "{n}/{d}");
        }
        assert_eq!(sin_turns(1, 4), 1.0);
        assert_eq!(sin_turns(0, 9), 0.0);
    }
}
