/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/*
 * C interface of dsd-upsample: DSF, DFF, WAV or FLAC files (or streamed DSD/PCM) in,
 * DSD64 (from PCM), DSD128 or DSD256 out (and 24-bit PCM WAV from DSD64 for whole files).
 *
 * Conventions
 * - Every function returning int32_t returns a dsdup_status; on an error,
 *   dsdup_last_error() describes it.
 * - Paths are NUL-terminated: raw bytes on POSIX systems, UTF-8 on Windows.
 * - No function keeps a pointer it was given beyond the call, except the callback and its
 *   user pointer passed to dsdup_stream_new, which are kept until dsdup_stream_free.
 * - Callbacks run on the calling thread, inside the call that triggers them. A call into
 *   the same stream from its output callback returns DSDUP_ERR_BUSY (this includes
 *   dsdup_stream_counters), except dsdup_stream_delay, which works there, and
 *   dsdup_stream_free, which then frees the stream when the outer call returns. No
 *   callback follows that free: the outer call stops producing output, returns DSDUP_OK
 *   and leaves its output parameters (such as out_samples) unwritten, so the callback may
 *   free its user data together with the stream. Do not use the stream afterwards.
 * - Callbacks must return normally: they must not throw a C++ exception, longjmp out of
 *   the library or otherwise unwind through it (unwinding through the library aborts the
 *   process). Catch everything inside the callback and return the stop value instead.
 * - A stream may be used from any thread, by one thread at a time.
 * - ABI evolution: within ABI version 1, later versions only add functions, constants and
 *   fields at the end of dsdup_settings and dsdup_report. The library learns the size of
 *   every struct it fills from the caller (the dsdup_settings_init and dsdup_convert_file
 *   macros pass sizeof for you) and never writes past it; struct fields it does not know
 *   are set to 0, which is the default of every field added later. dsdup_counters never
 *   grows. See docs/c-api.md.
 * - DSD data is one buffer per channel, MSB-first: the earliest sample is bit 7, 1 = +1.
 */
#ifndef DSD_UPSAMPLE_H
#define DSD_UPSAMPLE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DSDUP_ABI_VERSION 1

/* Status codes. */
#define DSDUP_OK 0
#define DSDUP_ERR_INVALID_ARGUMENT 1 /* a setting or argument is out of range */
#define DSDUP_ERR_UNSUPPORTED 2      /* valid, but not supported by this version */
#define DSDUP_ERR_FORMAT 3           /* the input file is not valid */
#define DSDUP_ERR_IO 4               /* reading or writing failed */
#define DSDUP_ERR_CANCELLED 5        /* a callback asked to stop */
#define DSDUP_ERR_NULL 6             /* a required pointer is NULL */
#define DSDUP_ERR_INTERNAL 7         /* a bug in the library; please report it */
#define DSDUP_ERR_BUSY 8             /* the stream is in a call (from its own callback) */
#define DSDUP_ERR_EXISTS 9           /* no_overwrite is set and the output exists */

/* Outputs (dsdup_settings.output). */
#define DSDUP_OUT_DSD64 64 /* PCM input only */
#define DSDUP_OUT_DSD128 128
#define DSDUP_OUT_DSD256 256
#define DSDUP_OUT_PCM88 1  /* 88.2 kHz, 24-bit WAV, DSD64 input, files only */
#define DSDUP_OUT_PCM176 2 /* 176.4 kHz */
#define DSDUP_OUT_PCM352 3 /* 352.8 kHz */

/* DSD64 decimator (dsdup_settings.cutoff). */
#define DSDUP_CUTOFF_DEFAULT 0 /* DSD output: 140 dB Kaiser; PCM output: 40 kHz */
#define DSDUP_CUTOFF_30 30
#define DSDUP_CUTOFF_40 40
#define DSDUP_CUTOFF_WIDE 80

/* Noise-shaping band of the modulator (DSD output). This release has one band; the value 1
 * is reserved for a later release and refused, like every other value. */
#define DSDUP_BAND_AUDIO 0 /* zeros over 0-20 kHz (default) */

/* Stream input kinds. */
#define DSDUP_IN_DSD 0
#define DSDUP_IN_PCM 1

/* Settings. Initialise with dsdup_settings_init, then change fields (never struct_size). Code that fills the struct by hand must zero it first (memset) and set
 * struct_size to sizeof(dsdup_settings). Later versions may add fields at the end. */
