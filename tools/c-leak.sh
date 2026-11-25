#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# Runs the C interface leak loop under AddressSanitizer with leak detection (clang).
# Usage: tools/c-leak.sh [N] (default 200). Extra cargo flags come from CARGO_FLAGS.
set -eu
n=${1:-200}
cargo build --release ${CARGO_FLAGS:-} -p dsd-upsample-capi -p dsd-upsample-cli
work=$(mktemp -d)
trap 'rm -r "$work"' EXIT
mkdir "$work/lib"
cp target/release/libdsd_upsample.so "$work/lib/libdsd_upsample.so.1"
ln -s libdsd_upsample.so.1 "$work/lib/libdsd_upsample.so"
./target/release/dsd-upsample gen "$work/in.dsf" --rate 64 --seconds 1 --level -6
clang -fsanitize=address -g -std=c11 -Wall -Wextra -Werror \
  -I crates/dsd-upsample-capi/include crates/dsd-upsample-capi/tests/c/leak.c \
  -L "$work/lib" -ldsd_upsample -Wl,-rpath,"$work/lib" -o "$work/leak"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 "$work/leak" "$work/in.dsf" "$work" "$n"
