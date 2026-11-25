// SPDX-License-Identifier: MIT OR Apache-2.0
//! The conversion pipeline: DSD or PCM in, DSD64 (from PCM), DSD128, DSD256 or 24-bit PCM
//! out.
//!
//! DSD to DSD, per channel:
//! 1. to PCM at 352.8 kHz: DSD64 through a byte-LUT Kaiser FIR (or, on request, the
//!    `dsd2pcm` decimator with a chosen
//!    [`Cutoff`]), DSD128/DSD256 through a byte-LUT Kaiser FIR; PCM input through x2
//!    interpolators up to 352.8 kHz, 48 kHz-family PCM first through a 147/160 polyphase
//!    resampler to the 44.1 kHz-family rate below it;
//! 2. gain (default -6 dB, see [`DEFAULT_GAIN_DB`]);
//! 3. x2 half-band interpolators up to the output rate;
//! 4. optional TPDF dither, input limit, CRFB modulator.
//!
//! DSD64 to PCM: the ported decimator, rounded to 24 bits, as WAV.
//!
//! With threads, every channel runs as a pipeline of two threads, front end and modulator,
//! joined by bounded queues. Every channel's output depends only on its input, and every
//! stage sees its samples in order, so the result does not depend on thread timing.

use crate::filters::{Decimator as OwnDecimator, Interpolator, Resampler, IDLE};
use crate::modulator::{Counters, Modulator};
use crate::resample_table;
use crate::tables;
use dsd2pcm::decimator::{self as sbpcm, Cutoff, PcmRate};
use dsd2pcm::dff::DffWriter;
use dsd2pcm::dsf::DsfWriter;
use dsd2pcm::io::DsdWrite;
use dsd2pcm::wav::{WavFormat, WavWriter};
use dsd2pcm::{open_input, Error, Input, PcmOptions, Result};
use std::fs::File;
use std::io::BufWriter;
use std::path::{Path, PathBuf};

const BASE: u32 = 44_100;
const PCM_RATE: u32 = 8 * BASE;
/// The 48 kHz family's rate change to the 44.1 kHz family: 44100/48000 = 147/160.
const RESAMPLE_UP: u32 = 147;
const RESAMPLE_DOWN: u32 = 160;

/// What to produce.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Output {
    /// DSD at `44.1 kHz x mult`; `mult` is 64 (PCM input only), 128 or 256.
    Dsd {
        /// 64, 128 or 256.
        mult: u32,
    },
    /// 24-bit PCM at the given rate (DSD64 input only).
    Pcm(PcmRate),
}

/// Where the modulator puts its noise-shaping zeros. This release has one band; the type
/// is non-exhaustive so that a later release can add one (docs/design.md, Decisions).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
#[non_exhaustive]
pub enum Band {
    /// Zeros over 0 to 20 kHz (the default).
    #[default]
    Audio,
}

/// Conversion settings.
#[derive(Clone, Copy, Debug)]
pub struct Options {
    /// Output kind and rate.
    pub output: Output,
    /// Modulator order: one of [`accepted_orders`] for the band and output rate (5 to 8;
    /// 5 to 7 for DSD128).
    pub order: usize,
    /// Noise-shaping band of the modulator.
    pub band: Band,
    /// Gain in dB (-120 to +24). DSD output: applied before the modulator; the default,
    /// [`DEFAULT_GAIN_DB`], leaves 6 dB of headroom so that legal input is not limited. A
    /// higher gain is louder and may be limited: [`crate::modulator::Counters`] reports it.
    pub gain_db: f64,
    /// DSD64 decimator. `None` (the default for DSD output): this crate's 140 dB Kaiser
    /// filter (flat to 30 kHz, stop from 70 kHz). `Some(cutoff)`: dsd2pcm's filter, the one
    /// used for PCM output (105 dB stopband; it raises the in-band floor to about -125 dB
    /// SACD, see docs/measurements.md). PCM output always uses dsd2pcm's filter
    /// (`Standard` when `None`).
    pub cutoff: Option<Cutoff>,
    /// Add TPDF dither (+-1 LSB at 24 bits) before the modulator.
    pub dither: bool,
    /// Modulator input limit, as a fraction of 100 % modulation; `None` = the default.
    pub input_limit: Option<f64>,
    /// Process channels on separate threads.
    pub threads: bool,
}

impl Options {
    /// Defaults for an output: order 6 (see [`default_order`]) in the audio band, -6 dB
    /// ([`DEFAULT_GAIN_DB`]) for DSD and 0 dB for PCM, the default input limit and
    /// decimator.
    pub fn new(output: Output) -> Options {
        let gain_db = match output {
            Output::Dsd { .. } => DEFAULT_GAIN_DB,
            Output::Pcm(_) => 0.0,
        };
        Options {
            output,
            order: default_order(output),
            band: Band::Audio,
            gain_db,
            cutoff: None,
            dither: false,
            input_limit: None,
            threads: true,
        }
    }

    /// Checks the settings without converting: the same [`Error::InvalidArgument`] a
    /// conversion would return for them (gain, order, input limit, PCM options). Whether
    /// an input fits (for example DSD64 output needs PCM input) is checked by the
    /// conversion.
    pub fn validate(&self) -> Result<()> {
        match self.output {
            Output::Pcm(rate) => dsd2pcm::convert::check_options(&pcm_options(self, rate)),
            Output::Dsd { .. } => check_dsd(self).map(drop),
        }
    }
}

/// Default modulator order for an output: 6 at every rate (the order is unused for PCM
/// output). With the default band ([`Band::Audio`]) this is the highest order whose loop
/// stayed stable in every hold test of docs/modulator-design.md, including bounded
/// ultrasonic square waves and random steps at the input limit; orders 7 and 8 have lower
/// in-band noise and less of that margin.
pub fn default_order(_output: Output) -> usize {
    6
}

/// The modulator orders accepted for a noise-shaping band and a DSD output rate (`mult`:
/// 64, 128 or 256); empty for any other rate. A combination is accepted only if, at the
/// default input limit, it clipped no modulator state and never reset on any legal signal
/// of the 60 s stability study (docs/modulator-design.md); `tests/stability.rs` runs the
/// same signals on every accepted combination. Anything else is refused with
/// [`Error::InvalidArgument`]. Order 8 at DSD128 is not accepted: it clips its states on a
/// full-scale square at a quarter of the sample rate from 384 kHz PCM.
pub fn accepted_orders(band: Band, mult: u32) -> &'static [usize] {
    match (band, mult) {
        (Band::Audio, 64 | 256) => &[5, 6, 7, 8],
        (Band::Audio, 128) => &[5, 6, 7],
        _ => &[],
    }
}

/// Default modulator input limit (fraction of 100 % modulation): 0.51, that is 0.17 dB
/// above 0 dB SACD. A 1 kHz tone at exactly 0 dB SACD still has 53, 106 and 212 samples
/// limited in 60 s at DSD64, DSD128 and DSD256 (interpolator ripple; below about 0.507 it is
/// itself limited), a 20 kHz tone none (docs/measurements-dsd.md, Hot input). Louder input is
/// hard-limited before the modulator; [`crate::modulator::Counters`] reports it, and
/// `clipped` and `resets` report a modulator overload (none was measured at the defaults,
/// see docs/modulator-design.md).
pub const DEFAULT_INPUT_LIMIT: f64 = 0.51;

