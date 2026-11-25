// SPDX-License-Identifier: MIT OR Apache-2.0
//! C interface of dsd-upsample; the header is `include/dsd_upsample.h`.
//!
//! Safety rules for this crate, the only one with `unsafe`:
//! - every entry point checks each pointer for NULL before use and returns `DSDUP_ERR_NULL`;
//! - slices built from caller pointers live only for the call;
//! - every entry point runs inside `catch_unwind`, so no panic crosses the C boundary
//!   (it becomes `DSDUP_ERR_INTERNAL`);
//! - `dsdup_settings` is read only after `struct_size` shows the caller's struct is at
//!   least as large as this version's;
//! - structs the library fills (`dsdup_settings`, `dsdup_report`) come with the caller's
//!   size, and the library writes exactly that many bytes (see "ABI evolution" in
//!   docs/c-api.md).
#![deny(unsafe_op_in_unsafe_fn)]
#![allow(clippy::missing_safety_doc)]

use dsd_upsample::dsd2pcm::decimator::{Cutoff, PcmRate};
use dsd_upsample::modulator::Counters;
use dsd_upsample::{
    convert_file_to, is_cancelled, Band, Error, FileOutput, InputFormat, Options, Output, Stream,
};
use std::cell::{Cell, RefCell, UnsafeCell};
use std::ffi::{c_char, c_void, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::PathBuf;

pub const DSDUP_OK: i32 = 0;
pub const DSDUP_ERR_INVALID_ARGUMENT: i32 = 1;
pub const DSDUP_ERR_UNSUPPORTED: i32 = 2;
pub const DSDUP_ERR_FORMAT: i32 = 3;
pub const DSDUP_ERR_IO: i32 = 4;
pub const DSDUP_ERR_CANCELLED: i32 = 5;
pub const DSDUP_ERR_NULL: i32 = 6;
pub const DSDUP_ERR_INTERNAL: i32 = 7;
pub const DSDUP_ERR_BUSY: i32 = 8;
pub const DSDUP_ERR_EXISTS: i32 = 9;

pub const DSDUP_OUT_DSD64: u32 = 64;
pub const DSDUP_OUT_DSD128: u32 = 128;
pub const DSDUP_BAND_AUDIO: u32 = 0;
pub const DSDUP_OUT_DSD256: u32 = 256;
pub const DSDUP_OUT_PCM88: u32 = 1;
pub const DSDUP_OUT_PCM176: u32 = 2;
pub const DSDUP_OUT_PCM352: u32 = 3;

pub const DSDUP_IN_DSD: u32 = 0;
pub const DSDUP_IN_PCM: u32 = 1;

pub const DSDUP_MAX_CHANNELS: usize = 6;

/// `dsdup_settings`.
#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct DsdupSettings {
    pub struct_size: u32,
    pub output: u32,
    pub order: u32,
    pub cutoff: u32,
    pub gain_db: f64,
    pub input_limit: f64,
    pub dither: u32,
    pub threads: u32,
    pub no_overwrite: u32,
    /// `DSDUP_BAND_AUDIO` (0), the only band of this release; 1 is reserved. The field also
    /// fills the struct's tail, so there is no implicit padding (see the layout assertions).
    pub band: u32,
}

/// `dsdup_counters`.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct DsdupCounters {
    pub limited: u64,
    pub clipped: u64,
    pub resets: u64,
}

/// `dsdup_report`.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct DsdupReport {
    pub in_rate: u32,
    pub out_rate: u32,
    pub seconds: f64,
    pub out_samples: u64,
    pub channels: u32,
    /// Always 0 (fills the hole before `counters`; see the layout assertions).
    pub reserved: u32,
    pub counters: [DsdupCounters; DSDUP_MAX_CHANNELS],
    pub pcm_clipped: [u64; DSDUP_MAX_CHANNELS],
}

// The C structs have no implicit padding on any target: every byte belongs to a field,
// so the library writes every byte of the caller's struct, and a field added later cannot
// land in padding without changing `sizeof` (which would defeat `struct_size`). The sum
// of the field sizes equals the struct size on every target (this also holds on 32-bit
// targets, where `double` and `uint64_t` may be 4-byte aligned), and the offsets match the
// header's `_Static_assert`s.
const _: () = {
    use std::mem::{offset_of, size_of};
    assert!(size_of::<DsdupSettings>() == 48);
    assert!(size_of::<DsdupSettings>() == 4 * 4 + 2 * 8 + 4 * 4);
    assert!(offset_of!(DsdupSettings, struct_size) == 0);
    assert!(offset_of!(DsdupSettings, output) == 4);
    assert!(offset_of!(DsdupSettings, order) == 8);
    assert!(offset_of!(DsdupSettings, cutoff) == 12);
    assert!(offset_of!(DsdupSettings, gain_db) == 16);
    assert!(offset_of!(DsdupSettings, input_limit) == 24);
    assert!(offset_of!(DsdupSettings, dither) == 32);
    assert!(offset_of!(DsdupSettings, threads) == 36);
    assert!(offset_of!(DsdupSettings, no_overwrite) == 40);
    assert!(offset_of!(DsdupSettings, band) == 44);
    assert!(size_of::<DsdupCounters>() == 24);
    assert!(size_of::<DsdupReport>() == 224);
    assert!(size_of::<DsdupReport>() == 4 + 4 + 8 + 8 + 4 + 4 + DSDUP_MAX_CHANNELS * (24 + 8));
    assert!(offset_of!(DsdupReport, in_rate) == 0);
    assert!(offset_of!(DsdupReport, out_rate) == 4);
    assert!(offset_of!(DsdupReport, seconds) == 8);
    assert!(offset_of!(DsdupReport, out_samples) == 16);
    assert!(offset_of!(DsdupReport, channels) == 24);
    assert!(offset_of!(DsdupReport, reserved) == 28);
    assert!(offset_of!(DsdupReport, counters) == 32);
    assert!(offset_of!(DsdupReport, pcm_clipped) == 176);
};

