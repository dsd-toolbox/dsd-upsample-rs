#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# musl check (x86_64-unknown-linux-musl), for hosts that load the C library on musl (for
# example a musllinux Python wheel):
#   1. the whole test suite in release on the musl target, golden hashes included;
#   2. the C library as a shared object linked against musl's libc
#      (-C target-feature=-crt-static: the target's default static CRT drops cdylib): it
#      must exist, export the dsdup_ functions, need only musl's loader and libgcc_s.so.1
#      (Rust's unwinder links libgcc_s on non-static musl; on Alpine it is the libgcc
#      package, a musllinux wheel must carry it) and no glibc symbol version;
#   3. with MUSL_LIBGCC_DIR set to a folder holding a musl build of libgcc_s.so.1 (Alpine's
#      /usr/lib), the C smoke test compiled with musl-gcc against that library. Without it
#      the smoke run is reported as not run: a glibc host has no musl libgcc_s.
# Usage: tools/musl-check.sh (from the repository root). Needs the rustup target
# x86_64-unknown-linux-musl, musl-gcc and readelf. Extra cargo flags come from CARGO_FLAGS.
set -eu
t=x86_64-unknown-linux-musl
echo "== tests on $t"
cargo test --release ${CARGO_FLAGS:-} --workspace --target "$t"

echo "== C library on $t (dynamic musl libc)"
# A separate target dir: other RUSTFLAGS must not invalidate the main build.
RUSTFLAGS="-C target-feature=-crt-static" CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc \
  cargo build --release ${CARGO_FLAGS:-} -p dsd-upsample-capi \
  --target "$t" --target-dir target/musl-dyn
rel=target/musl-dyn/$t/release
so=$rel/libdsd_upsample.so
[ -f "$so" ] || { echo "musl-check: $so was not built" >&2; exit 1; }
readelf -d "$so" | grep -E 'NEEDED|SONAME'
needed=$(readelf -d "$so" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort | tr '\n' ' ')
case $needed in
  "ld-musl-x86_64.so.1 libgcc_s.so.1 "|"libc.musl-x86_64.so.1 libgcc_s.so.1 ") ;;
  *) echo "musl-check: $so needs '$needed', expected musl's loader and libgcc_s.so.1" >&2; exit 1 ;;
esac
if readelf -W --dyn-syms "$so" | grep -q 'GLIBC_'; then
  echo "musl-check: $so references glibc symbol versions" >&2; exit 1
fi
n=$(readelf -W --dyn-syms "$so" | grep -c ' dsdup_' || true)
[ "$n" -gt 0 ] || { echo "musl-check: $so exports no dsdup_ function" >&2; exit 1; }
echo "musl-check: $so: $n dsdup_ symbols, needs $needed"
if [ -z "${MUSL_LIBGCC_DIR:-}" ]; then
  echo "musl-check: C smoke test NOT RUN (set MUSL_LIBGCC_DIR to a musl libgcc_s.so.1 folder)"
  echo "musl-check: passed (tests on $t, library build and dependencies)"
  exit 0
fi
work=$(mktemp -d)
trap 'rm -r "$work"' EXIT
mkdir "$work/lib"
cp "$so" "$work/lib/libdsd_upsample.so.1"
ln -s libdsd_upsample.so.1 "$work/lib/libdsd_upsample.so"
# The static CLI from step 1 writes the input.
"target/$t/release/dsd-upsample" gen "$work/in.dsf" --rate 64 --seconds 2 --level -6
musl-gcc -std=c11 -Wall -Wextra -Werror -g \
  -I crates/dsd-upsample-capi/include crates/dsd-upsample-capi/tests/c/smoke.c \
  -L "$work/lib" -ldsd_upsample -Wl,-rpath,"$work/lib" -o "$work/smoke"
LD_LIBRARY_PATH="$work/lib:$MUSL_LIBGCC_DIR" "$work/smoke" "$work/in.dsf" "$work"
echo "musl-check: passed (tests on $t, library, C smoke test)"