typedef struct dsdup_settings {
    uint32_t struct_size; /* set by dsdup_settings_init; tells the library the struct's size */
    uint32_t output;      /* DSDUP_OUT_* */
    uint32_t order;       /* modulator order, 5 to 8, DSD128 output 5 to 7 (default 6) */
    uint32_t cutoff;      /* DSDUP_CUTOFF_* */
    double gain_db;       /* -120 to +24 (default -6 for DSD output, 0 for PCM). The default
                             leaves 6 dB of headroom: PCM true peaks up to +6 dBTP and DSD
                             up to 100 % modulation are not limited. A higher gain is
                             louder; samples above the limit are limited and counted
                             (dsdup_counters.limited). */
    double input_limit;   /* modulator input limit, (0, 1]; 0 = default (0.51) */
    uint32_t dither;      /* nonzero: TPDF dither before the modulator */
    uint32_t threads;     /* nonzero (default): use several threads (files only) */
    uint32_t no_overwrite; /* nonzero: dsdup_convert_file fails with DSDUP_ERR_EXISTS if the
                              output exists (created atomically otherwise) */
    uint32_t band;         /* DSDUP_BAND_AUDIO (0, the default and the only band of this
                              release); any other value is refused with
                              DSDUP_ERR_INVALID_ARGUMENT */
} dsdup_settings;

/* Overload counters of one channel. Fixed: this struct never grows. */
typedef struct dsdup_counters {
    uint64_t limited; /* input samples limited */
    uint64_t clipped; /* samples with clipped modulator states */
    uint64_t resets;  /* modulator resets */
} dsdup_counters;

#define DSDUP_MAX_CHANNELS 6

/* Result of a file conversion. Later versions may add fields at the end. */
typedef struct dsdup_report {
    uint32_t in_rate;
    uint32_t out_rate;
    double seconds;       /* input duration */
    uint64_t out_samples; /* per channel */
    uint32_t channels;
    uint32_t reserved;    /* always 0 */
    dsdup_counters counters[DSDUP_MAX_CHANNELS]; /* DSD output */
    uint64_t pcm_clipped[DSDUP_MAX_CHANNELS];     /* PCM output: samples clamped to 24 bits */
} dsdup_report;

/* The structs have no implicit padding on any target (every byte is a field, so the library
 * writes every byte and a field added later changes sizeof); checked where the compiler
 * can (C11, C++11). */
#if defined(__cplusplus) && \
    (__cplusplus >= 201103L || (defined(_MSVC_LANG) && _MSVC_LANG >= 201103L))
#define DSDUP_STATIC_ASSERT_(cond, msg) static_assert(cond, msg)
#elif !defined(__cplusplus) && defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
#define DSDUP_STATIC_ASSERT_(cond, msg) _Static_assert(cond, msg)
#endif
#ifdef DSDUP_STATIC_ASSERT_
DSDUP_STATIC_ASSERT_(sizeof(dsdup_settings) == 48, "dsdup_settings layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_settings, gain_db) == 16, "dsdup_settings layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_settings, dither) == 32, "dsdup_settings layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_settings, band) == 44, "dsdup_settings layout");
DSDUP_STATIC_ASSERT_(sizeof(dsdup_counters) == 24, "dsdup_counters layout");
DSDUP_STATIC_ASSERT_(sizeof(dsdup_report) == 224, "dsdup_report layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_report, seconds) == 8, "dsdup_report layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_report, reserved) == 28, "dsdup_report layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_report, counters) == 32, "dsdup_report layout");
DSDUP_STATIC_ASSERT_(offsetof(dsdup_report, pcm_clipped) == 176, "dsdup_report layout");
#undef DSDUP_STATIC_ASSERT_
#endif

/* Progress: output samples done and total per channel. Return 0 to cancel. */
typedef int32_t (*dsdup_progress_fn)(void *user, uint64_t done, uint64_t total);

/* Stream output: one buffer of `bytes` bytes per channel. Return 0 to continue, anything
 * else to stop: the call that produced the output then returns DSDUP_ERR_CANCELLED. It may
 * call dsdup_stream_free on its own stream (see Conventions); it is then not called again. */
typedef int32_t (*dsdup_output_fn)(void *user, const uint8_t *const *channels,
                                   uint32_t n_channels, size_t bytes);

typedef struct dsdup_stream dsdup_stream;

/* Library version, e.g. "0.1.0". Static; never free. */
const char *dsdup_version(void);

/* The message of the last error on this thread, or "" if none. Valid until the next call
 * into the library on this thread. */
const char *dsdup_last_error(void);

/* Default settings for `output` (DSDUP_OUT_*):
 *     int32_t dsdup_settings_init(dsdup_settings *settings, uint32_t output);
 * A macro that passes sizeof(dsdup_settings) to dsdup_settings_init_sized, which fills
 * `size` bytes. Bindings that cannot use the macro call dsdup_settings_init_sized with the
 * size of their struct (at least the size of ABI 1.0's). */
