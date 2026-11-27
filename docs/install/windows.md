[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › [Install](README.md) › Windows

# Windows

Install dsd-upsample on Windows 11, x64: the `dsd-upsample.exe` command and the C library.
Windows on ARM is not supported; it comes in a later release, once tested on ARM64 Windows.

## Release zip

The [releases page](https://github.com/dsd-toolbox/dsd-upsample-rs/releases) has a `.zip` for
`x86_64-pc-windows-msvc`, with a `.sha256` file and a build provenance attestation. The
Windows releases are not code-signed yet, so their zips are named `-unsigned` and the SHA-256
sum is how you check what you downloaded. In PowerShell, download both files and compare the
sums:

```powershell
curl.exe -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.1/dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip
curl.exe -fLO https://github.com/dsd-toolbox/dsd-upsample-rs/releases/download/v0.1.1/dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip.sha256
(Get-FileHash dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip -Algorithm SHA256).Hash.ToLower() -eq (Get-Content dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip.sha256).Split(' ')[0]
```

The last line must print `True`. With the [GitHub CLI](https://cli.github.com/) installed and signed in with `gh auth login`, this
also checks where the zip was built:

```powershell
gh attestation verify dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip --repo dsd-toolbox/dsd-upsample-rs
```

Only after both checks, unblock the zip (Windows marks a file from the internet, and may warn
before it runs an unsigned program from it), extract it and run the command:

```powershell
Unblock-File dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip
Expand-Archive dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc.zip -DestinationPath .
.\dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc\dsd-upsample.exe --version
```

The last line prints `dsd-upsample 0.1.1`. The zip unpacks into one folder,
`dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc\`, which holds:

| Path | Contents |
|---|---|
| `dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc\` | The folder everything below is in |
| `dsd-upsample.exe` | The command |
| `lib\dsd_upsample.dll`, `lib\dsd_upsample.dll.lib` | The C library and its import library |
| `lib\dsd_upsample.lib` | The static C library |
| `include\dsd_upsample.h` | C header |
| `README.md`, `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE` | Documentation, licences and notices |

To run `dsd-upsample` from any folder, copy it to a folder of its own and add that folder to
your user `PATH`. Run these lines once (the last one adds the folder again each time it runs). Paste them as they are: `$env:LOCALAPPDATA` is read by PowerShell, not
a placeholder to fill in. Then open a new PowerShell window.

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Programs\dsd-upsample"
Copy-Item .\dsd-upsample-v0.1.1-unsigned-x86_64-pc-windows-msvc\dsd-upsample.exe "$env:LOCALAPPDATA\Programs\dsd-upsample"
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:LOCALAPPDATA\Programs\dsd-upsample", "User")
```

## From crates.io

With Rust 1.83 or later (from rustup, which puts `cargo install`'s folder on your `PATH`):

```powershell
cargo install dsd-upsample-cli
```

## Tested

The Windows build runs the full test suite in release, golden hashes included, on GitHub's
Windows Server 2025 x64 runners before it is packaged; CI runs the tests on every change.
Each release is also tested in a Windows 11 x64 virtual machine: the test suite, the release
zip, and output byte-identical to the Linux command. Windows 10 is not tested.

## See also

- [Install](README.md)
- [User guide](../user-guide.md)
- [C interface](../c-api.md)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
