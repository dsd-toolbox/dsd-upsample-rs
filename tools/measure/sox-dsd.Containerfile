# SPDX-License-Identifier: MIT OR Apache-2.0
# Build: podman build -t sox-dsd:0be259ea -f tools/measure/sox-dsd.Containerfile tools/measure
# Binary for measure_dsdup.py --sox: podman create --name soxcp sox-dsd:0be259ea && podman cp soxcp:/opt/sox/bin/sox . && podman rm soxcp
# SoX with DSD output (sdm and clans modulators), by Mans Rullgard.
# Source: https://github.com/mansr/sox, pinned to one commit and one tarball hash.
ARG BASE=registry.fedoraproject.org/fedora:43
ARG MINIMAL=registry.fedoraproject.org/fedora-minimal:43

FROM ${BASE} AS build
ARG SOX_COMMIT=0be259eaa9ce3f3fa587a3ef0cf2c0b9c73167a2
ARG SOX_SHA256=795e90314462e4b0f028d731c748d52aa95391688a09c5ef9752d1cddb5b8072
RUN dnf -y install --setopt=install_weak_deps=False \
        gcc make autoconf automake libtool pkgconf-pkg-config curl tar gzip \
    && dnf clean all
WORKDIR /src
RUN curl -fsSL -o sox.tar.gz "https://github.com/mansr/sox/archive/${SOX_COMMIT}.tar.gz" \
    && echo "${SOX_SHA256}  sox.tar.gz" | sha256sum -c - \
    && tar xzf sox.tar.gz --strip-components=1 \
    && autoreconf -fi \
    && ./configure --prefix=/opt/sox --disable-shared --enable-static \
        --without-png --without-magic --without-oggvorbis --without-opus \
        --without-flac --without-mad --without-lame --without-twolame \
        --without-id3tag --without-sndfile --without-gsm --without-lpc10 \
        --without-amrnb --without-amrwb --without-wavpack --without-sndio \
        --without-alsa --without-ao --without-coreaudio --without-pulseaudio \
        --without-oss --without-ffmpeg --without-mp3 \
        CFLAGS="-O2 -std=gnu99 -Wno-implicit-function-declaration" LIBS="-lm" \
    && make -C libgsm && make -C lpc10 && make -C src -j"$(nproc)" \
    && make -C src install-strip \
    && echo "${SOX_COMMIT}" > /opt/sox/SOURCE_COMMIT

FROM ${MINIMAL}
LABEL org.opencontainers.image.title="sox-dsd" \
      org.opencontainers.image.description="SoX fork with DSD output (sdm, clans), pinned build" \
      org.opencontainers.image.licenses="GPL-2.0-or-later" \
      org.opencontainers.image.source="https://github.com/mansr/sox"
RUN microdnf -y install --setopt=install_weak_deps=0 libgomp && microdnf clean all
COPY --from=build /opt/sox /opt/sox
ENV PATH=/opt/sox/bin:$PATH
USER 65534:65534
ENTRYPOINT ["/opt/sox/bin/sox"]
