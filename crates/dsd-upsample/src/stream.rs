// SPDX-License-Identifier: MIT OR Apache-2.0
//! Streaming conversion: push input as it arrives, receive DSD output as it is produced.
//!
//! Gives the same bytes as [`crate::convert()`] for the same input and settings, however the
//! input is split into pushes. Runs on the calling thread.

use crate::convert::{build, output_len, Built, Chunk, FrontStage, InputFormat, ModStage};
use crate::filters::IDLE;
use crate::modulator::Counters;
use crate::{Error, Options, Result};

/// Receives output: one byte vector per channel (MSB-first, equal lengths).
pub type Emit<'a> = &'a mut dyn FnMut(&[Vec<u8>]) -> Result<()>;

/// A streaming converter to DSD64 (from PCM), DSD128 or DSD256.
pub struct Stream {
    fronts: Vec<FrontStage>,
    mods: Vec<ModStage>,
    fmt: InputFormat,
    fout: u32,
    pcm_chunk: usize,
    /// Input samples per channel so far.
    n_in: u64,
    /// Filter delay in output samples.
    delay: u64,
    finished: bool,
}

/// Idle chunks fed at the end before giving up (2 are needed at most).
const MAX_FLUSHES: usize = 64;

impl Stream {
    /// A converter for `channels` channels of `fmt` (`opts.threads` is ignored).
    pub fn new(fmt: InputFormat, channels: u16, opts: &Options) -> Result<Stream> {
        let Built {
            fronts,
            mods,
            fout,
            pcm_chunk,
        } = build(fmt, channels, opts)?;
        let delay = mods.first().map_or(0, |m| m.packer.skip);
        Ok(Stream {
            fronts,
            mods,
            fmt,
            fout,
            pcm_chunk,
            n_in: 0,
            delay,
            finished: false,
        })
    }

    /// Output sample rate in Hz.
    pub fn out_rate(&self) -> u32 {
        self.fout
    }

    /// Number of channels.
    pub fn channels(&self) -> usize {
        self.fronts.len()
    }

    /// Modulator counters per channel so far.
    pub fn counters(&self) -> Vec<Counters> {
        self.mods.iter().map(|m| m.modulator.counters).collect()
    }

    fn check(&self, n: usize, lens: impl Iterator<Item = usize>) -> Result<usize> {
        if self.finished {
            return Err(Error::InvalidArgument("the stream is finished".into()));
        }
        let lens: Vec<usize> = lens.collect();
        if n != self.channels() {
            return Err(Error::InvalidArgument(format!(
                "{n} channels pushed, the stream has {}",
                self.channels()
            )));
        }
        if lens.windows(2).any(|w| w[0] != w[1]) {
            return Err(Error::InvalidArgument(
                "channels of different lengths".into(),
            ));
        }
        Ok(lens[0])
    }

    /// Pushes DSD bytes (MSB-first), one slice per channel, of equal lengths.
    pub fn push_dsd(&mut self, chans: &[&[u8]], emit: Emit<'_>) -> Result<()> {
        let n = self.check(chans.len(), chans.iter().map(|c| c.len()))?;
        if !matches!(self.fmt, InputFormat::Dsd { .. }) {
            return Err(Error::InvalidArgument("the stream takes PCM".into()));
        }
        self.n_in += 8 * n as u64;
        let chunks: Vec<Chunk> = chans.iter().map(|c| Chunk::Dsd(c.to_vec())).collect();
        self.run(&chunks, emit)
    }

    /// Pushes PCM frames (full scale +-1.0), one slice per channel, of equal lengths.
    pub fn push_pcm(&mut self, chans: &[&[f64]], emit: Emit<'_>) -> Result<()> {
        let n = self.check(chans.len(), chans.iter().map(|c| c.len()))?;
        if !matches!(self.fmt, InputFormat::Pcm { .. }) {
            return Err(Error::InvalidArgument("the stream takes DSD".into()));
        }
        self.n_in += n as u64;
        let chunks: Vec<Chunk> = chans.iter().map(|c| Chunk::Pcm(c.to_vec())).collect();
        self.run(&chunks, emit)
    }