/// Default gain for DSD output, in dB: -6, for every input. With [`DEFAULT_INPUT_LIMIT`]
/// it leaves 6.17 dB of headroom above the nominal level, so that legal input is not
/// limited: PCM within full scale whose true peak (the peak of the interpolated waveform)
/// is at most +6 dBTP, and DSD whose waveform after the input filter stays within 100 %
/// modulation, which a tone held at the Super Audio CD peak level of +3.1 dB SACD does
/// with its ultrasonic noise (docs/design.md, Decisions; `tests/stability.rs` asserts it).
/// PCM full scale then sits at -6 dB SACD (25 % modulation). A higher gain is the louder
/// setting: it raises the signal against the modulator's noise by as much, and input
/// above the limit is limited and counted.
pub const DEFAULT_GAIN_DB: f64 = -6.0;

/// Result of one conversion.
#[derive(Clone, Debug, Default)]
pub struct Report {
    /// Input sample rate (Hz).
    pub in_rate: u32,
    /// Output sample rate (Hz).
    pub out_rate: u32,
    /// Input duration in seconds.
    pub seconds: f64,
    /// Output samples per channel.
    pub out_samples: u64,
    /// DSD output: modulator counters per channel.
    pub counters: Vec<Counters>,
    /// PCM output: samples clamped to 24 bits, per channel.
    pub pcm_clipped: Vec<u64>,
    /// DSD output: the mean of the input per channel, as a fraction of full scale (PCM:
    /// +-1.0; DSD: full modulation, so +-1.0 is a constant bit stream). A large value is a
    /// DC offset in the source, which uses up the modulator's headroom and shows up as
    /// limited samples. Measured on the input before the gain; the output does not depend on
    /// it.
    pub input_mean: Vec<f64>,
}

/// Output container, by file extension.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Container {
    /// DSF.
    Dsf,
    /// DSDIFF.
    Dff,
    /// WAV.
    Wav,
}

impl Container {
    /// From a path's extension (case-insensitive).
    pub fn from_path(p: &Path) -> Result<Container> {
        match p
            .extension()
            .and_then(|e| e.to_str())
            .map(str::to_ascii_lowercase)
            .as_deref()
        {
            Some("dsf") => Ok(Container::Dsf),
            Some("dff") => Ok(Container::Dff),
            Some("wav") => Ok(Container::Wav),
            _ => Err(Error::InvalidArgument(
                "output must end in .dsf, .dff or .wav".into(),
            )),
        }
    }
}

fn pcm_options(opts: &Options, rate: PcmRate) -> PcmOptions {
    PcmOptions {
        rate,
        cutoff: opts.cutoff.unwrap_or_default(),
        gain_db: opts.gain_db,
        threads: opts.threads,
        filter: dsd2pcm::Filter::Default,
    }
}

/// Converts `input` to `output` (format by extension).
pub fn convert_file(input: &Path, output: &Path, opts: &Options) -> Result<Report> {
    convert_file_with(input, output, opts, None)
}

/// Output file settings beyond [`Options`].
#[derive(Clone, Debug, Default)]
pub struct FileOutput {
    /// The container; `None`: by the output's extension.
    pub container: Option<Container>,
    /// Tags for DSF output (ID3v2.4, see [`crate::id3::tag`]), replacing any tag carried
    /// over from a DSF input. Not supported for DFF or WAV output.
    pub tags: Vec<(String, String)>,
    /// Refuse to replace an existing output file: the conversion fails with an
    /// [`std::io::ErrorKind::AlreadyExists`] error if the output exists when it starts, and
    /// the finished file is moved to the output's name only if that name is still free
    /// (see [`convert_file_to`]).
    pub no_overwrite: bool,
}

/// [`convert_file_with`] with explicit [`FileOutput`] settings.
///
/// Every file conversion writes to a new temporary file next to the output, named
/// `NAME.partN.EXT` (`N` counts up from 1 to the first free name), flushes it to disk and
/// renames it to the output's name only when the conversion succeeds. After an error, a
/// cancel or a panic the temporary file is removed: no partial output is ever left under
/// the output's name, and an existing output is replaced only by a complete one. A process
/// that is killed outright can leave the temporary file behind.
///
/// With [`FileOutput::no_overwrite`], the finished file is hard-linked to the output's
/// name, which fails if a file of that name appeared during the conversion (no race). On
/// file systems without hard links (FAT, exFAT, some network shares) the name is claimed
/// with an exclusive create and then replaced by a rename.
pub fn convert_file_to(
    input: &Path,
    output: &Path,
    opts: &Options,
    file: &FileOutput,
    progress: Option<Progress<'_>>,
) -> Result<Report> {
    convert_file_impl(input, output, opts, file, progress)
}

/// [`convert_file`] with a progress callback (see [`Progress`]), which can cancel; it is
/// called after every chunk for DSD output and every block for PCM output.
pub fn convert_file_with(
    input: &Path,
    output: &Path,
    opts: &Options,
    progress: Option<Progress<'_>>,
) -> Result<Report> {
    convert_file_impl(input, output, opts, &FileOutput::default(), progress)
}

fn convert_file_impl(
    input: &Path,
    output: &Path,
    opts: &Options,
    file: &FileOutput,
    progress: Option<Progress<'_>>,
) -> Result<Report> {
    let container = match file.container {
        Some(c) => c,
        None => Container::from_path(output)?,
    };
    if !file.tags.is_empty() && container != Container::Dsf {
        return Err(Error::Unsupported(
            "tags are written to DSF output only".into(),
        ));
    }
    let new_tag = if file.tags.is_empty() {
        None
    } else {
        Some(crate::id3::tag(&file.tags)?)
    };
    match (container, opts.output) {
        (Container::Wav, Output::Dsd { .. }) => {
            return Err(Error::InvalidArgument(
                "DSD output needs a .dsf or .dff file".into(),
            ))
        }
        (Container::Dsf | Container::Dff, Output::Pcm(_)) => {
            return Err(Error::InvalidArgument(
                "PCM output needs a .wav file".into(),
            ))
        }
        _ => {}
    }
    opts.validate()?;
    // Refuse an output that is the input (same path, symlink or hard link), before
    // anything is written.
    if same_file(input, output) {
        return Err(Error::InvalidArgument(format!(
            "output {} is the input file",
            output.display()
        )));
    }
    let inp = open_input(input)?;
    check_declared_length(input, &inp)?;
    if file.no_overwrite && output.symlink_metadata().is_ok() {
        return Err(Error::Io(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            format!("{} exists", output.display()),
        )));
    }
    let (temp, file_out) = TempOutput::create(output)?;
    let sync = file_out.try_clone()?;
    let out = BufWriter::with_capacity(1 << 20, file_out);
    // Every writer is finished and dropped (flushed) before the file is synced.
    let report = write_output(inp, out, opts, container, new_tag, progress)?;
    sync.sync_all()?;
    drop(sync);
    temp.commit(output, file.no_overwrite)?;
    Ok(report)
}

