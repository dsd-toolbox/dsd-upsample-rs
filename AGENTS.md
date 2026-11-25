# Rules for contributors and agents

- **Licence boundary.** No GPL or LGPL code, tables or coefficients are copied into this
  repository's crates. Designs come from published literature and permissively licensed
  tools; record the source of every borrowed idea, design method or table in
  `PROVENANCE.md`.
- **Determinism.** Within a release, output must be byte-identical across platforms, SIMD
  levels and build profiles. No fused multiply-add, no runtime-generated filter coefficients from platform
  libm, no FFT libraries that choose algorithms per CPU in the output path. The golden
  hashes in `crates/dsd-upsample/tests` change only on purpose, in a change that says why and
  adds the change and its measured effect to `CHANGELOG.md`.
- **Pull requests** with green required checks: `cargo fmt --check`,
  `cargo clippy --all-targets -- -D warnings`, tests in debug and release on Linux
  (x86_64), and the C smoke test (`tools/c-smoke.sh`).
- **Unsafe code** lives only in `crates/dsd-upsample-capi`; every `unsafe` block carries a
  `SAFETY:` comment.
- Every change updates the README and docs where needed.
