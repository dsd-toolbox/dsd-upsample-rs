#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# Builds the C library and runs the C smoke test against it (with AddressSanitizer and
# UBSan on the C side when clang is installed). Usage: tools/c-smoke.sh (from the repository root; needs cc).
set -eu
# Extra cargo flags (for example a --config patch) come from CARGO_FLAGS.
cargo build --release ${CARGO_FLAGS:-} -p dsd-upsample-capi -p dsd-upsample-cli
work=$(mktemp -d)
trap 'rm -r "$work"' EXIT
# The library as installed: on Linux the real file under its soname plus the link-time
# name; on macOS the dylib.
mkdir "$work/lib"
if [ "$(uname -s)" = Darwin ]; then
  cp target/release/libdsd_upsample.dylib "$work/lib/"
  install_name_tool -id @rpath/libdsd_upsample.dylib "$work/lib/libdsd_upsample.dylib"
else
  cp target/release/libdsd_upsample.so "$work/lib/libdsd_upsample.so.1"
  ln -s libdsd_upsample.so.1 "$work/lib/libdsd_upsample.so"
fi
./target/release/dsd-upsample gen "$work/in.dsf" --rate 64 --seconds 2 --level -6
# Sanitizers through clang when present (gcc's runtimes are often not installed).
if command -v clang >/dev/null; then
  cc="clang -fsanitize=address,undefined"
else
  cc=cc
fi
# The header alone: C99 (no layout assertions), C11 and C++11 (with them), and with clang
# the layout assertions on 32-bit and other 64-bit targets too.
hdr=crates/dsd-upsample-capi/include
for c in "cc -x c -std=c99" "cc -x c -std=c11" "c++ -x c++ -std=c++11"; do
  echo '#include "dsd_upsample.h"' | $c -Wall -Wextra -Werror -pedantic -fsyntax-only -I "$hdr" -
done
if command -v clang >/dev/null; then
  for t in i686-linux-gnu armv7-linux-gnueabihf aarch64-linux-gnu; do
    echo '#include "dsd_upsample.h"' |
      clang --target=$t -ffreestanding -x c -std=c11 -Werror -fsyntax-only -I "$hdr" -
  done
fi
$cc -std=c11 -Wall -Wextra -Werror -g \
  -I crates/dsd-upsample-capi/include crates/dsd-upsample-capi/tests/c/smoke.c \
  -L "$work/lib" -ldsd_upsample -Wl,-rpath,"$work/lib" -o "$work/smoke"
LD_LIBRARY_PATH="$work/lib" "$work/smoke" "$work/in.dsf" "$work"
