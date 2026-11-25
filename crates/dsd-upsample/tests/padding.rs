// SPDX-License-Identifier: MIT OR Apache-2.0
//! DSF input whose sample count is not a multiple of 8: the bits after the last sample in
//! the last byte are padding (zero in normal files) and must not reach the output as
//! audio, where they would be a click on a silent ending. The output must be the same as
//! for the same file with those bits set to the idle pattern 0x69.

use dsd_upsample::dsd2pcm::dsf::DsfWriter;
use dsd_upsample::dsd2pcm::io::DsdWrite;
use dsd_upsample::dsd2pcm::PcmRate;
use dsd_upsample::{convert_file, Options, Output};
use std::path::{Path, PathBuf};

/// Digital silence (0x69) of `samples` samples per channel, stereo DSD64, with the bits
/// past `samples` in the last byte taken from `pad` (MSB-first, as delivered to writers).
fn silent_dsf(path: &Path, samples: u64, pad: u8) {
    let bytes = samples.div_ceil(8) as usize;
    let mut data = vec![0x69u8; bytes];
    let used = (samples % 8) as u32;
    assert_ne!(used, 0);
    let keep = 0xffu8 << (8 - used);
    data[bytes - 1] = (0x69 & keep) | (pad & !keep);
    let f = std::io::BufWriter::new(std::fs::File::create(path).unwrap());
    let mut w = DsfWriter::new(f, 2, 2_822_400, None).unwrap();
    w.write_bytes(&[data.clone(), data]).unwrap();
    w.finish(samples).unwrap();
}

fn scratch() -> PathBuf {
    let d = std::env::temp_dir().join(format!("dsdup-padding-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn padding_bits_are_not_audio() {
    let d = scratch();
    let samples = 8 * 35_280 + 3; // 0.1 s of DSD64 and 3 samples
    let (zero, idle) = (d.join("zero.dsf"), d.join("idle.dsf"));
    silent_dsf(&zero, samples, 0x00);
    silent_dsf(&idle, samples, 0x69);
    let outputs = [
        (Output::Dsd { mult: 128 }, "dsf"),
        (Output::Dsd { mult: 256 }, "dsf"),
        (Output::Pcm(PcmRate::Hz176400), "wav"),
    ];
    for (out, ext) in outputs {
        let a = d.join(format!("zero-out.{ext}"));
        let b = d.join(format!("idle-out.{ext}"));
        convert_file(&zero, &a, &Options::new(out)).unwrap();
        convert_file(&idle, &b, &Options::new(out)).unwrap();
        assert!(
            std::fs::read(&a).unwrap() == std::fs::read(&b).unwrap(),
            "{out:?}: zero padding bits change the output (a click at the end)"
        );
    }
    std::fs::remove_dir_all(&d).unwrap();
}
