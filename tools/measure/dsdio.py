# SPDX-License-Identifier: MIT OR Apache-2.0
"""File input and output for DSD and PCM test files.

- ``read_dsd(path, channel)``: one channel of a DSF or DFF file as a NumPy ``uint8`` array of
  bits (0 or 1, in time order) and the DSD sample rate in Hz.
- ``read_wav(path)``: a PCM WAV (16, 24 or 32-bit integer, 32 or 64-bit float) as float64
  in [-1, 1), shape (samples, channels), and the sample rate.
- ``write_wav(path, x, fs, fmt)``: writes float samples as ``i16``, ``i24``, ``i32`` (rounded,
  clipped) or ``f32``/``f64``.

Only the standard library and NumPy are used.
"""
import struct
import sys

import numpy as np


def read_dsd(path, channel=0):
    """Return (bits, rate): one channel of a DSF or DFF file as uint8 0/1 values."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"DSD ":
        ch, rate, bits, samples, block = struct.unpack_from("<IIIQI", data, 52)
        lsb = bits == 1
        start = 92
        nblk = (len(data) - start) // (block * ch)
        raw = np.frombuffer(data, dtype=np.uint8, count=nblk * block * ch, offset=start)
        raw = raw.reshape(nblk, ch, block)[:, channel, :].reshape(-1)
        b = np.unpackbits(raw, bitorder="little" if lsb else "big")[:samples]
        return b, rate
    if data[:4] == b"FRM8":
        pos, rate, ch = 16, None, None
        while pos + 12 <= len(data):
            cid = data[pos:pos + 4]
            size = struct.unpack_from(">Q", data, pos + 4)[0]
            body = pos + 12
            if cid == b"PROP":
                p = body + 4
                while p < body + size:
                    sid = data[p:p + 4]
                    ss = struct.unpack_from(">Q", data, p + 4)[0]
                    if sid == b"FS  ":
                        rate = struct.unpack_from(">I", data, p + 12)[0]
                    if sid == b"CHNL":
                        ch = struct.unpack_from(">H", data, p + 12)[0]
                    p += 12 + ss + (ss & 1)
            if cid == b"DSD ":
                raw = np.frombuffer(data, dtype=np.uint8, count=size, offset=body)
                raw = raw[: len(raw) // ch * ch].reshape(-1, ch)[:, channel]
                return np.unpackbits(raw, bitorder="big"), rate
            pos = body + size + (size & 1)
    raise ValueError(f"{path}: not a DSF or DFF file")


def iter_dsf(path, channel=0, blocks=512):
    """Yield one channel of a DSF file as uint8 0/1 bit arrays, `blocks` DSF blocks at a
    time (memory-mapped; for files too large to unpack at once)."""
    with open(path, "rb") as f:
        head = f.read(92)
    if head[:4] != b"DSD ":
        raise ValueError(f"{path}: not a DSF file")
    ch, rate, bits, samples, block = struct.unpack_from("<IIIQI", head, 52)
    mm = np.memmap(path, dtype=np.uint8, mode="r", offset=92)
    nblk = len(mm) // (block * ch)
    view = mm[: nblk * block * ch].reshape(nblk, ch, block)
    left = samples
    for a in range(0, nblk, blocks):
        raw = np.ascontiguousarray(view[a:a + blocks, channel, :]).reshape(-1)
        b = np.unpackbits(raw, bitorder="little" if bits == 1 else "big")
        b = b[:left]
        left -= len(b)
        if len(b):
            yield b
        if left <= 0:
            break


def dsf_rate(path):
    with open(path, "rb") as f:
        head = f.read(92)
    return struct.unpack_from("<I", head, 56)[0]


def read_wav(path):
    """Return (x, fs): x is float64 of shape (samples, channels), full scale = 1.0."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    pos, fmt, fs, ch, bits = 12, None, None, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt, ch, fs = struct.unpack_from("<HHI", data, body)
            bits = struct.unpack_from("<H", data, body + 14)[0]
            if fmt == 0xFFFE:
                fmt = struct.unpack_from("<H", data, body + 24)[0]
        if cid == b"data":
            raw = data[body:body + size]
            if fmt == 3 and bits == 32:
                x = np.frombuffer(raw, "<f4").astype(np.float64)
            elif fmt == 3 and bits == 64:
                x = np.frombuffer(raw, "<f8").copy()
            elif fmt == 1 and bits == 16:
                x = np.frombuffer(raw, "<i2") / 32768.0
            elif fmt == 1 and bits == 32:
                x = np.frombuffer(raw, "<i4") / 2147483648.0
            elif fmt == 1 and bits == 24:
                b = np.frombuffer(raw[: len(raw) // 3 * 3], np.uint8).reshape(-1, 3)
                v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
                     | (b[:, 2].astype(np.int32) << 16))
                v = np.where(v >= 1 << 23, v - (1 << 24), v)
                x = v / 8388608.0
            else:
                raise ValueError(f"{path}: unsupported WAV format {fmt}/{bits}")
            return x[: len(x) // ch * ch].reshape(-1, ch), fs
        pos = body + size + (size & 1)
    raise ValueError(f"{path}: no data chunk")


def write_wav(path, x, fs, fmt="i32"):
    """Write x (samples or samples x channels, float, full scale 1.0) as a WAV file.

    Integer formats round to nearest and clip; no dither is added here (callers that want
    dither add it before)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    ch = x.shape[1]
    if fmt in ("f32", "f64"):
        tag, bits = 3, 32 if fmt == "f32" else 64
        data = x.astype("<f4" if fmt == "f32" else "<f8").tobytes()
    else:
        tag = 1
        bits = {"i16": 16, "i24": 24, "i32": 32}[fmt]
        scale = float(1 << (bits - 1))
        v = np.clip(np.round(x * scale), -scale, scale - 1).astype(np.int64)
        if bits == 16:
            data = v.astype("<i2").tobytes()
        elif bits == 32:
            data = v.astype("<i4").tobytes()
        else:
            u = (v & 0xFFFFFF).astype(np.uint32).reshape(-1)
            b = np.empty((u.size, 3), np.uint8)
            b[:, 0] = u & 0xFF
            b[:, 1] = (u >> 8) & 0xFF
            b[:, 2] = (u >> 16) & 0xFF
            data = b.tobytes()
    ba = ch * bits // 8
    if tag == 3:
        fmtc = struct.pack("<HHIIHHH", 3, ch, fs, fs * ba, ba, bits, 0)
    else:
        fmtc = struct.pack("<HHIIHH", 1, ch, fs, fs * ba, ba, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmtc)) + fmtc
    body += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        try:
            b, r = read_dsd(p)
            print(f"{p}: DSD, {r} Hz, {len(b)} samples")
        except ValueError:
            x, fs = read_wav(p)
            print(f"{p}: PCM, {fs} Hz, {x.shape[0]} samples, {x.shape[1]} channels")
