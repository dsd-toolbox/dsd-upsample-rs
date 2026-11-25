// SPDX-License-Identifier: MIT OR Apache-2.0
//! A minimal ID3v2.4 writer for DSF output: UTF-8 text frames from key/value pairs.
//!
//! Format: ID3v2.4.0 (id3.org "ID3 tag version 2.4.0 - Main Structure" and "Native
//! Frames"): a 10-byte header with a synchsafe size, then frames with synchsafe sizes; text
//! frames start with the encoding byte 3 (UTF-8). Writing only; this crate never parses
//! ID3.

use crate::{Error, Result};

/// The frame for a common key (case-insensitive), or `None` for a TXXX frame.
fn frame_id(key: &str) -> Option<&'static [u8; 4]> {
    Some(match key.to_ascii_lowercase().as_str() {
        "title" => b"TIT2",
        "artist" => b"TPE1",
        "album" => b"TALB",
        "albumartist" | "album_artist" => b"TPE2",
        "track" | "tracknumber" => b"TRCK",
        "disc" | "discnumber" => b"TPOS",
        "date" | "year" => b"TDRC",
        "genre" => b"TCON",
        "composer" => b"TCOM",
        "comment" => b"COMM",
        _ => return None,
    })
}

fn synchsafe(n: usize) -> Result<[u8; 4]> {
    if n >= 1 << 28 {
        return Err(Error::InvalidArgument("tag too large".into()));
    }
    Ok([
        (n >> 21) as u8 & 0x7f,
        (n >> 14) as u8 & 0x7f,
        (n >> 7) as u8 & 0x7f,
        n as u8 & 0x7f,
    ])
}

/// An ID3v2.4 tag holding `tags` in order. Keys: title, artist, album, albumartist, track,
/// disc, date, genre, composer, comment; any other key becomes a TXXX frame with that key
/// as its description. Keys and values may not contain NUL; keys may not be empty.
pub fn tag(tags: &[(String, String)]) -> Result<Vec<u8>> {
    let mut frames = Vec::new();
    for (k, v) in tags {
        if k.is_empty() || k.contains('\0') || v.contains('\0') {
            return Err(Error::InvalidArgument(format!(
                "tag {k:?}: empty key or NUL character"
            )));
        }
        let (id, body): (&[u8; 4], Vec<u8>) = match frame_id(k) {
            Some(b"COMM") => {
                // encoding, language, empty description, text
                let mut b = vec![3, b'e', b'n', b'g', 0];
                b.extend_from_slice(v.as_bytes());
                (b"COMM", b)
            }
            Some(id) => {
                let mut b = vec![3];
                b.extend_from_slice(v.as_bytes());
                (id, b)
            }
            None => {
                let mut b = vec![3];
                b.extend_from_slice(k.as_bytes());
                b.push(0);
                b.extend_from_slice(v.as_bytes());
                (b"TXXX", b)
            }
        };
        frames.extend_from_slice(id);
        frames.extend_from_slice(&synchsafe(body.len())?);
        frames.extend_from_slice(&[0, 0]);
        frames.extend_from_slice(&body);
    }
    let mut out = b"ID3\x04\x00\x00".to_vec();
    out.extend_from_slice(&synchsafe(frames.len())?);
    out.extend_from_slice(&frames);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_frames() {
        let t = tag(&[
            ("Title".into(), "Fire and Water".into()),
            ("artist".into(), "Ünïcode".into()),
            ("comment".into(), "c".into()),
            ("SOURCE".into(), "SACD".into()),
        ])
        .unwrap();
        assert_eq!(&t[..6], b"ID3\x04\x00\x00");
        let size = (usize::from(t[6]) << 21)
            | (usize::from(t[7]) << 14)
            | (usize::from(t[8]) << 7)
            | usize::from(t[9]);
        assert_eq!(size, t.len() - 10);
        assert_eq!(&t[10..14], b"TIT2");
        assert_eq!(&t[14..18], &[0, 0, 0, 15]);
        assert_eq!(&t[20..35], b"\x03Fire and Water");
        assert!(t.windows(4).any(|w| w == b"TPE1"));
        assert!(t.windows(9).any(|w| w == b"COMM\x00\x00\x00\x06\x00"));
        assert!(t.windows(4).any(|w| w == b"TXXX"));
        assert!(t.windows(12).any(|w| w == b"\x03SOURCE\x00SACD"));
    }

    #[test]
    fn rejects_bad_keys() {
        assert!(tag(&[(String::new(), "x".into())]).is_err());
        assert!(tag(&[("a\0b".into(), "x".into())]).is_err());
        assert!(tag(&[("title".into(), "x\0".into())]).is_err());
    }
}