    fn run(&mut self, chunks: &[Chunk], emit: Emit<'_>) -> Result<()> {
        let mut out = Vec::with_capacity(chunks.len());
        for ((f, m), x) in self.fronts.iter_mut().zip(&mut self.mods).zip(chunks) {
            f.process(x, &mut |u| m.process(u));
            out.push(m.end_chunk().0);
        }
        if out.first().is_some_and(|o| !o.is_empty()) {
            emit(&out)?;
        }
        Ok(())
    }

    /// How far the output lags the input, in output samples: the filters' delay, which the
    /// stream compensates by holding back that many samples (plus up to 7 bits that wait
    /// for a whole byte). For a host's latency report.
    pub fn delay(&self) -> u64 {
        self.delay
    }

    /// Ends the input: emits the rest of the output, which then has exactly
    /// `input samples x output rate / input rate` samples per channel, and returns that
    /// number.
    pub fn finish(&mut self, emit: Emit<'_>) -> Result<u64> {
        let n = self.n_in;
        self.finish_exact(n, emit)
    }

    /// [`Stream::finish`] for an input of exactly `samples` samples per channel: for DSD
    /// input whose last byte is partly padding (DSF and DFF store whole bytes), so that the
    /// output length matches the real input.
    ///
    /// Only the padding of the last byte can be declared away: for DSD input, `samples`
    /// must be at most the samples pushed (8 per byte) and more than the samples pushed
    /// minus 8 (less than one byte shorter); for PCM input, it must equal the frames
    /// pushed. Anything else is an [`Error::InvalidArgument`] and leaves the stream
    /// unfinished: output for the pushed input may already have been emitted, so a shorter
    /// declared length could not be honoured.
    pub fn finish_exact(&mut self, samples: u64, emit: Emit<'_>) -> Result<u64> {
        if self.finished {
            return Err(Error::InvalidArgument("the stream is finished".into()));
        }
        if samples > self.n_in {
            return Err(Error::InvalidArgument(format!(
                "{samples} samples declared, {} pushed",
                self.n_in
            )));
        }
        let slack = match self.fmt {
            InputFormat::Dsd { .. } => 7,
            InputFormat::Pcm { .. } => 0,
        };
        if samples < self.n_in.saturating_sub(slack) {
            return Err(Error::InvalidArgument(format!(
                "{samples} samples declared, less than the {} already pushed minus the \
                 padding of one byte",
                self.n_in
            )));
        }
        self.finished = true;
        let n_out = output_len(samples, self.fmt.rate(), self.fout)?;
        for m in &mut self.mods {
            m.packer.left = n_out.saturating_sub(m.packer.taken);
        }
        let idle = |fmt: InputFormat, pcm: usize| match fmt {
            InputFormat::Dsd { .. } => Chunk::Dsd(vec![IDLE; 8192]),
            InputFormat::Pcm { .. } => Chunk::Pcm(vec![0.0; pcm]),
        };
        for _ in 0..=MAX_FLUSHES {
            // The first pass emits what the packers hold back from earlier pushes.
            let mut out = Vec::with_capacity(self.channels());
            let mut done = false;
            for (f, m) in self.fronts.iter_mut().zip(&mut self.mods) {
                if !m.packer.done() {
                    f.process(&idle(self.fmt, self.pcm_chunk), &mut |u| m.process(u));
                }
                let (bytes, d) = m.end_chunk();
                out.push(bytes);
                done = d;
            }
            if !out[0].is_empty() {
                emit(&out)?;
            }
            if done {
                return Ok(n_out);
            }
        }
        Err(Error::InvalidArgument("flush did not complete".into()))
    }
}