pub type DsdupProgressFn = Option<unsafe extern "C" fn(*mut c_void, u64, u64) -> i32>;
pub type DsdupOutputFn = Option<OutputCb>;

thread_local! {
    static LAST_ERROR: RefCell<CString> = RefCell::new(CString::default());
}

fn set_error(msg: &str) {
    let c = CString::new(msg.replace('\0', " ")).unwrap_or_default();
    LAST_ERROR.with(|e| *e.borrow_mut() = c);
}

/// A failure: status code and message.
struct Fail(i32, String);

impl From<Error> for Fail {
    fn from(e: Error) -> Fail {
        let code = if is_cancelled(&e) {
            DSDUP_ERR_CANCELLED
        } else {
            match &e {
                Error::InvalidArgument(_) => DSDUP_ERR_INVALID_ARGUMENT,
                Error::Unsupported(_) => DSDUP_ERR_UNSUPPORTED,
                Error::Format(_) => DSDUP_ERR_FORMAT,
                Error::Io(io) if io.kind() == std::io::ErrorKind::AlreadyExists => DSDUP_ERR_EXISTS,
                Error::Io(_) => DSDUP_ERR_IO,
                Error::Cancelled => DSDUP_ERR_CANCELLED,
                // The error type is non-exhaustive: a kind added later reads as internal
                // until it gets a code of its own.
                _ => DSDUP_ERR_INTERNAL,
            }
        };
        Fail(code, e.to_string())
    }
}

fn null(what: &str) -> Fail {
    Fail(DSDUP_ERR_NULL, format!("{what} is NULL"))
}

fn invalid(msg: impl Into<String>) -> Fail {
    Fail(DSDUP_ERR_INVALID_ARGUMENT, msg.into())
}

/// Runs `f`, turning errors and panics into a status and the thread's last error.
fn guard(f: impl FnOnce() -> Result<(), Fail>) -> i32 {
    set_error("");
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(Ok(())) => DSDUP_OK,
        Ok(Err(Fail(code, msg))) => {
            set_error(&msg);
            code
        }
        Err(_) => {
            set_error("internal error (panic); please report it");
            DSDUP_ERR_INTERNAL
        }
    }
}

fn defaults(output: u32) -> Result<DsdupSettings, Fail> {
    let out = output_of(output)?;
    let o = Options::new(out);
    Ok(DsdupSettings {
        struct_size: std::mem::size_of::<DsdupSettings>() as u32,
        output,
        order: o.order as u32,
        cutoff: 0,
        gain_db: o.gain_db,
        input_limit: 0.0,
        dither: 0,
        threads: 1,
        no_overwrite: 0,
        band: DSDUP_BAND_AUDIO,
    })
}

fn output_of(v: u32) -> Result<Output, Fail> {
    Ok(match v {
        DSDUP_OUT_DSD64 => Output::Dsd { mult: 64 },
        DSDUP_OUT_DSD128 => Output::Dsd { mult: 128 },
        DSDUP_OUT_DSD256 => Output::Dsd { mult: 256 },
        DSDUP_OUT_PCM88 => Output::Pcm(PcmRate::Hz88200),
        DSDUP_OUT_PCM176 => Output::Pcm(PcmRate::Hz176400),
        DSDUP_OUT_PCM352 => Output::Pcm(PcmRate::Hz352800),
        _ => return Err(invalid(format!("output {v}: not a DSDUP_OUT_* value"))),
    })
}

/// Reads and validates the caller's settings.
///
/// # Safety
/// `s` is NULL or points to at least `struct_size` readable bytes.
unsafe fn options(s: *const DsdupSettings) -> Result<Options, Fail> {
    // SAFETY: caller contract, as for `settings`.
    unsafe { settings(s) }.and_then(|s| options_of(&s))
}