/// Refuses a DSF file whose header declares no samples while its data chunk holds audio
/// (more than one block per channel, the most a writer pads an empty file to). The reader
/// trusts the header, so such a file would convert to an empty output; the header is
/// damaged, and the data's real length is unknown.
fn check_declared_length(path: &Path, inp: &Input) -> Result<()> {
    let Input::Dsd(r) = inp else {
        return Ok(());
    };
    if r.info().samples > 0 {
        return Ok(());
    }
    let Some((data, block)) = dsf_data_len(path)? else {
        return Ok(());
    };
    let channels = u64::from(r.info().channels);
    if data > block * channels {
        return Err(Error::Format(format!(
            "the DSF header declares 0 samples per channel, but its data chunk holds {data} bytes \
             ({channels} channels); the header is damaged, so nothing was converted"
        )));
    }
    Ok(())
}

/// A DSF file's data chunk length (without its 12-byte header) and block size per channel,
/// read from the file's headers; `None` if it is not a DSF file.
fn dsf_data_len(path: &Path) -> Result<Option<(u64, u64)>> {
    use std::io::{Read, Seek, SeekFrom};
    let le64 = |b: &[u8]| u64::from_le_bytes(b.try_into().expect("8 bytes"));
    let mut f = File::open(path)?;
    let mut h = [0u8; 92];
    if f.read_exact(&mut h).is_err() || &h[..4] != b"DSD " || &h[28..32] != b"fmt " {
        return Ok(None);
    }
    let fmt_size = le64(&h[32..40]);
    let block = u64::from(u32::from_le_bytes(h[72..76].try_into().expect("4 bytes")));
    // The reader bounded fmt_size on its own open, but the file may have changed since:
    // an offset past u64 is a damaged header, not a wrap or a panic.
    let Some(data_at) = 28u64.checked_add(fmt_size) else {
        return Err(Error::Format(format!(
            "the DSF fmt chunk size {fmt_size} is out of range; the header is damaged, \
             so nothing was converted"
        )));
    };
    let mut d = [0u8; 12];
    f.seek(SeekFrom::Start(data_at))?;
    if f.read_exact(&mut d).is_err() || &d[..4] != b"data" {
        return Ok(None);
    }
    Ok(Some((le64(&d[4..12]).saturating_sub(12), block)))
}

fn write_output(
    inp: Input,
    out: BufWriter<File>,
    opts: &Options,
    container: Container,
    new_tag: Option<Vec<u8>>,
    mut progress: Option<Progress<'_>>,
) -> Result<Report> {
    match opts.output {
        Output::Pcm(rate) => {
            let Input::Dsd(r) = inp else {
                return Err(Error::Unsupported("PCM output needs DSD input".into()));
            };
            let info = r.info();
            let mut w = WavWriter::new(out, WavFormat::I24, info.channels, rate.hz())?;
            let pcm_opts = pcm_options(opts, rate);
            let mut hook = |p: dsd2pcm::convert::Progress| {
                if let Some(f) = progress.as_mut() {
                    if !f(p.done, p.total) {
                        return std::ops::ControlFlow::Break(());
                    }
                }
                std::ops::ControlFlow::Continue(())
            };
            let rep = dsd2pcm::convert::dsd64_to_pcm_with(r, &mut w, &pcm_opts, &mut hook)?;
            w.finish()?;
            Ok(Report {
                in_rate: rep.in_rate,
                out_rate: rep.out_rate,
                seconds: rep.seconds,
                out_samples: rep.out_samples,
                counters: Vec::new(),
                pcm_clipped: rep.clipped,
                input_mean: Vec::new(),
            })
        }
        Output::Dsd { mult } => {
            let (channels, ctype, meta) = match &inp {
                Input::Dsd(r) => (
                    r.info().channels,
                    r.channel_type(),
                    new_tag.or_else(|| r.metadata().map(<[u8]>::to_vec)),
                ),
                Input::Pcm(r) => (r.info().channels, None, new_tag),
            };
            let rate = BASE * mult;
            let mut sink: Box<dyn DsdWrite> = match container {
                Container::Dsf => {
                    let mut w = DsfWriter::new(out, channels, rate, ctype)?;
                    w.set_metadata(meta);
                    Box::new(w)
                }
                _ => Box::new(DffWriter::new(out, channels, rate)?),
            };
            convert_with(inp, sink.as_mut(), opts, progress)
        }
    }
}

/// Most `.partN` names tried for the temporary output.
const MAX_TEMP_NAMES: u32 = 10_000;

/// The temporary file a conversion writes; removed on drop unless committed.
struct TempOutput {
    path: PathBuf,
    keep: bool,
}

/// `dir/NAME.partN.EXT` for `dir/NAME.EXT` (`dir/NAME.partN` without an extension).
fn temp_name(output: &Path, n: u32) -> PathBuf {
    let mut name = match output.extension() {
        Some(_) => output.file_stem().unwrap_or_default().to_os_string(),
        None => output.file_name().unwrap_or_default().to_os_string(),
    };
    name.push(format!(".part{n}"));
    if let Some(ext) = output.extension() {
        name.push(".");
        name.push(ext);
    }
    output.with_file_name(name)
}

impl TempOutput {
    /// Creates the first free `NAME.partN.EXT` next to `output` (exclusive create, so it
    /// never opens a file that exists).
    fn create(output: &Path) -> Result<(TempOutput, File)> {
        if output.file_name().is_none() {
            return Err(Error::InvalidArgument(format!(
                "output {} is not a file name",
                output.display()
            )));
        }
        for n in 1..=MAX_TEMP_NAMES {
            let path = temp_name(output, n);
            match File::create_new(&path) {
                Ok(f) => return Ok((TempOutput { path, keep: false }, f)),
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(e) => return Err(e.into()),
            }
        }
        Err(Error::Io(std::io::Error::other(format!(
            "no free temporary name next to {}",
            output.display()
        ))))
    }

    /// Moves the finished file to `output`: a rename that replaces any existing file, or,
    /// with `no_overwrite`, a link that fails if `output` exists.
    fn commit(mut self, output: &Path, no_overwrite: bool) -> Result<()> {
        if no_overwrite {
            match std::fs::hard_link(&self.path, output) {
                // The temporary name is removed on drop.
                Ok(()) => {}
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => return Err(e.into()),
                Err(_) => {
                    claim_then_rename(&self.path, output)?;
                    self.keep = true;
                }
            }
        } else {
            std::fs::rename(&self.path, output)?;
            self.keep = true;
        }
        sync_dir(output);
        Ok(())
    }
}

/// Moves `tmp` to `output` only if `output` does not exist, without hard links: claims the
/// name with an exclusive create (which fails if it exists), then renames over the empty
/// claim. Another process could replace the claim between the two steps; the rename then
/// replaces that file, which is the closest a portable program gets.
fn claim_then_rename(tmp: &Path, output: &Path) -> std::io::Result<()> {
    drop(File::create_new(output)?);
    if let Err(e) = std::fs::rename(tmp, output) {
        // Remove the claim, unless someone replaced it meanwhile.
        if output
            .symlink_metadata()
            .is_ok_and(|m| m.is_file() && m.len() == 0)
        {
            let _ = std::fs::remove_file(output);
        }
        return Err(e);
    }
    Ok(())
}

