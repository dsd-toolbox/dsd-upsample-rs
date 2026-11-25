// SPDX-License-Identifier: MIT OR Apache-2.0
// The shared library's soname follows the C ABI version (DSDUP_ABI_VERSION in the header):
// libdsd_upsample.so.1. It changes only when the ABI breaks.
fn main() {
    let os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if os == "linux" || os == "freebsd" {
        println!("cargo:rustc-cdylib-link-arg=-Wl,-soname,libdsd_upsample.so.1");
    }
    println!("cargo:rerun-if-changed=build.rs");
}
