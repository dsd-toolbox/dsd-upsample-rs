[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › [Install](README.md) › Packages

# Packages

Every package dsd-upsample 0.1.0 ships as: the crates and the C library, on Linux.

## Crates

| Crate | What |
|---|---|
| [dsd-upsample](https://crates.io/crates/dsd-upsample) | The Rust library ([API](https://docs.rs/dsd-upsample)) |
| [dsd-upsample-cli](https://crates.io/crates/dsd-upsample-cli) | The `dsd-upsample` command (`cargo install dsd-upsample-cli`) |

Both need Rust 1.83 or later.

## C library

`libdsd_upsample` and its header are in the Linux x86_64 release archive,
shared and static, with a pkg-config file. See [Linux](linux.md) and the
[C interface](../c-api.md).

## See also

- [Install](README.md)
- [C interface](../c-api.md)
- [Release process](../release.md)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