impl Drop for TempOutput {
    fn drop(&mut self) {
        if !self.keep {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

/// Makes a rename in `file`'s directory durable where the platform allows (best effort).
fn sync_dir(file: &Path) {
    #[cfg(unix)]
    {
        let dir = match file.parent() {
            Some(d) if !d.as_os_str().is_empty() => d,
            _ => Path::new("."),
        };
        if let Ok(d) = File::open(dir) {
            let _ = d.sync_all();
        }
    }
    #[cfg(not(unix))]
    let _ = file;
}

/// Whether `a` and `b` name the same existing file: the same path, a symlink to it or a
/// hard link to it (device and inode on Unix, volume serial number and file index on
/// Windows, through the `same-file` crate). `false` if either does not exist.
pub(crate) fn same_file(a: &Path, b: &Path) -> bool {
    same_file::is_same_file(a, b).unwrap_or(false)
}

fn check_common(opts: &Options) -> Result<f64> {
    if !opts.gain_db.is_finite() || !(-120.0..=24.0).contains(&opts.gain_db) {
        return Err(Error::InvalidArgument(format!(
            "gain {} dB is outside -120 to +24 dB",
            opts.gain_db
        )));
    }
    Ok(sbpcm::db_to_linear(opts.gain_db))
}

/// Validates DSD-output options: returns the gain factor, modulator table and input limit.
fn check_dsd(opts: &Options) -> Result<(f64, u32, &'static crate::filters::ModTable, f64)> {
    let gain = check_common(opts)?;
    let Output::Dsd { mult } = opts.output else {
        return Err(Error::InvalidArgument("not a DSD output".into()));
    };
    if !matches!(mult, 64 | 128 | 256) {
        return Err(Error::InvalidArgument(format!(
            "DSD output rate DSD{mult}: 64 (from PCM), 128 or 256 are supported"
        )));
    }
    let accepted = accepted_orders(opts.band, mult);
    if !accepted.contains(&opts.order) {
        let list: Vec<String> = accepted.iter().map(|o| o.to_string()).collect();
        return Err(Error::InvalidArgument(format!(
            "modulator order {}: DSD{mult} output accepts {}",
            opts.order,
            list.join(", ")
        )));
    }
    let limit = opts.input_limit.unwrap_or(DEFAULT_INPUT_LIMIT);
    if !(limit > 0.0 && limit <= 1.0) {
        return Err(Error::InvalidArgument(
            "input limit must be in (0, 1]".into(),
        ));
    }
    // The earlier wide-band tables stay in tables.rs for the reference-vector test only.
    let table = tables::modulator(mult, opts.order, false)
        .ok_or_else(|| Error::InvalidArgument("no modulator table".into()))?;
    Ok((gain, mult, table, limit))
}

/// SplitMix64 (Steele, Lea & Flood 2014): a small deterministic generator for dither.
#[derive(Clone, Debug)]
struct SplitMix(u64);

impl SplitMix {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform in [0, 1), exact.
    fn unit(&mut self) -> f64 {
        (self.next() >> 11) as f64 * (1.0 / 9_007_199_254_740_992.0)
    }
}

/// TPDF dither amplitude: one 24-bit LSB of full scale.
const DITHER_LSB: f64 = 1.0 / 8_388_608.0;

/// Builds one channel's front end and the scale applied to its output.
type FrontMaker = Box<dyn Fn() -> Result<(Front, f64)>>;

enum Front {
    Sb(Box<sbpcm::Decimator>),
    Own(OwnDecimator),
    Pcm,
    Resample(Box<Resampler>),
}

/// Packs bits MSB-first after dropping `skip` bits, up to `left` bits.
pub(crate) struct Packer {
    pub(crate) skip: u64,
    pub(crate) left: u64,
    /// Bits taken after the skip.
    pub(crate) taken: u64,
    pub(crate) acc: u8,
    pub(crate) nacc: u8,
    pub(crate) out: Vec<u8>,
}

impl Packer {
    #[inline(always)]
    fn put(&mut self, bit: bool) {
        if self.skip > 0 {
            self.skip -= 1;
            return;
        }
        if self.left == 0 {
            return;
        }
        self.left -= 1;
        self.taken += 1;
        self.acc = (self.acc << 1) | u8::from(bit);
        self.nacc += 1;
        if self.nacc == 8 {
            self.out.push(self.acc);
            self.acc = 0;
            self.nacc = 0;
        }
    }
    pub(crate) fn done(&self) -> bool {
        self.skip == 0 && self.left == 0
    }
    fn flush_partial(&mut self) {
        if self.nacc > 0 {
            // The bits past the last sample are padding. Fill them with the idle pattern
            // (0x69's bits), not zeros: DFF carries no bit count, so a reader plays them,
            // and a run of zeros is a full-scale negative step.
            self.out
                .push((self.acc << (8 - self.nacc)) | (0x69 & (0xFF >> self.nacc)));
            self.acc = 0;
            self.nacc = 0;
        }
    }
}

/// One channel's front end, gain, interpolators and dither.
pub(crate) struct FrontStage {
    front: Front,
    scale: f64,
    interps: Vec<Interpolator>,
    dither: Option<SplitMix>,
    front_out: Vec<f64>,
    a: Vec<f64>,
    b: Vec<f64>,
}

/// One channel's modulator and bit packer.
pub(crate) struct ModStage {
    pub(crate) modulator: Modulator,
    pub(crate) packer: Packer,
    pub(crate) flushed: bool,
}

/// An input chunk of one channel.
pub(crate) enum Chunk {
    Dsd(Vec<u8>),
    Pcm(Vec<f64>),
}

impl FrontStage {
    /// Runs the chunk through the front end and passes the modulator input to `sink` in
    /// blocks of at most `BLOCK` front-end samples, so that every stage's buffer stays in
    /// cache; each stage is a stream, so the blocking does not change the output.
    pub(crate) fn process(&mut self, input: &Chunk, sink: &mut impl FnMut(&[f64])) {
        self.front_out.clear();
        match (&mut self.front, input) {
            (Front::Sb(d), Chunk::Dsd(x)) => d.push(x, &mut self.front_out),
            (Front::Own(d), Chunk::Dsd(x)) => d.push(x, &mut self.front_out),
            (Front::Pcm, Chunk::Pcm(x)) => self.front_out.extend_from_slice(x),
            (Front::Resample(r), Chunk::Pcm(x)) => r.process(x, &mut self.front_out),
            _ => {}
        }
        let s = self.scale;
        for blk in self.front_out.chunks(BLOCK) {
            self.a.clear();
            self.a.extend(blk.iter().map(|v| v * s));
            for it in &mut self.interps {
                self.b.clear();
                it.process(&self.a, &mut self.b);
                std::mem::swap(&mut self.a, &mut self.b);
            }
            if let Some(rng) = &mut self.dither {
                for v in &mut self.a {
                    let d = (rng.unit() - rng.unit()) * DITHER_LSB;
                    *v += d;
                }
            }
            sink(&self.a);
        }
    }
}

impl ModStage {
    pub(crate) fn process(&mut self, u: &[f64]) {
        let p = &mut self.packer;
        self.modulator.run(u, &mut |bit| p.put(bit));
    }

    /// Ends a chunk: flushes the last partial byte once the output is complete, and
    /// returns the chunk's bytes and whether the output is complete.
    pub(crate) fn end_chunk(&mut self) -> (Vec<u8>, bool) {
        let done = self.packer.done();
        if done && !self.flushed {
            self.packer.flush_partial();
            self.flushed = true;
        }
        (std::mem::take(&mut self.packer.out), done)
    }
}

/// Front-end samples per block through the interpolators and the modulator.
const BLOCK: usize = 1024;

fn interp_table(out_rate: u32) -> Option<&'static crate::filters::InterpTable> {
    Some(match out_rate {
        176_400 => &tables::HB_176400,
        352_800 => &tables::HB_352800,
        705_600 => &tables::HB_705600,
        1_411_200 => &tables::HB_1411200,
        2_822_400 => &tables::HB_2822400,
        5_644_800 => &tables::HB_5644800,
        11_289_600 => &tables::HB_11289600,
        _ => return None,
    })
}

/// The format of an input stream.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputFormat {
    /// DSD, MSB-first bytes per channel, at `rate` Hz (DSD64, DSD128 or DSD256).
    Dsd {
        /// Sample rate in Hz.
        rate: u32,
    },
    /// PCM, `f64` samples with full scale at +-1.0, at `rate` Hz: 44.1, 88.2, 176.4 or
    /// 352.8 kHz, or 48, 96, 192 or 384 kHz (resampled by 147/160 to the 44.1 kHz family
    /// first).
    Pcm {
        /// Sample rate in Hz.
        rate: u32,
    },
}

impl InputFormat {
    /// The sample rate in Hz.
    pub fn rate(self) -> u32 {
        match self {
            InputFormat::Dsd { rate } | InputFormat::Pcm { rate } => rate,
        }
    }
}

/// The per-channel stages of one conversion, before the output length is known.
pub(crate) struct Built {
    pub fronts: Vec<FrontStage>,
    pub mods: Vec<ModStage>,
    pub fout: u32,
    /// PCM frames per input chunk (and per idle chunk at the end).
    pub pcm_chunk: usize,
}

/// Validates the settings and builds the stages for `channels` channels of `fmt`.
pub(crate) fn build(fmt: InputFormat, channels: u16, opts: &Options) -> Result<Built> {
    let (gain, mult, table, limit) = check_dsd(opts)?;
    let fout = BASE * mult;
    if mult == 64 && matches!(fmt, InputFormat::Dsd { .. }) {
        return Err(Error::Unsupported(
            "DSD64 output is for PCM input (DSD input is already DSD64 or higher)".into(),
        ));
    }
    if !(1..=MAX_CHANNELS).contains(&channels) {
        return Err(Error::Unsupported(format!(
            "{channels} channels (1 to {MAX_CHANNELS} are supported)"
        )));
    }
    // front end, first PCM rates, and the front end's delay in samples at its output rate
    let (mk_front, first_rates, front_delay): (FrontMaker, &[u32], (u64, u32)) = match fmt {
        InputFormat::Dsd { rate } => {
            let cut = opts.cutoff;
            let mk: FrontMaker = match rate {
                r if r == 64 * BASE => match cut {
                    Some(cut) => Box::new(move || {
                        Ok((
                            Front::Sb(Box::new(sbpcm::Decimator::new(PcmRate::Hz352800, cut)?)),
                            sbpcm::GRID_TO_UNIT * gain,
                        ))
                    }),
                    None => Box::new(move || {
                        Ok((Front::Own(OwnDecimator::new(&tables::DECIM_DSD64)), gain))
                    }),
                },
                r if r == 128 * BASE => Box::new(move || {
                    Ok((Front::Own(OwnDecimator::new(&tables::DECIM_DSD128)), gain))
                }),
                r if r == 256 * BASE => Box::new(move || {
                    Ok((Front::Own(OwnDecimator::new(&tables::DECIM_DSD256)), gain))
                }),
                _ => {
                    return Err(Error::Unsupported(format!(
                        "DSD input at {rate} Hz (DSD64, DSD128 and DSD256 of 44.1 kHz so far)"
                    )))
                }
            };
            (mk, &[], (0, PCM_RATE))
        }
        InputFormat::Pcm { rate } => {
            // the 48 kHz family is resampled to the 44.1 kHz-family rate below it
            let (base, resample) = match rate {
                48_000 | 96_000 | 192_000 | 384_000 => (rate / RESAMPLE_DOWN * RESAMPLE_UP, true),
                _ => (rate, false),
            };
            let steep: &[u32] = match base {
                44_100 => &[88_200, 176_400, 352_800],
                88_200 => &[176_400, 352_800],
                176_400 => &[352_800],
                352_800 => &[],
                other => {
                    return Err(Error::Unsupported(format!(
                        "PCM input at {other} Hz (44.1, 88.2, 176.4, 352.8, 48, 96, 192 or 384 \
                         kHz are supported)"
                    )))
                }
            };
            if resample {
                let t = &resample_table::RESAMPLE_147;
                let d = Resampler::delay(t, RESAMPLE_DOWN as usize) as u64;
                let mk: FrontMaker = Box::new(move || {
                    Ok((
                        Front::Resample(Box::new(Resampler::new(t, RESAMPLE_DOWN as usize))),
                        0.5 * gain,
                    ))
                });
                (mk, steep, (d, base))
            } else {
                (
                    Box::new(move || Ok((Front::Pcm, 0.5 * gain))),
                    steep,
                    (0, base),
                )
            }
        }
    };
    // interpolator plan: PCM-input stages (first one steep), then half-bands to fout
    let mut plan: Vec<&'static crate::filters::InterpTable> = Vec::new();
    for (k, &r) in first_rates.iter().enumerate() {
        plan.push(if k == 0 {
            match r {
                88_200 => &tables::STEEP_44100,
                176_400 => &tables::STEEP_88200,
                _ => &tables::STEEP_176400,
            }
        } else {
            interp_table(r).ok_or_else(|| Error::InvalidArgument("rate plan".into()))?
        });
    }
    let mut r = PCM_RATE * 2;
    while r <= fout {
        plan.push(interp_table(r).ok_or_else(|| Error::InvalidArgument("rate plan".into()))?);
        r *= 2;
    }
    let delay: u64 = plan
        .iter()
        .map(|t| t.delay as u64 * u64::from(fout / t.out_rate))
        .sum::<u64>()
        + front_delay.0 * u64::from(fout / front_delay.1);
    let ch = usize::from(channels);
    let mut fronts = Vec::with_capacity(ch);
    let mut mods = Vec::with_capacity(ch);
    for c in 0..ch {
        let (front, scale) = mk_front()?;
        fronts.push(FrontStage {
            front,
            scale,
            interps: plan.iter().map(|t| Interpolator::new(t)).collect(),
            dither: opts
                .dither
                .then_some(SplitMix(0x5EED_0000_0000_0000 ^ c as u64)),
            front_out: Vec::new(),
            a: Vec::new(),
            b: Vec::new(),
        });
        mods.push(ModStage {
            modulator: Modulator::new(table, limit),
            packer: Packer {
                skip: delay,
                left: u64::MAX,
                taken: 0,
                acc: 0,
                nacc: 0,
                out: Vec::new(),
            },
            flushed: false,
        });
    }
    Ok(Built {
        fronts,
        mods,
        fout,
        pcm_chunk: (fmt.rate() / 16).max(1024) as usize,
    })
}

/// Output samples for `n_in` input samples at `in_rate`.
pub(crate) fn output_len(n_in: u64, in_rate: u32, fout: u32) -> Result<u64> {
    u64::try_from(u128::from(n_in) * u128::from(fout) / u128::from(in_rate))
        .map_err(|_| Error::Unsupported("input too long".into()))
}

/// Progress of a conversion: called with output samples done and the total per channel;
/// returning `false` cancels the conversion, which then ends with [`cancelled`].
pub type Progress<'a> = &'a mut dyn FnMut(u64, u64) -> bool;

/// The error a cancelled conversion returns (see [`is_cancelled`]).
pub fn cancelled() -> Error {
    Error::Cancelled
}

/// Whether `e` is the error of a cancelled conversion.
pub fn is_cancelled(e: &Error) -> bool {
    matches!(e, Error::Cancelled)
}

/// Converts any supported input to DSD64 (from PCM), DSD128 or DSD256 into `sink` (which
/// is finished).
///
/// A source that ends before the length it declares is an error, at its end: the output
/// never extends past what the source delivered.
pub fn convert(input: Input, sink: &mut dyn DsdWrite, opts: &Options) -> Result<Report> {
    convert_with(input, sink, opts, None)
}

/// [`convert`] with a progress callback that can cancel.
pub fn convert_with(
    input: Input,
    sink: &mut dyn DsdWrite,
    opts: &Options,
    progress: Option<Progress<'_>>,
) -> Result<Report> {
    let (fmt, channels, n_in) = match &input {
        Input::Dsd(r) => {
            let i = r.info();
            (
                InputFormat::Dsd {
                    rate: i.sample_rate,
                },
                i.channels,
                i.samples,
            )
        }
        Input::Pcm(r) => {
            let i = r.info();
            (
                InputFormat::Pcm {
                    rate: i.sample_rate,
                },
                i.channels,
                i.frames,
            )
        }
    };
    let Built {
        fronts,
        mut mods,
        fout,
        pcm_chunk,
    } = build(fmt, channels, opts)?;
    let in_rate = fmt.rate();
    let n_out = output_len(n_in, in_rate, fout)?;
    for m in &mut mods {
        m.packer.left = n_out;
    }
    let mut reader = ChunkReader {
        input,
        ch: usize::from(channels),
        eof: false,
        pcm_chunk,
        flushes: 0,
        declared: n_in,
        mean: Mean::new(usize::from(channels)),
    };
    let mut tick = Tick {
        progress,
        done: 0,
        total: n_out,
    };
    let counters = if opts.threads {
        run_pipelined(&mut reader, fronts, mods, sink, &mut tick)?
    } else {
        run_serial(&mut reader, fronts, mods, sink, &mut tick)?
    };
    sink.finish(n_out)?;
    Ok(Report {
        in_rate,
        out_rate: fout,
        seconds: n_in as f64 / f64::from(in_rate),
        out_samples: n_out,
        counters,
        pcm_clipped: Vec::new(),
        input_mean: reader.mean.get(),
    })
}

/// Progress reporting after each written chunk.
struct Tick<'a> {
    progress: Option<Progress<'a>>,
    done: u64,
    total: u64,
}

