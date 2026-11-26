#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# The Change-level checks of docs/release-test-plan.md on one Linux machine, in the order CI
# runs them: format, lints, tests in debug and release (including the short soak), the
# heap-flat test with 10 rounds, the MSRV tests, the C smoke test and the C leak loop under
# AddressSanitizer, the licence files in the crate packages, `cargo doc` without warnings,
# the quality gate's unit tests (Python 3.11 or later), and the fuzz build.
#
#   tools/local-ci.sh
#
# Needs rustup with the stable toolchain CI pins (RUST_STABLE in .github/workflows/ci.yml,
# with clippy and rustfmt), 1.83, the nightly FUZZ_NIGHTLY there and cargo-fuzz, and a C
# compiler, clang and its AddressSanitizer runtime. Stops at the first failure.
set -eu
cd "$(dirname "$0")/.."
stable=$(sed -n 's/^  RUST_STABLE: //p' .github/workflows/ci.yml)
msrv=1.83
nightly=$(sed -n 's/^  FUZZ_NIGHTLY: //p' .github/workflows/ci.yml)
step() { printf '\n== %s\n' "$*"; }
step fmt; cargo +"$stable" fmt --all --check
step clippy; cargo +"$stable" clippy --locked --workspace --all-targets -- -D warnings
step test debug; cargo +"$stable" test --locked --workspace
step test release; cargo +"$stable" test --locked --workspace --release
step heap-flat; HEAP_FLAT_N=10 cargo +"$stable" test --locked --release -p dsd-upsample --test heap_flat
step test MSRV $msrv; cargo +$msrv test --locked --workspace --release
step C smoke; RUSTUP_TOOLCHAIN=$stable CARGO_FLAGS=--locked tools/c-smoke.sh
step C leak loop; RUSTUP_TOOLCHAIN=$stable CARGO_FLAGS=--locked tools/c-leak.sh 100
# --allow-dirty: a working tree under development (CI checks a clean checkout without it).
step crate licence files
for c in dsd-upsample dsd-upsample-cli; do
  list=$(cargo +"$stable" package --locked --allow-dirty --list -p "$c")
  for f in LICENSE-MIT LICENSE-APACHE NOTICE; do
    printf '%s\n' "$list" | grep -qx "$f" || { echo "$c: $f is not in the package" >&2; exit 1; }
    cmp "$f" "crates/$c/$f"
  done
done
# The C library's crate has the same library name, so the Rust library is documented alone.
step doc; RUSTDOCFLAGS='-D warnings' cargo +"$stable" doc --locked -p dsd-upsample --no-deps
step quality compare unit tests; python3 -I tools/quality/test_compare.py
step fuzz build; (cd fuzz && cargo +"$nightly" fuzz build)
step done; echo "local-ci: all checks passed"