/// Reads the caller's settings struct.
///
/// # Safety
/// `s` is NULL or points to at least `struct_size` readable bytes.
unsafe fn settings(s: *const DsdupSettings) -> Result<DsdupSettings, Fail> {
    if s.is_null() {
        return Err(null("settings"));
    }
    // SAFETY: non-NULL; the caller promises `struct_size` readable bytes, and the first
    // field is read alone before trusting the rest.
    let size = unsafe { std::ptr::addr_of!((*s).struct_size).read_unaligned() } as usize;
    if size < std::mem::size_of::<DsdupSettings>() {
        return Err(invalid(
            "settings.struct_size is too small; use dsdup_settings_init",
        ));
    }
    // SAFETY: at least size_of::<DsdupSettings>() readable bytes (checked above).
    Ok(unsafe { s.read_unaligned() })
}

fn options_of(s: &DsdupSettings) -> Result<Options, Fail> {
    let mut o = Options::new(output_of(s.output)?);
    o.order = s.order as usize;
    o.band = match s.band {
        DSDUP_BAND_AUDIO => Band::Audio,
        v => {
            return Err(invalid(format!(
                "band {v}: only 0 (audio) is supported; 1 is reserved for a later release"
            )))
        }
    };
    o.cutoff = match s.cutoff {
        0 => None,
        30 => Some(Cutoff::Low),
        40 => Some(Cutoff::Standard),
        80 => Some(Cutoff::Wide),
        v => return Err(invalid(format!("cutoff {v}: 0, 30, 40 or 80"))),
    };
    o.gain_db = s.gain_db;
    o.input_limit = (s.input_limit != 0.0).then_some(s.input_limit);
    o.dither = s.dither != 0;
    o.threads = s.threads != 0;
    Ok(o)
}

/// # Safety
/// `p` is NULL or a NUL-terminated string.
unsafe fn path(p: *const c_char, what: &str) -> Result<PathBuf, Fail> {
    if p.is_null() {
        return Err(null(what));
    }
    // SAFETY: non-NULL and NUL-terminated (caller contract); only read during the call.
    let c = unsafe { CStr::from_ptr(p) };
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        Ok(PathBuf::from(std::ffi::OsStr::from_bytes(c.to_bytes())))
    }
    #[cfg(not(unix))]
    {
        c.to_str()
            .map(PathBuf::from)
            .map_err(|_| invalid(format!("{what} is not UTF-8")))
    }
}

fn counters(c: &Counters) -> DsdupCounters {
    DsdupCounters {
        limited: c.limited,
        clipped: c.clipped,
        resets: c.resets,
    }
}

/// Library version. Static.
#[no_mangle]
pub extern "C" fn dsdup_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr().cast()
}

/// The last error on this thread.
#[no_mangle]
pub extern "C" fn dsdup_last_error() -> *const c_char {
    LAST_ERROR.with(|e| e.borrow().as_ptr())
}

/// Copies `value` into the caller's struct of `size` bytes: zeros the whole range first,
/// then copies this version's struct over its start, so fields of a newer header that this
/// version does not know read 0 (and no byte keeps the caller's old contents, padding or
/// not). Refuses a struct smaller than this version's (`what` names it) unwritten.
///
/// # Safety
/// `dst` is non-NULL and writable for `size` bytes.
unsafe fn write_sized<T: Copy>(
    dst: *mut T,
    size: usize,
    value: &T,
    what: &str,
) -> Result<(), Fail> {
    let ours = std::mem::size_of::<T>();
    if size < ours {
        return Err(invalid(format!(
            "{what}: size {size} is smaller than this library's {ours}"
        )));
    }
    let dst = dst.cast::<u8>();
    // SAFETY: `dst` is writable for `size >= ours` bytes (caller contract), `value` is
    // `ours` readable bytes, and the two cannot overlap (`value` is the library's own copy).
    unsafe {
        std::ptr::write_bytes(dst, 0, size);
        std::ptr::copy_nonoverlapping((value as *const T).cast::<u8>(), dst, ours);
    }
    Ok(())
}

/// `dsdup_settings_init` (a macro in the header) passes `sizeof(dsdup_settings)` as `size`.
///
/// # Safety
/// `settings` is NULL or writable for `size` bytes.
#[no_mangle]
pub unsafe extern "C" fn dsdup_settings_init_sized(
    settings: *mut DsdupSettings,
    size: usize,
    output: u32,
) -> i32 {
    guard(|| {
        if settings.is_null() {
            return Err(null("settings"));
        }
        let d = defaults(output)?;
        // SAFETY: non-NULL and writable for `size` bytes (caller contract).
        unsafe { write_sized(settings, size, &d, "settings") }
    })
}