impl Tick<'_> {
    /// Records `bytes` written per channel; an error if the caller cancels.
    fn written(&mut self, bytes: usize) -> Result<()> {
        self.done = (self.done + 8 * bytes as u64).min(self.total);
        if let Some(p) = &mut self.progress {
            if !p(self.done, self.total) {
                return Err(cancelled());
            }
        }
        Ok(())
    }
}

/// Most channels per stream (Super Audio CD and DSF allow 6).
const MAX_CHANNELS: u16 = 6;

/// Idle chunks fed after the end of the input before giving up (2 are needed at most).
const MAX_FLUSHES: u64 = 64;

/// The mean of the input per channel ([`Report::input_mean`]), over the input only (not the
/// idle chunks after its end).
struct Mean {
    /// PCM: the sum of the samples. DSD: ones minus zeros.
    sum: Vec<f64>,
    /// Samples per channel.
    n: u64,
}

impl Mean {
    fn new(ch: usize) -> Mean {
        Mean {
            sum: vec![0.0; ch],
            n: 0,
        }
    }

    /// DSD bytes: each bit is +1 or -1, so a byte adds 2 x its ones minus 8.
    fn dsd(&mut self, bufs: &[Vec<u8>], got: usize) {
        for (s, b) in self.sum.iter_mut().zip(bufs) {
            let ones: u64 = b[..got].iter().map(|x| u64::from(x.count_ones())).sum();
            *s += 2.0 * ones as f64 - 8.0 * got as f64;
        }
        self.n += 8 * got as u64;
    }

