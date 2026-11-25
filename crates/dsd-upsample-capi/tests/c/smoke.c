/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/* Smoke test of the C interface: tools/c-smoke.sh builds and runs it.
 * Usage: smoke IN.dsf OUTDIR */
#include "dsd_upsample.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            fprintf(stderr, "FAIL %s:%d: %s (last error: %s)\n", __FILE__,     \
                    __LINE__, #cond, dsdup_last_error());                      \
            failures++;                                                        \
        }                                                                      \
    } while (0)

static int32_t count_progress(void *user, uint64_t done, uint64_t total) {
    int *calls = user;
    (*calls)++;
    return done <= total;
}

static int32_t cancel_at_2(void *user, uint64_t done, uint64_t total) {
    int *calls = user;
    (void)done;
    (void)total;
    return ++(*calls) < 2;
}

struct sink {
    uint64_t bytes;
    uint32_t channels;
    int stop_after;
    int calls;
};

static int32_t on_output(void *user, const uint8_t *const *ch, uint32_t n, size_t bytes) {
    struct sink *s = user;
    s->channels = n;
    for (uint32_t c = 0; c < n; c++)
        if (bytes && !ch[c]) return 1;
    s->bytes += bytes;
    s->calls++;
    return s->stop_after && s->calls >= s->stop_after;
}

/* Reentrancy: the callback calls back into its own stream. */
struct reenter {
    dsdup_stream *st;
    int mode; /* 0: push, counters and finish must be BUSY, delay works; 1: free inside */
    int busy_ok;
    int delay_ok;
    uint64_t delay;
    int calls;
};

static int32_t on_output_reenter(void *user, const uint8_t *const *ch, uint32_t n,
                                 size_t bytes) {
    struct reenter *r = user;
    (void)ch;
    (void)n;
    (void)bytes;
    r->calls++;
    if (r->mode == 0) {
        static const uint8_t b[4] = {0x69, 0x69, 0x69, 0x69};
        const uint8_t *two[2] = {b, b};
        dsdup_counters k;
        uint64_t n_out;
        r->busy_ok += dsdup_stream_push_dsd(r->st, two, 4) == DSDUP_ERR_BUSY;
        r->busy_ok += dsdup_stream_counters(r->st, 0, &k) == DSDUP_ERR_BUSY;
        r->busy_ok += dsdup_stream_finish(r->st, &n_out) == DSDUP_ERR_BUSY;
        uint64_t d = 0;
        r->delay_ok += dsdup_stream_delay(r->st, &d) == DSDUP_OK && d == r->delay;
    } else if (r->calls == 1) {
        dsdup_stream_free(r->st); /* deferred to the end of the outer call */
        r->st = NULL;
    }
    return 0;
}

/* Free in the callback, together with the user data: the library must not call the
 * callback again (ASan reports the use after free if it does). */
static int owned_frees = 0;
struct owned {
    dsdup_stream *st;
    int free_now;
};

static int32_t on_output_free_owner(void *user, const uint8_t *const *ch, uint32_t n,
                                    size_t bytes) {
    struct owned *o = user; /* a use after free if called after the free */
    (void)ch;
    (void)n;
    (void)bytes;
    if (o->free_now) {
        owned_frees++;
        dsdup_stream_free(o->st);
        free(o);
    }
    return 0;
}