/// `dsdup_convert_file` (a macro in the header) passes `sizeof(dsdup_report)` as
/// `report_size`.
///
/// # Safety
/// Pointers as documented in the header; `report` is NULL or writable for `report_size`
/// bytes.
#[no_mangle]
pub unsafe extern "C" fn dsdup_convert_file_sized(
    in_path: *const c_char,
    out_path: *const c_char,
    settings: *const DsdupSettings,
    progress: DsdupProgressFn,
    user: *mut c_void,
    report: *mut DsdupReport,
    report_size: usize,
) -> i32 {
    guard(|| {
        // SAFETY: caller contract for each pointer.
        let (inp, out, st) = unsafe {
            (
                path(in_path, "in_path")?,
                path(out_path, "out_path")?,
                self::settings(settings)?,
            )
        };
        let o = options_of(&st)?;
        // A report too small is refused before any work.
        if !report.is_null() && report_size < std::mem::size_of::<DsdupReport>() {
            return Err(invalid(format!(
                "report: size {report_size} is smaller than this library's {}",
                std::mem::size_of::<DsdupReport>()
            )));
        }
        let file = FileOutput {
            no_overwrite: st.no_overwrite != 0,
            ..FileOutput::default()
        };
        let mut cb = |done: u64, total: u64| match progress {
            // SAFETY: a caller-supplied C function with this signature.
            Some(f) => unsafe { f(user, done, total) != 0 },
            None => true,
        };
        let rep = convert_file_to(&inp, &out, &o, &file, Some(&mut cb))?;
        if !report.is_null() {
            let mut r = DsdupReport {
                in_rate: rep.in_rate,
                out_rate: rep.out_rate,
                seconds: rep.seconds,
                out_samples: rep.out_samples,
                channels: rep.counters.len().max(rep.pcm_clipped.len()) as u32,
                ..DsdupReport::default()
            };
            for (d, c) in r.counters.iter_mut().zip(&rep.counters) {
                *d = counters(c);
            }
            for (d, c) in r.pcm_clipped.iter_mut().zip(&rep.pcm_clipped) {
                *d = *c;
            }
            // SAFETY: non-NULL and writable for `report_size` bytes (caller contract).
            unsafe { write_sized(report, report_size, &r, "report")? };
        }
        Ok(())
    })
}

/// A stream handle. Entry points take it by shared reference only: `busy` marks a call in
/// progress, so a call made from inside the output callback (reentrancy) is refused with
/// `DSDUP_ERR_BUSY` before it can touch `inner`, and `dsdup_stream_free` from inside the
/// callback is deferred until the outermost call returns. `Cell` suffices because a stream
/// is used by one thread at a time (header contract).
pub struct DsdupStream {
    busy: Cell<bool>,
    free_requested: Cell<bool>,
    /// `Stream::delay`, fixed at creation. Kept outside `inner` so that
    /// `dsdup_stream_delay` can read it from inside the output callback: it is read through
    /// a raw pointer to this field alone, never written after creation, and disjoint from
    /// `inner`, so the read does not alias the `&mut Inner` that the outer call holds.
    delay: u64,
    inner: UnsafeCell<Inner>,
}

struct Inner {
    stream: Stream,
    output: OutputCb,
    user: *mut c_void,
}

type OutputCb = unsafe extern "C" fn(*mut c_void, *const *const u8, u32, usize) -> i32;