    fn pcm(&mut self, bufs: &[Vec<f64>], got: usize) {
        for (s, b) in self.sum.iter_mut().zip(bufs) {
            *s += b[..got].iter().sum::<f64>();
        }
        self.n += got as u64;
    }

    fn get(&self) -> Vec<f64> {
        let n = self.n.max(1) as f64;
        self.sum.iter().map(|s| s / n).collect()
    }
}

/// Refuses a read that did not append exactly `got` samples to every channel (a custom
/// source breaking the reader contract): the stages and the sink need equal lengths.
fn same_lengths(lens: impl Iterator<Item = usize>, got: usize) -> Result<()> {
    for (c, n) in lens.enumerate() {
        if n != got {
            return Err(Error::Format(format!(
                "the source returned {got} samples per channel but gave channel {c} {n}"
            )));
        }
    }
    Ok(())
}

/// Reads input chunks, then idle chunks after the end of the input.
struct ChunkReader {
    input: Input,
    ch: usize,
    eof: bool,
    pcm_chunk: usize,
    flushes: u64,
    /// Samples per channel the source declared (DSD: bits; PCM: frames).
    declared: u64,
    mean: Mean,
}

impl ChunkReader {
    /// Refuses a source that ends before the length it declared, at its end and before any
    /// idle chunk: the output is bounded by the samples the source delivered, never by the
    /// length it claims (a few bytes declaring hours of audio would otherwise be converted
    /// as silence, up to [`MAX_FLUSHES`] idle chunks of it).
    fn check_end(&self) -> Result<()> {
        if self.mean.n < self.declared {
            return Err(Error::Format(format!(
                "input ended after {} of {} samples per channel it declared",
                self.mean.n, self.declared
            )));
        }
        Ok(())
    }

    /// The next chunk of every channel.
    fn next(&mut self) -> Result<Vec<Chunk>> {
        if self.eof {
            self.flushes += 1;
            // A few idle chunks cover every filter's delay. A source that delivered less
            // than it declared is refused before the first one (`check_end`); this limit is
            // a backstop, so the output can never grow with silence.
            if self.flushes > MAX_FLUSHES {
                return Err(Error::Format(
                    "input ended before its declared length".into(),
                ));
            }
        }
        match &mut self.input {
            Input::Dsd(rd) => {
                let mut bufs = vec![Vec::<u8>::new(); self.ch];
                let got = if self.eof {
                    0
                } else {
                    rd.read_bytes(32_768, &mut bufs)?
                };
                same_lengths(bufs.iter().map(Vec::len), got)?;
                if got == 0 {
                    if !self.eof {
                        self.check_end()?;
                    }
                    self.eof = true;
                    for b in &mut bufs {
                        b.resize(8192, IDLE);
                    }
                } else {
                    self.mean.dsd(&bufs, got);
                }
                Ok(bufs.into_iter().map(Chunk::Dsd).collect())
            }
            Input::Pcm(rd) => {
                let mut bufs = vec![Vec::<f64>::new(); self.ch];
                let got = if self.eof {
                    0
                } else {
                    rd.read_frames(self.pcm_chunk, &mut bufs)?
                };
                same_lengths(bufs.iter().map(Vec::len), got)?;
                if got == 0 {
                    if !self.eof {
                        self.check_end()?;
                    }
                    self.eof = true;
                    for b in &mut bufs {
                        b.resize(self.pcm_chunk, 0.0);
                    }
                } else {
                    self.mean.pcm(&bufs, got);
                }
                Ok(bufs.into_iter().map(Chunk::Pcm).collect())
            }
        }
    }
}

