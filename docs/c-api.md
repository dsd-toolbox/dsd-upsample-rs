[dsd-upsample-rs](../README.md) › [Documentation](README.md) › C interface

# C interface

What the C library offers and where its full reference lives: the header comments.

## Library and files

`crates/dsd-upsample-capi` builds `libdsd_upsample`: shared (soname `libdsd_upsample.so.1` on
Linux) and static, with the header `crates/dsd-upsample-capi/include/dsd_upsample.h`. The
release archives hold the library and the header; the Linux x86_64 archive also holds a
pkg-config file (`lib/pkgconfig/dsd_upsample.pc`). On macOS and Windows, point the compiler
at `include/` and the linker at `lib/` yourself.

## Functions

- One settings struct (`dsdup_settings`, initialised with `dsdup_settings_init`).
- Whole-file conversion (`dsdup_convert_file`) with a progress callback that can cancel and
  an optional report. The output is written to a temporary `NAME.partN.EXT` next to it and
  renamed on success: an error or a cancel leaves no partial file, and an existing output
  is replaced only by a complete one.
- A streaming converter: `dsdup_stream_new`, push DSD (`dsdup_stream_push_dsd`) or PCM
  (`dsdup_stream_push_pcm`), receive DSD through an output callback, `dsdup_stream_finish`.
  PCM streams take 44.1, 88.2, 176.4 or 352.8 kHz, or 48, 96, 192 or 384 kHz (resampled
  by 147/160 first; `dsdup_stream_delay` includes the resampler's delay, 182 samples at
  the 44.1 kHz-family rate); other rates return `DSDUP_ERR_UNSUPPORTED`.
  `dsdup_stream_finish` reports `input samples × output rate / input rate`, rounded down.
  For 48 kHz-family PCM (48,001 frames at 48 kHz, for example) that count need not be a
  multiple of 8: the last byte then carries the remaining samples in its high bits and
  idle-pattern bits below them. 44.1 kHz-family PCM always gives whole bytes.
- Status codes, with a message from `dsdup_last_error()`.

## Ownership and threading

The header documents ownership, threading and reentrancy: a call into a stream from its own
callback returns `DSDUP_ERR_BUSY` (including `dsdup_stream_counters`; read the counters after
the call returns), except `dsdup_stream_delay`, which works there, and freeing a stream from its callback is deferred to the
end of the outer call, which returns `DSDUP_OK` without calling the callback again, so the
callback may free its user data with the stream. Callbacks must return normally: a C++
exception or a `longjmp` must not leave a callback, because unwinding through the library
aborts the process.

## ABI evolution

ABI version 1 (`DSDUP_ABI_VERSION`, soname `libdsd_upsample.so.1`) stays compatible across
1.x releases: they only add functions, constants and fields at the end of `dsdup_settings`
and `dsdup_report`. So that a newer library never writes past an older caller's struct, every
function that fills a struct takes the caller's size:

- `dsdup_settings_init(s, output)` is a macro for
  `dsdup_settings_init_sized(s, sizeof(dsdup_settings), output)`;
- `dsdup_convert_file(..., report)` is a macro for
  `dsdup_convert_file_sized(..., report, sizeof(dsdup_report))`.

The library writes exactly the caller's size: it zeros all of it, then writes the fields it
knows, so fields of a newer header that it does not know read 0 (the default of every field
added later). A struct
smaller than ABI 1.0's is refused with `DSDUP_ERR_INVALID_ARGUMENT` before anything is
written or converted. When reading `dsdup_settings`, the library takes the size from
`struct_size` (set by `dsdup_settings_init`) and uses the defaults for fields the caller's
struct lacks. `dsdup_counters` never grows.

The structs have no implicit padding on 64-bit or 32-bit targets: every byte belongs to a
field, so every byte the library fills is defined, and a field added later always changes
`sizeof` (a field placed in padding would not, and `struct_size` could not tell the versions
apart). `dsdup_settings` (48 bytes) ends with `uint32_t band` (the modulator's noise-shaping band:
0 = `DSDUP_BAND_AUDIO`, the default that `dsdup_settings_init` writes and the only band of
this release; 1 is reserved for a later release; every value but 0 is refused with
`DSDUP_ERR_INVALID_ARGUMENT`), and `dsdup_report`
(224 bytes) has `uint32_t reserved` after `channels`. Code that fills `dsdup_settings` by
hand must zero it (`memset`) first, which selects the defaults of fields it does not know. The library always writes 0 to the
report's `reserved`. The Rust side checks the sizes and offsets at compile time, and the
header does too with `_Static_assert` (C11) or `static_assert` (C++11).

C and C++ code calls the macros and needs only to
be compiled against the header; bindings in other languages call the `_sized` functions with
the size of their own struct.

## Testing

`tools/c-smoke.sh` builds the library and runs a C test against it (with AddressSanitizer and
UBSan when clang is installed). `tools/c-leak.sh` runs a leak loop under AddressSanitizer
([results](measurements.md#long-running-use-threads-and-memory)).

## See also

- [Options](options.md): the same settings on the command line
- [Design](design.md)
- [Install: packages](install/packages.md)
- [Rust API](https://docs.rs/dsd-upsample) on docs.rs

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