/* Size of a file, or -1 if it cannot be opened. */
static long file_size(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fclose(f);
    return n;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: smoke IN.dsf OUTDIR\n");
        return 2;
    }
    char out[4096];
    printf("dsd-upsample %s, ABI %d\n", dsdup_version(), DSDUP_ABI_VERSION);

    /* settings */
    dsdup_settings s;
    CHECK(dsdup_settings_init(&s, DSDUP_OUT_DSD128) == DSDUP_OK);
    CHECK(s.struct_size == sizeof s && s.order == 6 && s.gain_db == -6.0);
    { dsdup_settings t; CHECK(dsdup_settings_init(&t, DSDUP_OUT_DSD256) == DSDUP_OK && t.order == 6); }
    CHECK(dsdup_settings_init(&s, 999) == DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(strlen(dsdup_last_error()) > 0);
    CHECK(dsdup_settings_init(NULL, DSDUP_OUT_DSD128) == DSDUP_ERR_NULL);
    CHECK(dsdup_settings_init(&s, DSDUP_OUT_DSD128) == DSDUP_OK);

    /* sized writes: the library writes exactly the caller's size, zeroing fields it does
     * not know, and refuses a struct smaller than its own without writing */
    struct {
        dsdup_settings s;
        uint8_t newer[16];
        uint8_t canary[16];
    } sz;
    memset(&sz, 0xab, sizeof sz);
    CHECK(dsdup_settings_init_sized(&sz.s, sizeof sz.s + sizeof sz.newer,
                                    DSDUP_OUT_DSD256) == DSDUP_OK);
    CHECK(sz.s.struct_size == sizeof sz.s && sz.s.output == DSDUP_OUT_DSD256);
    for (size_t i = 0; i < sizeof sz.newer; i++) CHECK(sz.newer[i] == 0);
    for (size_t i = 0; i < sizeof sz.canary; i++) CHECK(sz.canary[i] == 0xab);
    memset(&sz, 0xab, sizeof sz);
    CHECK(dsdup_settings_init_sized(&sz.s, sizeof sz.s - 8, DSDUP_OUT_DSD256) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(sz.s.struct_size == 0xabababab);

    /* every byte written: a struct prefilled with 0xCD and one prefilled with 0x00 are
     * identical after init (no byte keeps its old value, padding or not), and band is
     * 0 (DSDUP_BAND_AUDIO); band 1 (reserved) and band 2 are refused */
    {
        dsdup_settings a, z;
        memset(&a, 0xCD, sizeof a);
        memset(&z, 0x00, sizeof z);
        CHECK(dsdup_settings_init(&a, DSDUP_OUT_DSD128) == DSDUP_OK);
        CHECK(dsdup_settings_init(&z, DSDUP_OUT_DSD128) == DSDUP_OK);
        CHECK(memcmp(&a, &z, sizeof a) == 0);
        CHECK(a.band == DSDUP_BAND_AUDIO && a.struct_size == 48);
        const unsigned char *p = (const unsigned char *)&a;
        size_t cd = 0;
        for (size_t i = 0; i < sizeof a; i++) cd += p[i] == 0xCD;
        CHECK(cd == 0);
        dsdup_settings r = a;
        r.band = 2;
        dsdup_stream *rs = NULL;
        CHECK(dsdup_convert_file(argv[1], "unused.dsf", &r, NULL, NULL, NULL) ==
              DSDUP_ERR_INVALID_ARGUMENT);
        CHECK(strstr(dsdup_last_error(), "band") != NULL);
        CHECK(dsdup_stream_new(&r, DSDUP_IN_DSD, 2822400, 2, on_output, NULL, &rs) ==
              DSDUP_ERR_INVALID_ARGUMENT);
        CHECK(rs == NULL);
        r.band = 1;
        CHECK(dsdup_stream_new(&r, DSDUP_IN_DSD, 2822400, 2, on_output, NULL, &rs) ==
              DSDUP_ERR_INVALID_ARGUMENT);
        CHECK(rs == NULL);
        CHECK(strstr(dsdup_last_error(), "reserved") != NULL);
        r.band = DSDUP_BAND_AUDIO;
        CHECK(dsdup_stream_new(&r, DSDUP_IN_DSD, 2822400, 2, on_output, NULL, &rs) == DSDUP_OK);
        CHECK(rs != NULL);
        dsdup_stream_free(rs);
    }

    /* whole file, with progress and report */
    snprintf(out, sizeof out, "%s/c128.dsf", argv[2]);
    int calls = 0;
    dsdup_report rep;
    CHECK(dsdup_convert_file(argv[1], out, &s, count_progress, &calls, &rep) == DSDUP_OK);
    CHECK(calls > 0 && rep.out_rate == 5644800 && rep.channels == 2 && rep.out_samples > 0);
    CHECK(strcmp(dsdup_last_error(), "") == 0);

    /* every report byte written: prefilled with 0xCD and with 0x00, the same report */
    {
        dsdup_report a, z;
        memset(&a, 0xCD, sizeof a);
        memset(&z, 0x00, sizeof z);
        CHECK(dsdup_convert_file(argv[1], out, &s, NULL, NULL, &a) == DSDUP_OK);
        CHECK(dsdup_convert_file(argv[1], out, &s, NULL, NULL, &z) == DSDUP_OK);
        CHECK(memcmp(&a, &z, sizeof a) == 0);
        CHECK(a.reserved == 0 && a.channels == 2);
        for (uint32_t c = a.channels; c < DSDUP_MAX_CHANNELS; c++)
            CHECK(a.counters[c].limited == 0 && a.counters[c].clipped == 0 &&
                  a.counters[c].resets == 0 && a.pcm_clipped[c] == 0);
    }

    /* report sized as by a newer header: the extra bytes are zeroed, nothing beyond */
    struct {
        dsdup_report r;
        uint8_t newer[16];
        uint8_t canary[16];
    } brep;
    memset(&brep, 0xab, sizeof brep);
    CHECK(dsdup_convert_file_sized(argv[1], out, &s, NULL, NULL, &brep.r,
                                   sizeof brep.r + sizeof brep.newer) == DSDUP_OK);
    CHECK(brep.r.out_rate == 5644800 && brep.r.channels == 2);
    for (size_t i = 0; i < sizeof brep.newer; i++) CHECK(brep.newer[i] == 0);
    for (size_t i = 0; i < sizeof brep.canary; i++) CHECK(brep.canary[i] == 0xab);
    /* a report smaller than the library's is refused before any work */
    memset(&brep, 0xab, sizeof brep);
    CHECK(dsdup_convert_file_sized(argv[1], out, &s, count_progress, &calls, &brep.r,
                                   sizeof brep.r - 8) == DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(brep.r.in_rate == 0xabababab);

    /* cancel: the complete output from before survives, and no temporary file is left */
    long good = file_size(out);
    CHECK(good > 0);
    calls = 0;
    CHECK(dsdup_convert_file(argv[1], out, &s, cancel_at_2, &calls, NULL) ==
          DSDUP_ERR_CANCELLED);
    CHECK(file_size(out) == good);
    char part[4096];
    snprintf(part, sizeof part, "%s/c128.part1.dsf", argv[2]);
    CHECK(file_size(part) == -1);
    /* a cancelled new output leaves nothing */
    snprintf(part, sizeof part, "%s/cancelled.dsf", argv[2]);
    calls = 0;
    CHECK(dsdup_convert_file(argv[1], part, &s, cancel_at_2, &calls, NULL) ==
          DSDUP_ERR_CANCELLED);
    CHECK(file_size(part) == -1);
    snprintf(part, sizeof part, "%s/cancelled.part1.dsf", argv[2]);
    CHECK(file_size(part) == -1);

    /* same file, NULLs, bad settings */
    CHECK(dsdup_convert_file(argv[1], argv[1], &s, NULL, NULL, NULL) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(dsdup_convert_file(NULL, out, &s, NULL, NULL, NULL) == DSDUP_ERR_NULL);
    CHECK(dsdup_convert_file(argv[1], out, NULL, NULL, NULL, NULL) == DSDUP_ERR_NULL);
    dsdup_settings bad = s;
    bad.struct_size = 8;
    CHECK(dsdup_convert_file(argv[1], out, &bad, NULL, NULL, NULL) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    bad = s;
    bad.order = 12;
    CHECK(dsdup_convert_file(argv[1], out, &bad, NULL, NULL, NULL) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(dsdup_convert_file("/nonexistent/x.dsf", out, &s, NULL, NULL, NULL) ==
          DSDUP_ERR_IO);

    /* no_overwrite: the existing output from above is refused */
    dsdup_settings nw = s;
    nw.no_overwrite = 1;
    snprintf(out, sizeof out, "%s/c128.dsf", argv[2]);
    CHECK(dsdup_convert_file(argv[1], out, &nw, NULL, NULL, NULL) == DSDUP_ERR_EXISTS);

    /* PCM output */
    dsdup_settings p;
    CHECK(dsdup_settings_init(&p, DSDUP_OUT_PCM176) == DSDUP_OK);
    snprintf(out, sizeof out, "%s/c176.wav", argv[2]);
    CHECK(dsdup_convert_file(argv[1], out, &p, NULL, NULL, &rep) == DSDUP_OK);
    CHECK(rep.out_rate == 176400);

    /* stream: 1 s of DSD64 stereo in odd pieces, exact output length */
    dsdup_stream *st = NULL;
    struct sink sk = {0};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output, &sk, &st) == DSDUP_OK);
    static uint8_t l[352800], r[352800];
    for (size_t i = 0; i < sizeof l; i++) {
        l[i] = (uint8_t)(0x69 ^ (i * 37));
        r[i] = 0x69;
    }
    size_t done = 0, piece = 1;
    while (done < sizeof l) {
        size_t n = piece < sizeof l - done ? piece : sizeof l - done;
        const uint8_t *ch[2] = {l + done, r + done};
        CHECK(dsdup_stream_push_dsd(st, ch, n) == DSDUP_OK);
        done += n;
        piece = piece * 3 + 1;
    }
    uint64_t n_out = 0, delay = 0;
    CHECK(dsdup_stream_delay(st, &delay) == DSDUP_OK && delay > 0);
    CHECK(dsdup_stream_finish_exact(st, (uint64_t)sizeof l * 8 + 1, &n_out) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    /* shorter than pushed by a byte or more: refused, nothing emitted, stream unfinished */
    uint64_t before = sk.bytes;
    n_out = 777;
    CHECK(dsdup_stream_finish_exact(st, (uint64_t)sizeof l * 8 - 8, &n_out) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(strstr(dsdup_last_error(), "already pushed") != NULL);
    CHECK(dsdup_stream_finish_exact(st, (uint64_t)sizeof l * 4 + 5, &n_out) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(n_out == 777 && sk.bytes == before);
    CHECK(dsdup_stream_finish(st, &n_out) == DSDUP_OK);
    CHECK(n_out == 2822400 * 2 && sk.bytes * 8 == n_out && sk.channels == 2);
    dsdup_counters k;
    CHECK(dsdup_stream_counters(st, 1, &k) == DSDUP_OK);
    CHECK(dsdup_stream_counters(st, 2, &k) == DSDUP_ERR_INVALID_ARGUMENT);
    const uint8_t *two[2] = {l, r};
    CHECK(dsdup_stream_push_dsd(st, two, 4) == DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(dsdup_stream_push_dsd(NULL, two, 4) == DSDUP_ERR_NULL);
    const uint8_t *with_null[2] = {l, NULL};
    dsdup_stream_free(st);

    /* finish_exact within the last byte: 7 padding bits declared away */
    {
        struct sink ek = {0};
        dsdup_stream *es = NULL;
        CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output, &ek, &es) == DSDUP_OK);
        const uint8_t *ch[2] = {l, r};
        CHECK(dsdup_stream_push_dsd(es, ch, 1000) == DSDUP_OK);
        uint64_t en = 0;
        CHECK(dsdup_stream_finish_exact(es, 8000 - 7, &en) == DSDUP_OK);
        CHECK(en == (8000 - 7) * 2 && ek.bytes == (en + 7) / 8);
        dsdup_stream_free(es);
    }

    /* stream errors: output callback stops, NULL channel, PCM output, wrong kind */
    struct sink stop = {.stop_after = 1};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output, &stop, &st) == DSDUP_OK);
    CHECK(dsdup_stream_push_dsd(st, with_null, 4) == DSDUP_ERR_NULL);
    CHECK(dsdup_stream_push_dsd(st, two, sizeof l) == DSDUP_ERR_CANCELLED);
    const double *pcm[2] = {0, 0};
    CHECK(dsdup_stream_push_pcm(st, pcm, 0) == DSDUP_ERR_NULL);
    dsdup_stream_free(st);
    dsdup_stream_free(NULL);
    CHECK(dsdup_stream_new(&p, DSDUP_IN_DSD, 2822400, 2, on_output, &sk, &st) ==
          DSDUP_ERR_UNSUPPORTED);
    CHECK(st == NULL);
    CHECK(dsdup_stream_new(&s, 7, 2822400, 2, on_output, &sk, &st) ==
          DSDUP_ERR_INVALID_ARGUMENT);
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 0, on_output, &sk, &st) ==
          DSDUP_ERR_UNSUPPORTED);
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, NULL, &sk, &st) == DSDUP_ERR_NULL);

    /* stream of PCM */
    struct sink pk = {0};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_PCM, 44100, 1, on_output, &pk, &st) == DSDUP_OK);
    static double x[44100];
    for (size_t i = 0; i < 44100; i++) x[i] = 0.25 * (double)((i % 100) - 50) / 50.0;
    const double *one[1] = {x};
    CHECK(dsdup_stream_push_pcm(st, one, 44100) == DSDUP_OK);
    CHECK(dsdup_stream_finish(st, NULL) == DSDUP_OK);
    CHECK(pk.bytes * 8 == 5644800);
    dsdup_stream_free(st);

    /* 48 kHz-family PCM (resampled by 147/160): 1 s in, exactly 1 s of DSD128 out, the
     * resampler's delay included; other rates are refused */
    struct sink pk48 = {0};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_PCM, 48000, 1, on_output, &pk48, &st) == DSDUP_OK);
    uint64_t d48 = 0, d44 = 0;
    CHECK(dsdup_stream_delay(st, &d48) == DSDUP_OK);
    static double x48[48000];
    for (size_t i = 0; i < 48000; i++) x48[i] = 0.25 * (double)((i % 100) - 50) / 50.0;
    const double *one48[1] = {x48};
    CHECK(dsdup_stream_push_pcm(st, one48, 48000) == DSDUP_OK);
    uint64_t n48 = 0;
    CHECK(dsdup_stream_finish(st, &n48) == DSDUP_OK);
    CHECK(n48 == 5644800 && pk48.bytes * 8 == 5644800);
    dsdup_stream_free(st);
    CHECK(dsdup_stream_new(&s, DSDUP_IN_PCM, 44100, 1, on_output, &pk48, &st) == DSDUP_OK);
    CHECK(dsdup_stream_delay(st, &d44) == DSDUP_OK);
    dsdup_stream_free(st);
    CHECK(d48 == d44 + 182 * 128); /* 182 samples at 44.1 kHz */
    static const uint32_t ok_rates[] = {96000, 192000, 384000};
    for (size_t i = 0; i < 3; i++) {
        CHECK(dsdup_stream_new(&s, DSDUP_IN_PCM, ok_rates[i], 1, on_output, &pk48, &st) ==
              DSDUP_OK);
        dsdup_stream_free(st);
    }
    static const uint32_t bad_rates[] = {32000, 64000, 768000};
    for (size_t i = 0; i < 3; i++) {
        st = NULL;
        CHECK(dsdup_stream_new(&s, DSDUP_IN_PCM, bad_rates[i], 1, on_output, &pk48, &st) ==
              DSDUP_ERR_UNSUPPORTED);
        CHECK(st == NULL);
    }

    /* reentrancy: BUSY from inside the callback; free inside the callback is deferred */
    static uint8_t big[65536];
    memset(big, 0x5a, sizeof big);
    const uint8_t *bb[2] = {big, big};
    struct reenter re = {0};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output_reenter, &re, &re.st) ==
          DSDUP_OK);
    CHECK(dsdup_stream_delay(re.st, &re.delay) == DSDUP_OK && re.delay > 0);
    CHECK(dsdup_stream_push_dsd(re.st, bb, sizeof big) == DSDUP_OK);
    CHECK(re.calls > 0 && re.busy_ok == 3 * re.calls && re.delay_ok == re.calls);
    dsdup_counters k2;
    CHECK(dsdup_stream_counters(re.st, 0, &k2) == DSDUP_OK); /* not busy any more */
    dsdup_stream_free(re.st);
    struct reenter rf = {.mode = 1};
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output_reenter, &rf, &rf.st) ==
          DSDUP_OK);
    dsdup_stream *keep = rf.st;
    CHECK(dsdup_stream_push_dsd(keep, bb, sizeof big) == DSDUP_OK);
    CHECK(rf.calls >= 1 && rf.st == NULL); /* freed when the push returned; ASan checks */

    /* free stream and user data in the callback during finish (several outputs follow) and
     * during a push: exactly one callback, DSDUP_OK, out_samples not written */
    struct owned *ow = malloc(sizeof *ow);
    CHECK(ow != NULL);
    ow->free_now = 0;
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output_free_owner, ow,
                           &ow->st) == DSDUP_OK);
    CHECK(dsdup_stream_push_dsd(ow->st, bb, 4) == DSDUP_OK);
    dsdup_stream *fin = ow->st;
    ow->free_now = 1;
    uint64_t untouched = 12345;
    owned_frees = 0;
    CHECK(dsdup_stream_finish(fin, &untouched) == DSDUP_OK);
    CHECK(owned_frees == 1 && untouched == 12345);
    ow = malloc(sizeof *ow);
    CHECK(ow != NULL);
    ow->free_now = 1;
    CHECK(dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, on_output_free_owner, ow,
                           &ow->st) == DSDUP_OK);
    fin = ow->st;
    owned_frees = 0;
    CHECK(dsdup_stream_push_dsd(fin, bb, sizeof big) == DSDUP_OK);
    CHECK(owned_frees == 1);

    if (failures) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    printf("C smoke test: all checks passed\n");
    return 0;
}