/// Everything on the calling thread.
fn run_serial(
    reader: &mut ChunkReader,
    mut fronts: Vec<FrontStage>,
    mut mods: Vec<ModStage>,
    sink: &mut dyn DsdWrite,
    tick: &mut Tick<'_>,
) -> Result<Vec<Counters>> {
    loop {
        let chunks = reader.next()?;
        let mut out = Vec::with_capacity(chunks.len());
        let mut done = false;
        for ((f, m), x) in fronts.iter_mut().zip(mods.iter_mut()).zip(&chunks) {
            f.process(x, &mut |u| m.process(u));
            let (bytes, d) = m.end_chunk();
            out.push(bytes);
            done = d;
        }
        if !out[0].is_empty() {
            sink.write_bytes(&out)?;
            tick.written(out[0].len())?;
        }
        if done {
            return Ok(mods.iter().map(|m| m.modulator.counters).collect());
        }
    }
}

/// Chunks in flight between reading and writing.
const LAG: usize = 3;

/// Front-end to modulator messages.
enum Block {
    Samples(Vec<f64>),
    EndChunk,
}

/// Two threads per channel: front end (decimator, interpolators, dither) and modulator,
/// joined by bounded queues; the calling thread reads and writes, `LAG` chunks behind.
/// Each stage sees the same samples in the same order as in [`run_serial`], so the output
/// is the same.
fn run_pipelined(
    reader: &mut ChunkReader,
    fronts: Vec<FrontStage>,
    mods: Vec<ModStage>,
    sink: &mut dyn DsdWrite,
    tick: &mut Tick<'_>,
) -> Result<Vec<Counters>> {
    use std::sync::mpsc::{sync_channel, Receiver, SyncSender};
    std::thread::scope(|s| {
        let mut to_front: Vec<SyncSender<Chunk>> = Vec::new();
        let mut from_mod: Vec<Receiver<(Vec<u8>, bool)>> = Vec::new();
        let mut handles = Vec::new();
        for (mut f, mut m) in fronts.into_iter().zip(mods) {
            let (tx_in, rx_in) = sync_channel::<Chunk>(LAG + 1);
            let (tx_blk, rx_blk) = sync_channel::<Block>(64);
            let (tx_free, rx_free) = sync_channel::<Vec<f64>>(64);
            let (tx_out, rx_out) = sync_channel::<(Vec<u8>, bool)>(LAG + 1);
            s.spawn(move || {
                for x in rx_in {
                    let mut ok = true;
                    f.process(&x, &mut |u| {
                        let mut v = rx_free.try_recv().unwrap_or_default();
                        v.clear();
                        v.extend_from_slice(u);
                        ok &= tx_blk.send(Block::Samples(v)).is_ok();
                    });
                    if !ok || tx_blk.send(Block::EndChunk).is_err() {
                        break;
                    }
                }
            });
            handles.push(s.spawn(move || {
                for b in rx_blk {
                    match b {
                        Block::Samples(v) => {
                            m.process(&v);
                            let _ = tx_free.try_send(v);
                        }
                        Block::EndChunk => {
                            if tx_out.send(m.end_chunk()).is_err() {
                                break;
                            }
                        }
                    }
                }
                m.modulator.counters
            }));
            to_front.push(tx_in);
            from_mod.push(rx_out);
        }
        let result = (|| -> Result<()> {
            let mut in_flight = 0usize;
            loop {
                if in_flight <= LAG {
                    for (tx, x) in to_front.iter().zip(reader.next()?) {
                        tx.send(x)
                            .map_err(|_| Error::InvalidArgument("worker stopped".into()))?;
                    }
                    in_flight += 1;
                    continue;
                }
                let mut out = Vec::with_capacity(from_mod.len());
                let mut done = false;
                for rx in &from_mod {
                    let (bytes, d) = rx
                        .recv()
                        .map_err(|_| Error::InvalidArgument("worker stopped".into()))?;
                    out.push(bytes);
                    done = d;
                }
                in_flight -= 1;
                if !out[0].is_empty() {
                    sink.write_bytes(&out)?;
                    tick.written(out[0].len())?;
                }
                if done {
                    return Ok(());
                }
            }
        })();
        // Closing the queues ends the workers.
        drop(to_front);
        drop(from_mod);
        let counters: Vec<Counters> = handles
            .into_iter()
            .map(|h| h.join().expect("modulator thread panicked"))
            .collect();
        result.map(|()| counters)
    })
}

#[cfg(test)]
mod file_tests {
    #[test]
    fn partial_last_byte_is_padded_with_idle_bits() {
        let mut p = Packer {
            skip: 0,
            left: 3,
            taken: 0,
            acc: 0,
            nacc: 0,
            out: Vec::new(),
        };
        for b in [true, false, true] {
            p.put(b);
        }
        p.flush_partial();
        // three sample bits 101, then the low five bits of 0x69 (0b0110_1001 -> 0_1001)
        assert_eq!(p.out, vec![0b1010_1001]);
    }

    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("dsdup-unit-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn temp_names() {
        assert_eq!(
            temp_name(Path::new("a/song.dsf"), 3),
            Path::new("a/song.part3.dsf")
        );
        assert_eq!(temp_name(Path::new("song"), 1), Path::new("song.part1"));
        assert_eq!(
            temp_name(Path::new("x.y.wav"), 12),
            Path::new("x.y.part12.wav")
        );
    }

    /// Same path, symlink and hard link are the same file; a copy and a missing path are
    /// not. (On Windows the `same-file` crate compares volume and file index; checked on
    /// the Windows VM, not here.)
    #[cfg(unix)]
    #[test]
    fn same_file_sees_links() {
        let d = scratch("same");
        let a = d.join("a.dsf");
        std::fs::write(&a, b"x").unwrap();
        let hard = d.join("hard.dsf");
        std::fs::hard_link(&a, &hard).unwrap();
        let soft = d.join("soft.dsf");
        std::os::unix::fs::symlink(&a, &soft).unwrap();
        let copy = d.join("copy.dsf");
        std::fs::write(&copy, b"x").unwrap();
        assert!(same_file(&a, &a));
        assert!(same_file(&a, &hard));
        assert!(same_file(&soft, &a));
        assert!(!same_file(&a, &copy));
        assert!(!same_file(&a, &d.join("missing.dsf")));
        std::fs::remove_dir_all(&d).unwrap();
    }

    /// A DSF header whose fmt chunk size makes the data chunk's offset overflow u64 is
    /// refused as damaged, not wrapped (release) or panicked on (overflow checks).
    #[test]
    fn dsf_data_len_refuses_overflowing_fmt_size() {
        let d = scratch("fmtsize");
        let f = d.join("bad.dsf");
        let mut h = vec![0u8; 92];
        h[..4].copy_from_slice(b"DSD ");
        h[28..32].copy_from_slice(b"fmt ");
        h[32..40].copy_from_slice(&(u64::MAX - 10).to_le_bytes());
        h[72..76].copy_from_slice(&4096u32.to_le_bytes());
        std::fs::write(&f, &h).unwrap();
        let e = dsf_data_len(&f).unwrap_err();
        assert!(matches!(e, Error::Format(_)), "{e:?}");
        std::fs::remove_dir_all(&d).unwrap();
    }

