/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/* Leak loop for the C interface: every lifecycle path many times; run under
 * AddressSanitizer with detect_leaks=1 (tools/c-leak.sh). Usage: leak IN.dsf OUTDIR N */
#include "dsd_upsample.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int32_t sink(void *u, const uint8_t *const *c, uint32_t n, size_t b) {
    (void)c; (void)n; (void)b;
    int *stop = u;
    return stop && *stop > 0 && --*stop == 0;
}

struct self { dsdup_stream *st; int freed; };
static int32_t free_self(void *u, const uint8_t *const *c, uint32_t n, size_t b) {
    (void)c; (void)n; (void)b;
    struct self *s = u;
    if (!s->freed) { dsdup_stream_free(s->st); s->freed = 1; }
    return 0;
}

/* Frees the stream and its own user data in the callback; a later call is a use after
 * free that ASan reports. */
struct owner { dsdup_stream *st; int armed; };
static int32_t free_owner(void *u, const uint8_t *const *c, uint32_t n, size_t b) {
    (void)c; (void)n; (void)b;
    struct owner *o = u;
    if (o->armed) { dsdup_stream_free(o->st); free(o); }
    return 0;
}

static int32_t cancel_at(void *u, uint64_t d, uint64_t t) {
    (void)d; (void)t;
    int *k = u;
    return --*k > 0;
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: leak IN.dsf OUTDIR N\n"); return 2; }
    int n = atoi(argv[3]);
    char out[4096];
    snprintf(out, sizeof out, "%s/leak.dsf", argv[2]);
    static uint8_t l[200000], r[200000];
    for (size_t i = 0; i < sizeof l; i++) { l[i] = (uint8_t)(0x69 ^ (i * 31)); r[i] = 0x69; }
    const uint8_t *two[2] = {l, r};
    static double pcm[44100];
    for (size_t i = 0; i < 44100; i++) pcm[i] = 0.2 * (double)((int)(i % 200) - 100) / 100.0;
    const double *one[1] = {pcm};
    for (int i = 0; i < n; i++) {
        dsdup_settings s;
        dsdup_settings_init(&s, i % 2 ? DSDUP_OUT_DSD128 : DSDUP_OUT_DSD256);
        s.threads = i % 3 != 0;
        /* whole file; cancelled every third time; errors: bad paths and settings */
        int k = 2;
        dsdup_report rep;
        dsdup_convert_file(argv[1], out, &s, i % 3 == 0 ? cancel_at : NULL, &k, &rep);
        dsdup_convert_file("/nonexistent.dsf", out, &s, NULL, NULL, NULL);
        dsdup_settings bad = s; bad.order = 99;
        dsdup_convert_file(argv[1], out, &bad, NULL, NULL, NULL);
        (void)dsdup_last_error();
        /* streams: finished; stopped by the callback; freed without finish; freed in callback */
        dsdup_stream *st = NULL;
        if (dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, sink, NULL, &st) == DSDUP_OK) {
            dsdup_stream_push_dsd(st, two, sizeof l);
            uint64_t o; dsdup_stream_finish(st, &o);
            dsdup_counters c; dsdup_stream_counters(st, 0, &c);
            uint64_t d; dsdup_stream_delay(st, &d);
            dsdup_stream_free(st);
        }
        int stop = 1;
        if (dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, sink, &stop, &st) == DSDUP_OK) {
            dsdup_stream_push_dsd(st, two, sizeof l);
            dsdup_stream_free(st);
        }
        if (dsdup_stream_new(&s, DSDUP_IN_PCM, 44100, 1, sink, NULL, &st) == DSDUP_OK) {
            dsdup_stream_push_pcm(st, one, 44100);
            dsdup_stream_free(st); /* no finish */
        }
        struct self me = {0};
        if (dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, free_self, &me, &me.st) == DSDUP_OK) {
            dsdup_stream_push_dsd(me.st, two, sizeof l); /* frees itself in the callback */
            if (!me.freed) dsdup_stream_free(me.st);
        }
        /* stream and user data freed in the callback during finish */
        struct owner *ow = malloc(sizeof *ow);
        if (!ow) return 1;
        ow->armed = 0;
        if (dsdup_stream_new(&s, DSDUP_IN_DSD, 2822400, 2, free_owner, ow, &ow->st) == DSDUP_OK) {
            dsdup_stream_push_dsd(ow->st, two, 64);
            dsdup_stream *fin = ow->st;
            ow->armed = 1;
            uint64_t o;
            if (dsdup_stream_finish(fin, &o) != DSDUP_OK) return 1;
        } else {
            free(ow);
        }
        dsdup_stream_new(&s, 9, 2822400, 2, sink, NULL, &st); /* error path */
    }
    printf("leak loop: %d iterations done\n", n);
    return 0;
}