int32_t dsdup_settings_init_sized(dsdup_settings *settings, size_t size, uint32_t output);
#define dsdup_settings_init(settings, output) \
    dsdup_settings_init_sized((settings), sizeof(dsdup_settings), (output))

/* Converts a whole file (DSF, DFF, WAV or FLAC):
 *     int32_t dsdup_convert_file(const char *in_path, const char *out_path,
 *                                const dsdup_settings *settings, dsdup_progress_fn progress,
 *                                void *user, dsdup_report *report);
 * The output format follows the extension (.dsf, .dff, .wav). `progress` and `report` may
 * be NULL; `report` is filled on success only. An output that is the input is refused.
 * The output is written to a temporary file next to it (NAME.partN.EXT) and renamed to
 * the output's name on success, so after an error or a cancel no output and no temporary
 * file are left, and an existing output is replaced only by a complete one. With
 * no_overwrite, the rename never replaces a file that appeared during the conversion
 * (DSDUP_ERR_EXISTS).
 * dsdup_convert_file is a macro that passes sizeof(dsdup_report) to
 * dsdup_convert_file_sized, which writes at most `report_size` bytes to `report`. */
int32_t dsdup_convert_file_sized(const char *in_path, const char *out_path,
                                 const dsdup_settings *settings, dsdup_progress_fn progress,
                                 void *user, dsdup_report *report, size_t report_size);
#define dsdup_convert_file(in_path, out_path, settings, progress, user, report)          \
    dsdup_convert_file_sized((in_path), (out_path), (settings), (progress), (user), \
                             (report), sizeof(dsdup_report))

/* A streaming converter to DSD64 (PCM input only), DSD128 or DSD256 for `channels` (1 to 6) channels of
 * `input_kind` (DSDUP_IN_*) at `input_rate` Hz. `output` receives the DSD output.
 * Input rates: DSD 2822400, 5644800 or 11289600; PCM 44100, 88200, 176400 or 352800, or
 * 48000, 96000, 192000 or 384000 (resampled by 147/160 to the 44.1 kHz family first;
 * dsdup_stream_delay includes the resampler's delay). Other rates: DSDUP_ERR_UNSUPPORTED. */
int32_t dsdup_stream_new(const dsdup_settings *settings, uint32_t input_kind,
                         uint32_t input_rate, uint32_t channels, dsdup_output_fn output,
                         void *user, dsdup_stream **stream);

/* Pushes `bytes` DSD bytes per channel (`channels` holds one pointer per channel). */
int32_t dsdup_stream_push_dsd(dsdup_stream *stream, const uint8_t *const *channels,
                              size_t bytes);

/* Pushes `frames` PCM samples per channel (full scale +-1.0). */
int32_t dsdup_stream_push_pcm(dsdup_stream *stream, const double *const *channels,
                              size_t frames);

/* Ends the input and emits the rest of the output; `out_samples` (may be NULL) receives
 * the output length per channel, input samples x output rate / input rate rounded down.
 * It need not be a multiple of 8 (DSD input of odd bit counts, 48 kHz-family PCM): the
 * last byte then holds the remaining samples in its high bits and idle-pattern bits
 * (0x69's) below them. No pushes afterwards. */
int32_t dsdup_stream_finish(dsdup_stream *stream, uint64_t *out_samples);

/* dsdup_stream_finish for an input of exactly `input_samples` samples per channel: for DSD
 * whose last byte is partly padding. Only that padding can be declared away: for DSD input,
 * `input_samples` must be at most the samples pushed (8 per byte) and at least the samples
 * pushed minus 7; for PCM input, it must equal the frames pushed. Otherwise the call
 * returns DSDUP_ERR_INVALID_ARGUMENT, emits nothing and leaves the stream unfinished. */
int32_t dsdup_stream_finish_exact(dsdup_stream *stream, uint64_t input_samples,
                                  uint64_t *out_samples);

/* The stream's delay in output samples (how far output lags input), for latency
 * reports. Fixed for the stream's life; may be called from inside its output callback. */
int32_t dsdup_stream_delay(const dsdup_stream *stream, uint64_t *delay);

/* Overload counters of channel `channel` so far. From inside the stream's output callback
 * this returns DSDUP_ERR_BUSY: the counters belong to the call that is producing output;
 * read them after that call returns. */
int32_t dsdup_stream_counters(const dsdup_stream *stream, uint32_t channel,
                              dsdup_counters *counters);

/* Frees a stream (NULL is ignored). From inside the stream's own output callback, the
 * free happens when the outer call returns, and the callback is not called again. */
void dsdup_stream_free(dsdup_stream *stream);

#ifdef __cplusplus
}
#endif

#endif /* DSD_UPSAMPLE_H */