    /// The no-hard-link fallback of no_overwrite: moves into a free name, refuses an
    /// existing one and leaves both files as they were.
    #[test]
    fn claim_then_rename_never_replaces() {
        let d = scratch("claim");
        let (tmp, out) = (d.join("t.part1.dsf"), d.join("t.dsf"));
        std::fs::write(&tmp, b"new").unwrap();
        std::fs::write(&out, b"old").unwrap();
        let e = claim_then_rename(&tmp, &out).unwrap_err();
        assert_eq!(e.kind(), std::io::ErrorKind::AlreadyExists);
        assert_eq!(std::fs::read(&out).unwrap(), b"old");
        assert_eq!(std::fs::read(&tmp).unwrap(), b"new");
        std::fs::remove_file(&out).unwrap();
        claim_then_rename(&tmp, &out).unwrap();
        assert_eq!(std::fs::read(&out).unwrap(), b"new");
        assert!(!tmp.exists());
        std::fs::remove_dir_all(&d).unwrap();
    }
}

#[cfg(test)]
mod gate {
    //! The acceptance gate: `validate` accepts exactly the combinations of
    //! [`accepted_orders`], and each of them has a modulator table.
    use super::*;

    #[test]
    fn validate_accepts_exactly_the_accepted_orders() {
        for mult in [32, 64, 128, 256, 512] {
            let accepted = accepted_orders(Band::Audio, mult);
            assert_eq!(accepted.is_empty(), !matches!(mult, 64 | 128 | 256));
            for order in 0..=12 {
                let mut o = Options::new(Output::Dsd { mult });
                o.order = order;
                let ok = accepted.contains(&order);
                assert_eq!(o.validate().is_ok(), ok, "DSD{mult} order {order}");
                if ok {
                    assert!(tables::modulator(mult, order, false).is_some());
                }
            }
            if !accepted.is_empty() {
                let d = Options::new(Output::Dsd { mult });
                assert!(accepted.contains(&d.order));
                assert_eq!(d.band, Band::Audio);
            }
        }
        assert_eq!(accepted_orders(Band::Audio, 64), [5, 6, 7, 8]);
        assert_eq!(accepted_orders(Band::Audio, 128), [5, 6, 7]);
        assert_eq!(accepted_orders(Band::Audio, 256), [5, 6, 7, 8]);
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.order = 8;
        let e = o.validate().unwrap_err().to_string();
        assert!(
            e.contains("order 8") && e.contains("DSD128 output accepts 5, 6, 7"),
            "{e}"
        );
    }
}

#[cfg(test)]
mod cutoff_gain {
    //! The DSD64 decimators' gain at 1 kHz: docs/options.md quotes the difference between
    //! the default (140 dB Kaiser) filter and dsd2pcm's `--cutoff` filters.
    use super::*;
    use crate::testsignal::{sin_turns, write_dsd_to, Sine};

    struct Capture(Vec<u8>);
    impl dsd2pcm::io::DsdWrite for Capture {
        fn write_bytes(&mut self, data: &[Vec<u8>]) -> Result<()> {
            self.0.extend_from_slice(&data[0]);
            Ok(())
        }
        fn finish(&mut self, _: u64) -> Result<()> {
            Ok(())
        }
    }

    /// Amplitude of the 1 kHz component of the decimator's 352.8 kHz output, over 500
    /// whole periods after the first 0.1 s.
    fn level_1k(dsd: &[u8], cutoff: Option<Cutoff>) -> f64 {
        let mut o = Options::new(Output::Dsd { mult: 128 });
        o.gain_db = 0.0;
        o.cutoff = cutoff;
        let mut b = build(InputFormat::Dsd { rate: 64 * BASE }, 1, &o).unwrap();
        let f = &mut b.fronts[0];
        f.process(&Chunk::Dsd(dsd.to_vec()), &mut |_| {});
        let x: Vec<f64> = f.front_out.iter().map(|v| v * f.scale).collect();
        let (start, n) = (35_280usize, 176_400usize);
        assert!(x.len() >= start + n);
        let (mut s, mut c) = (0.0, 0.0);
        for (i, v) in x[start..start + n].iter().enumerate() {
            let j = (start + i) as u64 * 1000;
            s += v * sin_turns(j, 352_800);
            c += v * sin_turns(j + 352_800 / 4, 352_800);
        }
        2.0 * (s * s + c * c).sqrt() / n as f64
    }

    #[test]
    fn cutoff_filters_gain_at_1khz() {
        let mut cap = Capture(Vec::new());
        let tone = Sine {
            freq: 1000,
            level_db: -6.0,
            seconds: 1.0,
            channels: 1,
        };
        write_dsd_to(&mut cap, 64, &tone).unwrap();
        let default = level_1k(&cap.0, None);
        for (name, cut) in [
            ("30", Cutoff::Low),
            ("40", Cutoff::Standard),
            ("wide", Cutoff::Wide),
        ] {
            let db = 20.0 * (level_1k(&cap.0, Some(cut)) / default).log10();
            eprintln!("--cutoff {name}: {db:+.4} dB at 1 kHz re the default decimator");
            // docs/options.md quotes +0.0034 (30), -0.0026 (40) and -0.0009 dB (wide)
            assert!(db.abs() < 0.005, "--cutoff {name}: {db} dB");
        }
    }
}

#[cfg(test)]
mod alignment {
    //! The delay accounting: after the packer's skip, the modulator input of a PCM sine is
    //! the same sine at the output rate, sample for sample, for every PCM input rate. One
    //! output sample of misalignment would be an error of about 5e-4 at DSD128 (2.8e-4 at
    //! DSD256).
    use super::*;
    use crate::testsignal::sin_turns;

    fn max_error(rate: u32, mult: u32) -> f64 {
        let mut o = Options::new(Output::Dsd { mult });
        o.gain_db = 0.0;
        let b = build(InputFormat::Pcm { rate }, 1, &o).unwrap();
        let skip = b.mods[0].packer.skip as usize;
        let mut f = b.fronts.into_iter().next().unwrap();
        let n = rate as usize / 5;
        let x: Vec<f64> = (0..n as u64)
            .map(|i| 0.5 * sin_turns(i * 1000, u64::from(rate)))
            .collect();
        let mut u = Vec::new();
        f.process(&Chunk::Pcm(x), &mut |blk| u.extend_from_slice(blk));
        let fout = BASE * mult;
        // compare the middle (away from the start-up and the missing tail)
        let (a, z) = (fout as usize / 50, fout as usize / 10);
        assert!(u.len() >= skip + z);
        (a..z)
            .map(|m| (u[skip + m] - 0.25 * sin_turns(m as u64 * 1000, u64::from(fout))).abs())
            .fold(0.0, f64::max)
    }

    #[test]
    fn pcm_inputs_align_with_the_output() {
        for rate in [
            44_100, 88_200, 176_400, 352_800, 48_000, 96_000, 192_000, 384_000,
        ] {
            for mult in [64, 128, 256] {
                let e = max_error(rate, mult);
                assert!(e < 1e-6, "{rate} Hz to DSD{mult}: max error {e:e}");
            }
        }
    }
}