/// Calls the output callback; an error if it asks to stop. Once `dsdup_stream_free` has
/// been called from a callback (`freed`), the callback is never called again: the host may
/// have freed `user` with the stream, so the rest of the call stops as if cancelled.
fn emit(
    output: OutputCb,
    user: *mut c_void,
    freed: &Cell<bool>,
    chans: &[Vec<u8>],
) -> dsd_upsample::Result<()> {
    if freed.get() {
        return Err(dsd_upsample::cancelled());
    }
    let ptrs: Vec<*const u8> = chans.iter().map(|c| c.as_ptr()).collect();
    // SAFETY: a caller-supplied C function with this signature; the pointers are valid
    // for `len` bytes each for the duration of the call.
    let r = unsafe {
        output(
            user,
            ptrs.as_ptr(),
            ptrs.len() as u32,
            chans.first().map_or(0, Vec::len),
        )
    };
    if r == 0 && !freed.get() {
        Ok(())
    } else {
        Err(dsd_upsample::cancelled())
    }
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_new(
    settings: *const DsdupSettings,
    input_kind: u32,
    input_rate: u32,
    channels: u32,
    output: DsdupOutputFn,
    user: *mut c_void,
    stream: *mut *mut DsdupStream,
) -> i32 {
    guard(|| {
        if stream.is_null() {
            return Err(null("stream"));
        }
        // SAFETY: non-NULL and writable (caller contract); cleared first so that the
        // caller never sees a stale pointer after an error.
        unsafe { stream.write_unaligned(std::ptr::null_mut()) };
        let output = output.ok_or_else(|| null("output"))?;
        // SAFETY: caller contract.
        let o = unsafe { options(settings)? };
        if !matches!(o.output, Output::Dsd { .. }) {
            return Err(Fail(
                DSDUP_ERR_UNSUPPORTED,
                "streams produce DSD; PCM output is for files".into(),
            ));
        }
        let fmt = match input_kind {
            DSDUP_IN_DSD => InputFormat::Dsd { rate: input_rate },
            DSDUP_IN_PCM => InputFormat::Pcm { rate: input_rate },
            v => {
                return Err(invalid(format!(
                    "input_kind {v}: DSDUP_IN_DSD or DSDUP_IN_PCM"
                )))
            }
        };
        let ch = u16::try_from(channels).map_err(|_| invalid("too many channels"))?;
        let s = Stream::new(fmt, ch, &o)?;
        let b = Box::new(DsdupStream {
            busy: Cell::new(false),
            free_requested: Cell::new(false),
            delay: s.delay(),
            inner: UnsafeCell::new(Inner {
                stream: s,
                output,
                user,
            }),
        });
        // SAFETY: as above.
        unsafe { stream.write_unaligned(Box::into_raw(b)) };
        Ok(())
    })
}

/// Clears `busy` when a call ends, and frees the stream if `dsdup_stream_free` was called
/// during it. Holds a raw pointer: no reference to the stream outlives the free.
struct Exit(*mut DsdupStream);

impl Drop for Exit {
    fn drop(&mut self) {
        // SAFETY: the stream is alive until this drop (a free during the call was deferred).
        let h = unsafe { &*self.0 };
        h.busy.set(false);
        if h.free_requested.get() {
            // SAFETY: from Box::into_raw, freed exactly once: here, because the free was
            // deferred; no reference to it is used after this point.
            drop(unsafe { Box::from_raw(self.0) });
        }
    }
}

/// Runs `f` on the stream, refusing reentrant calls. `f` gets the stream's free flag for
/// [`emit`]. `Ok(None)`: `dsdup_stream_free` was called from the output callback during the
/// call; whatever `f` returned is dropped and the call returns `DSDUP_OK` (the header
/// contract), without writing any output parameter.
///
/// # Safety
/// `s` is NULL or from `dsdup_stream_new` and not freed.
unsafe fn with_stream<R>(
    s: *mut DsdupStream,
    f: impl FnOnce(&mut Inner, &Cell<bool>) -> Result<R, Fail>,
) -> Result<Option<R>, Fail> {
    if s.is_null() {
        return Err(null("stream"));
    }
    {
        // SAFETY: alive (caller contract); only the Cells are touched here.
        let h = unsafe { &*s };
        if h.busy.get() || h.free_requested.get() {
            return Err(Fail(
                DSDUP_ERR_BUSY,
                "the stream is in use (a call from inside its callback?)".into(),
            ));
        }
        h.busy.set(true);
    }
    let _exit = Exit(s);
    // SAFETY: `busy` is set, so no other entry point creates a reference to `inner` until
    // `_exit` drops, and the stream is not freed before then.
    let (inner, freed) = unsafe { (&mut *(*s).inner.get(), &(*s).free_requested) };
    let r = f(inner, freed);
    if freed.get() {
        return Ok(None);
    }
    r.map(Some)
}

/// # Safety
/// `chans` is NULL or holds `n` pointers, each NULL or readable for `len` elements.
unsafe fn channel_slices<'a, T>(
    chans: *const *const T,
    n: usize,
    len: usize,
) -> Result<Vec<&'a [T]>, Fail> {
    if chans.is_null() {
        return Err(null("channels"));
    }
    if len > isize::MAX as usize / std::mem::size_of::<T>() {
        return Err(invalid("length too large"));
    }
    // SAFETY: `n` pointers (caller contract).
    let ptrs = unsafe { std::slice::from_raw_parts(chans, n) };
    ptrs.iter()
        .map(|&p| {
            if p.is_null() {
                Err(null("a channel pointer"))
            } else if len == 0 {
                Ok(&[][..])
            } else {
                // SAFETY: readable for `len` elements (caller contract), for this call.
                Ok(unsafe { std::slice::from_raw_parts(p, len) })
            }
        })
        .collect()
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_push_dsd(
    stream: *mut DsdupStream,
    channels: *const *const u8,
    bytes: usize,
) -> i32 {
    guard(|| {
        // SAFETY: caller contract.
        unsafe {
            with_stream(stream, |s, freed| {
                // SAFETY: caller contract; one pointer per channel of the stream.
                let chans = channel_slices(channels, s.stream.channels(), bytes)?;
                let (output, user) = (s.output, s.user);
                s.stream
                    .push_dsd(&chans, &mut |b| emit(output, user, freed, b))?;
                Ok(())
            })
            .map(drop)
        }
    })
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_push_pcm(
    stream: *mut DsdupStream,
    channels: *const *const f64,
    frames: usize,
) -> i32 {
    guard(|| {
        // SAFETY: caller contract.
        unsafe {
            with_stream(stream, |s, freed| {
                // SAFETY: caller contract; one pointer per channel of the stream.
                let chans = channel_slices(channels, s.stream.channels(), frames)?;
                let (output, user) = (s.output, s.user);
                s.stream
                    .push_pcm(&chans, &mut |b| emit(output, user, freed, b))?;
                Ok(())
            })
            .map(drop)
        }
    })
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_finish(
    stream: *mut DsdupStream,
    out_samples: *mut u64,
) -> i32 {
    guard(|| {
        // SAFETY: caller contract.
        let n = unsafe {
            with_stream(stream, |s, freed| {
                let (output, user) = (s.output, s.user);
                Ok(s.stream.finish(&mut |b| emit(output, user, freed, b))?)
            })?
        };
        if let (Some(n), false) = (n, out_samples.is_null()) {
            // SAFETY: non-NULL and writable (caller contract).
            unsafe { out_samples.write_unaligned(n) };
        }
        Ok(())
    })
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_finish_exact(
    stream: *mut DsdupStream,
    input_samples: u64,
    out_samples: *mut u64,
) -> i32 {
    guard(|| {
        // SAFETY: caller contract.
        let n = unsafe {
            with_stream(stream, |s, freed| {
                let (output, user) = (s.output, s.user);
                Ok(s.stream
                    .finish_exact(input_samples, &mut |b| emit(output, user, freed, b))?)
            })?
        };
        if let (Some(n), false) = (n, out_samples.is_null()) {
            // SAFETY: non-NULL and writable (caller contract).
            unsafe { out_samples.write_unaligned(n) };
        }
        Ok(())
    })
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_delay(stream: *const DsdupStream, delay: *mut u64) -> i32 {
    guard(|| {
        if delay.is_null() {
            return Err(null("delay"));
        }
        if stream.is_null() {
            return Err(null("stream"));
        }
        // SAFETY: alive (caller contract; a free from a callback is deferred to the end of
        // the outer call, so the stream is alive during the callback too). Allowed from
        // inside the output callback: this reads the immutable `delay` field through a raw
        // pointer, without creating a reference to the handle or to `inner`, so it cannot
        // alias the `&mut Inner` held by the call that runs the callback.
        let d = unsafe { std::ptr::addr_of!((*stream).delay).read() };
        // SAFETY: non-NULL and writable (caller contract).
        unsafe { delay.write_unaligned(d) };
        Ok(())
    })
}

/// # Safety
/// Pointers as documented in the header.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_counters(
    stream: *const DsdupStream,
    channel: u32,
    out: *mut DsdupCounters,
) -> i32 {
    guard(|| {
        if out.is_null() {
            return Err(null("counters"));
        }
        // SAFETY: caller contract; the handle is only read through `with_stream`.
        let c = unsafe { with_stream(stream.cast_mut(), |s, _| Ok(s.stream.counters()))? }
            .ok_or_else(|| Fail(DSDUP_ERR_INTERNAL, "stream freed".into()))?;
        let c = c
            .get(channel as usize)
            .ok_or_else(|| invalid(format!("channel {channel} out of range")))?;
        // SAFETY: non-NULL and writable (caller contract).
        unsafe { out.write_unaligned(counters(c)) };
        Ok(())
    })
}

/// # Safety
/// `stream` is NULL or from `dsdup_stream_new` and not yet freed.
#[no_mangle]
pub unsafe extern "C" fn dsdup_stream_free(stream: *mut DsdupStream) {
    if stream.is_null() {
        return;
    }
    // A panic in a destructor must not cross the boundary.
    let _ = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: alive (caller contract); only the Cells are touched.
        let h = unsafe { &*stream };
        if h.busy.get() {
            // Called from inside the stream's callback: the outermost call frees it.
            h.free_requested.set(true);
        } else {
            // SAFETY: from Box::into_raw in dsdup_stream_new, freed once (caller contract).
            drop(unsafe { Box::from_raw(stream) });
        }
    }));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static CALLS: AtomicUsize = AtomicUsize::new(0);

    unsafe extern "C" fn count(_: *mut c_void, _: *const *const u8, _: u32, _: usize) -> i32 {
        CALLS.fetch_add(1, Ordering::SeqCst);
        0
    }

    /// Once a free is requested, `emit` never calls the callback again.
    #[test]
    fn emit_stops_after_a_free_request() {
        let freed = Cell::new(false);
        let chans = vec![vec![0x69u8; 4]; 2];
        let before = CALLS.load(Ordering::SeqCst);
        assert!(emit(count, std::ptr::null_mut(), &freed, &chans).is_ok());
        assert_eq!(CALLS.load(Ordering::SeqCst), before + 1);
        freed.set(true);
        let r = emit(count, std::ptr::null_mut(), &freed, &chans);
        assert!(r.is_err_and(|e| is_cancelled(&e)));
        assert_eq!(CALLS.load(Ordering::SeqCst), before + 1);
    }

    /// Per-test state for the free-in-callback test: the stream and calls seen.
    struct Ctx {
        stream: *mut DsdupStream,
        free_on_call: bool,
        calls: usize,
        calls_after_free: usize,
        freed: bool,
    }

    unsafe extern "C" fn free_in_cb(
        user: *mut c_void,
        _: *const *const u8,
        _: u32,
        _: usize,
    ) -> i32 {
        // SAFETY: `user` is the test's `Ctx`, alive for the whole test (it is not freed
        // here, so a call after the free is counted instead of being a use after free).
        let c = unsafe { &mut *user.cast::<Ctx>() };
        c.calls += 1;
        if c.freed {
            c.calls_after_free += 1;
        } else if c.free_on_call {
            c.freed = true;
            // SAFETY: the stream from dsdup_stream_new; freed once.
            unsafe { dsdup_stream_free(c.stream) };
        }
        0
    }

    fn settings(output: u32) -> DsdupSettings {
        let mut s = std::mem::MaybeUninit::<DsdupSettings>::uninit();
        // SAFETY: writable for its size.
        let r = unsafe {
            dsdup_settings_init_sized(s.as_mut_ptr(), std::mem::size_of::<DsdupSettings>(), output)
        };
        assert_eq!(r, DSDUP_OK);
        // SAFETY: initialised by the call above.
        unsafe { s.assume_init() }
    }

    /// Feeds `input_kind` input and finishes, freeing in the first callback of finish when
    /// `free`; returns the calls during finish, those after the free, the status and
    /// `out_samples`.
    fn finish_with(free: bool, input_kind: u32, rate: u32, out: u32) -> (usize, usize, i32, u64) {
        let s = settings(out);
        let mut ctx = Ctx {
            stream: std::ptr::null_mut(),
            free_on_call: false,
            calls: 0,
            calls_after_free: 0,
            freed: false,
        };
        let user = std::ptr::addr_of_mut!(ctx).cast::<c_void>();
        let mut st = std::ptr::null_mut();
        // SAFETY: valid pointers for the call.
        let r =
            unsafe { dsdup_stream_new(&s, input_kind, rate, 2, Some(free_in_cb), user, &mut st) };
        assert_eq!(r, DSDUP_OK);
        // SAFETY: the context outlives the stream; written before any callback.
        unsafe { (*user.cast::<Ctx>()).stream = st };
        let r = if input_kind == DSDUP_IN_DSD {
            let b = [0x69u8; 1000];
            let ch = [b.as_ptr(), b.as_ptr()];
            // SAFETY: two channels of 1000 bytes.
            unsafe { dsdup_stream_push_dsd(st, ch.as_ptr(), b.len()) }
        } else {
            let x = [0.1f64; 1000];
            let ch = [x.as_ptr(), x.as_ptr()];
            // SAFETY: two channels of 1000 frames.
            unsafe { dsdup_stream_push_pcm(st, ch.as_ptr(), x.len()) }
        };
        assert_eq!(r, DSDUP_OK);
        // SAFETY: as above; no callback runs between these accesses.
        unsafe {
            (*user.cast::<Ctx>()).free_on_call = free;
            (*user.cast::<Ctx>()).calls = 0;
        }
        let mut n = 12345u64;
        // SAFETY: the stream is alive; `n` is writable.
        let r = unsafe { dsdup_stream_finish(st, &mut n) };
        // SAFETY: as above.
        let c = unsafe { &*user.cast::<Ctx>() };
        let (calls, after) = (c.calls, c.calls_after_free);
        if !free {
            // SAFETY: not freed by the callback.
            unsafe { dsdup_stream_free(st) };
        }
        (calls, after, r, n)
    }

    /// A free from the output callback during finish: no further callback, DSDUP_OK, and
    /// out_samples is not written.
    #[test]
    fn no_callback_after_free_in_finish() {
        for (kind, rate, out) in [
            (DSDUP_IN_DSD, 2_822_400, DSDUP_OUT_DSD256),
            (DSDUP_IN_DSD, 11_289_600, DSDUP_OUT_DSD128),
            (DSDUP_IN_PCM, 44_100, DSDUP_OUT_DSD256),
            (DSDUP_IN_PCM, 352_800, DSDUP_OUT_DSD64),
        ] {
            let (calls, _, r, n) = finish_with(false, kind, rate, out);
            assert_eq!(r, DSDUP_OK);
            assert_ne!(n, 12345);
            eprintln!("kind {kind} rate {rate} out {out}: finish emits {calls} time(s)");
            assert!(calls >= 1);
            let (calls, after, r, n) = finish_with(true, kind, rate, out);
            assert_eq!((calls, after, r, n), (1, 0, DSDUP_OK, 12345));
        }
    }

    /// What the output callback sees when it queries its own stream.
    struct Query {
        stream: *mut DsdupStream,
        calls: usize,
        delays: Vec<(i32, u64)>,
        counters: Vec<i32>,
    }

    unsafe extern "C" fn query_in_cb(
        user: *mut c_void,
        _: *const *const u8,
        _: u32,
        _: usize,
    ) -> i32 {
        // SAFETY: `user` is the test's `Query`, alive for the whole test.
        let q = unsafe { &mut *user.cast::<Query>() };
        q.calls += 1;
        let mut d = 0u64;
        // SAFETY: the stream is alive (the call that runs this callback is in progress).
        let r = unsafe { dsdup_stream_delay(q.stream, &mut d) };
        q.delays.push((r, d));
        let mut k = DsdupCounters::default();
        // SAFETY: as above.
        q.counters
            .push(unsafe { dsdup_stream_counters(q.stream, 0, &mut k) });
        0
    }

    /// From inside the output callback, dsdup_stream_delay works (and gives the same value
    /// as outside) and dsdup_stream_counters returns BUSY. Run under Miri, this also checks
    /// that the delay read does not alias the `&mut Inner` of the outer call.
    #[test]
    fn queries_from_the_callback() {
        let s = settings(DSDUP_OUT_DSD128);
        let mut q = Query {
            stream: std::ptr::null_mut(),
            calls: 0,
            delays: Vec::new(),
            counters: Vec::new(),
        };
        let user = std::ptr::addr_of_mut!(q).cast::<c_void>();
        let mut st = std::ptr::null_mut();
        // SAFETY: valid pointers for the call.
        let r = unsafe {
            dsdup_stream_new(
                &s,
                DSDUP_IN_DSD,
                2_822_400,
                1,
                Some(query_in_cb),
                user,
                &mut st,
            )
        };
        assert_eq!(r, DSDUP_OK);
        // SAFETY: written before any callback; the Query outlives the stream.
        unsafe { (*user.cast::<Query>()).stream = st };
        let mut outside = 0u64;
        // SAFETY: the stream is alive.
        assert_eq!(unsafe { dsdup_stream_delay(st, &mut outside) }, DSDUP_OK);
        assert!(outside > 0);
        let b = [0x69u8; 256];
        let ch = [b.as_ptr()];
        // SAFETY: one channel of 256 bytes.
        assert_eq!(
            unsafe { dsdup_stream_push_dsd(st, ch.as_ptr(), b.len()) },
            DSDUP_OK
        );
        // SAFETY: the stream is alive.
        assert_eq!(
            unsafe { dsdup_stream_finish(st, std::ptr::null_mut()) },
            DSDUP_OK
        );
        let mut k = DsdupCounters::default();
        // SAFETY: the stream is alive; not inside a callback any more.
        assert_eq!(unsafe { dsdup_stream_counters(st, 0, &mut k) }, DSDUP_OK);
        // SAFETY: from dsdup_stream_new, freed once.
        unsafe { dsdup_stream_free(st) };
        // SAFETY: no callback runs any more.
        let q = unsafe { &*user.cast::<Query>() };
        assert!(q.calls >= 1);
        assert!(q.delays.iter().all(|&d| d == (DSDUP_OK, outside)));
        assert!(q.counters.iter().all(|&r| r == DSDUP_ERR_BUSY));
    }

    /// The library writes exactly the caller's size: its own struct, then zeros for
    /// fields it does not know; a struct smaller than its own is refused unwritten.
    #[test]
    fn sized_writes() {
        const OURS: usize = std::mem::size_of::<DsdupSettings>();
        let mut buf = [0xabu8; OURS + 32];
        // SAFETY: `buf` is writable for OURS + 16 bytes (and more).
        let r = unsafe {
            dsdup_settings_init_sized(buf.as_mut_ptr().cast(), OURS + 16, DSDUP_OUT_DSD128)
        };
        assert_eq!(r, DSDUP_OK);
        assert_eq!(&buf[..4], &(OURS as u32).to_ne_bytes());
        assert!(buf[OURS..OURS + 16].iter().all(|&b| b == 0));
        assert!(buf[OURS + 16..].iter().all(|&b| b == 0xab));
        let mut small = [0xabu8; OURS + 32];
        // SAFETY: writable for OURS - 4 bytes.
        let r = unsafe {
            dsdup_settings_init_sized(small.as_mut_ptr().cast(), OURS - 4, DSDUP_OUT_DSD128)
        };
        assert_eq!(r, DSDUP_ERR_INVALID_ARGUMENT);
        assert!(small.iter().all(|&b| b == 0xab));
        // every byte of the struct is written: garbage and zeros before give the same bytes
        let (mut a, mut z) = ([0xcdu8; OURS], [0u8; OURS]);
        for b in [&mut a, &mut z] {
            // SAFETY: writable for OURS bytes.
            let r = unsafe { dsdup_settings_init_sized(b.as_mut_ptr().cast(), OURS, 128) };
            assert_eq!(r, DSDUP_OK);
        }
        assert_eq!(a, z);
        assert_eq!(&a[44..48], &[0; 4]);
    }

    /// `band`: 0 (the default) is accepted; 1 (reserved) and anything else are refused.
    #[test]
    fn band_values() {
        let mut s = settings(DSDUP_OUT_DSD128);
        assert_eq!(s.band, DSDUP_BAND_AUDIO);
        assert!(options_of(&s).is_ok_and(|o| o.band == Band::Audio));
        for v in [1, 2, u32::MAX] {
            s.band = v;
            assert!(options_of(&s).is_err_and(|f| f.0 == DSDUP_ERR_INVALID_ARGUMENT));
        }
    }
}
