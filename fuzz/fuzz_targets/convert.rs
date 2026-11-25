// SPDX-License-Identifier: MIT OR Apache-2.0
// convert() with a source that breaks the reader contract (unequal channel lengths, more
// or fewer samples than declared, errors) and arbitrary settings: never panics, and output
// stays bounded.
//
// Work per input is capped by the source's budget, not by its declared length. A conversion
// costs in proportion to the samples the source delivers (the converter refuses a source that
// ends before its declared length, at its end), but this source makes them up: one script
// byte becomes up to 9,435 DSD bytes or 2,805 PCM frames per channel, so an 8 KiB input could
// ask for minutes of audio at DSD256 on 7 channels. That is legitimate work, but it takes far
// longer than -timeout=30 under the sanitizers and starves the fuzzer. The budget, about
// 0.19 s of input per channel, is the same order as the idle chunks after the end, so every
// path (short sources, skewed channels, errors, flushes, NaN, huge declared lengths) stays
// reachable.
#![no_main]
use libfuzzer_sys::fuzz_target;
mod common;
use common::Bytes;
use dsd_upsample::dsd2pcm::dsf::DsfWriter;
use dsd_upsample::dsd2pcm::io::{DsdInfo, DsdRead, PcmInfo, PcmRead};
use dsd_upsample::dsd2pcm::{Error, Input};
use dsd_upsample::{convert, InputFormat};
use std::io::Cursor;

struct Src {
    ch: u16,
    rate: u32,
    declared: u64,
    script: Vec<u8>,
    pos: usize,
    /// Samples per channel the source may still deliver (DSD: bytes; PCM: frames).
    budget: usize,
}

/// Most DSD bytes per channel a source delivers: 0.19 s of DSD64, enough for any declared
/// length up to `u16::MAX * 8` samples.
const DSD_BUDGET: usize = 65_536;
/// Most PCM frames per channel a source delivers: 0.19 s at 44.1 kHz.
const PCM_BUDGET: usize = 8_192;

impl Src {
    fn next(&mut self) -> Option<u8> {
        let b = self.script.get(self.pos).copied();
        self.pos += 1;
        b
    }
}

impl DsdRead for Src {
    fn info(&self) -> DsdInfo {
        DsdInfo { channels: self.ch, sample_rate: self.rate, samples: self.declared }
    }
    fn read_bytes(&mut self, max: usize, out: &mut [Vec<u8>]) -> dsd_upsample::Result<usize> {
        let Some(op) = self.next() else { return Ok(0) };
        if op == 0xEE {
            return Err(Error::Format("fuzz".into()));
        }
        let n = (usize::from(op) * 37).min(max).min(self.budget);
        self.budget -= n;
        let skew = usize::from(op % 7 == 0);
        for (c, v) in out.iter_mut().enumerate() {
            v.extend(std::iter::repeat(op).take(n.saturating_sub(skew * c)));
        }
        Ok(n)
    }
}

impl PcmRead for Src {
    fn info(&self) -> PcmInfo {
        PcmInfo { channels: self.ch, sample_rate: self.rate, frames: self.declared }
    }
    fn read_frames(&mut self, max: usize, out: &mut [Vec<f64>]) -> dsd_upsample::Result<usize> {
        let Some(op) = self.next() else { return Ok(0) };
        if op == 0xEE {
            return Err(Error::Format("fuzz".into()));
        }
        let n = (usize::from(op) * 11).min(max).min(self.budget);
        self.budget -= n;
        let skew = usize::from(op % 7 == 0);
        let v = if op == 0xFF { f64::NAN } else { (f64::from(op) - 128.0) / 64.0 };
        for (c, o) in out.iter_mut().enumerate() {
            o.extend(std::iter::repeat(v).take(n.saturating_sub(skew * c)));
        }
        Ok(n)
    }
}

fuzz_target!(|data: &[u8]| {
    let mut b = Bytes(data);
    let o = common::options(&mut b);
    let fmt = common::format(&mut b);
    let ch = u16::from(b.u8() % 8);
    let declared = u64::from(b.u16()) * [1, 8, 1000, 1 << 40][usize::from(b.u8() % 4)];
    let script = b.0.to_vec();
    let input = match fmt {
        InputFormat::Dsd { rate } => {
            let budget = DSD_BUDGET;
            Input::Dsd(Box::new(Src { ch, rate, declared, script, pos: 0, budget }))
        }
        InputFormat::Pcm { rate } => {
            let budget = PCM_BUDGET;
            Input::Pcm(Box::new(Src { ch, rate, declared, script, pos: 0, budget }))
        }
    };
    let Ok(mut w) = DsfWriter::new(Cursor::new(Vec::new()), ch.max(1), 44_100 * 128, None) else {
        return;
    };
    let _ = convert(input, &mut w, &o);
    // A source that stops early must not make the output grow with silence.
    assert!(w.into_inner().into_inner().len() < 256 << 20);
});
