[dsd-upsample-rs](../README.md) › [Documentation](README.md) › Options

# Options

Every option of the `dsd-upsample` command. Worked examples are in the
[user guide](user-guide.md).

## Synopsis

```sh
dsd-upsample IN OUT --rate 64|128|256|pcm88|pcm176|pcm352 [options]
dsd-upsample IN... --out-dir DIR --rate ... [--format dsf|dff|wav] [--jobs N] [--suffix TEXT] [--json]
dsd-upsample gen OUT.dsf|OUT.dff [--rate 64|128|256] [--freq HZ] [--level DB] [--seconds S] [--channels N]
dsd-upsample gen OUT.wav --fs HZ [--freq HZ] [--level DB] [--seconds S] [--channels N] [--bits 16|24|32|f32|f64]
```

`dsd-upsample --help` (or `-h`) prints the same summary on stdout; `dsd-upsample --version`
(or `-V`) prints `dsd-upsample` and the version, such as `dsd-upsample 0.1.0`. Both succeed
whatever else is on the command line. File names need not be valid UTF-8. `--` ends the
options: every argument after it is a file name, even one starting with `-`
(`dsd-upsample --rate 128 -- -take1.dsf out.dsf`). Options of the other mode are refused:
`--freq` on a conversion, or `--order` on `gen`, is a usage error, as is `--fs` or `--bits`
for a DSF or DFF test tone and `--rate` for a WAV one.

IN is DSF or DFF (DSD64, DSD128, DSD256), or WAV or FLAC at 44.1, 88.2, 176.4 or 352.8 kHz,
or at 48, 96, 192 or 384 kHz. No option selects the resampling of the 48 kHz family: it
is always the 147/160 filter of [resampler design](resampler-design.md) (stopband −244.6 dB
at the new rate's Nyquist frequency, ripple within ±5e-12 dB), and every option below applies after it as for the 44.1 kHz
family.

Every output is written to a temporary `NAME.partN.EXT` next to it and renamed when the
conversion succeeds; a failure or Ctrl-C removes it.

| Exit status | Meaning |
|---|---|
| 0 | Success |
| 1 | A conversion or I/O error (an unreadable or invalid input, a write error); in batch mode, any file failed |
| 2 | A usage error: the command line is invalid (an unknown option, a value out of range, an output that is the input); nothing was converted |
| 130 | Interrupted: Ctrl-C (or SIGTERM, SIGHUP) stopped a conversion before it finished. A Ctrl-C after every conversion has finished changes nothing |

## Conversion

| Option | Meaning |
|---|---|
| `--rate 64\|128\|256` | DSD64 (PCM input only), DSD128 or DSD256 output |
| `--rate pcm88\|pcm176\|pcm352` | 24-bit PCM WAV output at 88.2, 176.4 or 352.8 kHz, from DSD64 |
| `--order 5..8` | Modulator order (default 6). DSD128 output accepts 5 to 7; DSD64 and DSD256 accept 5 to 8. An accepted order clipped no modulator state on legal input in the 60 s [stability study](modulator-design.md#stability-study); order 8 at DSD128 did, so it is refused (exit status 2). Orders 7 and 8 lower the in-band noise but can overload on input above full scale; see [modulator design](modulator-design.md#orders-7-and-8) |
| `--gain DB` | Gain before the modulator: default -6 for DSD output, 0 for PCM. At 0 dB, PCM full scale is 0 dB SACD (50 % modulation), the reference level of Super Audio CD; at the default it is 6 dB lower (25 % modulation), and DSD input comes out 6 dB lower than it went in. The default leaves 6 dB of headroom, so that legal input is not limited: PCM true peaks up to +6 dBTP, and DSD up to 100 % modulation after the input filter ([design, Decisions](design.md#decisions)). A higher gain is the louder setting: for example `--gain -3` raises the signal 3 dB against the modulator's noise, and samples above the input limit are then limited and counted in the report |
| `--cutoff 30\|40\|wide` | DSD64 decimation filter: the 30, 40 or 80 kHz PCM filters (default for DSD output: a 140 dB Kaiser filter; for PCM output: 40). Against the default filter, they change the level of a 1 kHz tone by +0.0034 dB (30), -0.0026 dB (40) and -0.0009 dB (wide) |
| `--dither` | TPDF dither before the modulator |
| `--limit FRACTION` | Modulator input limit, default 0.51 (0.17 dB above 0 dB SACD; [modulator design](modulator-design.md#input-limit)). The stability results hold at the default; a higher limit lets more through to the modulator and can make it clip its states |
| `--tag KEY=VALUE` | ID3v2 tag in DSF output, repeatable, replacing the source's: title, artist, album, albumartist, track, disc, date, genre, composer, comment, or any other key (stored as a user text frame); single files only |
| `--format dsf\|dff\|wav` | Container, regardless of OUT's name |
| `--no-overwrite` | Fail instead of replacing an existing OUT, including one that appears during the conversion |
| `--single-thread` | One thread per file |

## Batch mode

| Option | Meaning |
|---|---|
| `--out-dir DIR` | Convert every IN to `DIR/<name><suffix>.<format>` (format default: DSF, or WAV for PCM rates); DIR must exist |
| `--jobs N` | Files converted at a time (default: CPU threads / 4) |
| `--suffix TEXT` | Text between the name and the extension; no path separators |
| `--json` | One JSON object per line on stdout: progress and done events; a done event carries the output length and the `limited`, `clipped`, `resets` and `clamped` totals ([fields](user-guide.md#follow-progress-from-another-program)) |

`--jobs`, `--suffix` and `--json` need `--out-dir`.

## Test signals (`gen`)

| Option | Meaning |
|---|---|
| `--rate 64\|128\|256` | DSD rate of a DSF or DFF test tone |
| `--fs HZ` | Sample rate of a WAV test tone |
| `--freq HZ` | Tone frequency |
| `--level DB` | Level: dB re 0 dB SACD for DSD, dBFS for WAV. DSD tones go up to +3.1 dB SACD, the Super Audio CD peak level; a higher level is refused. Up to 0 dB SACD the tone comes from the order-7 modulator; above it from a second-order modulator, which is stable at that level and has more noise in the audio band (72 dB below a 1 kHz tone at DSD64, 87 dB at DSD128, 102 dB at DSD256) |
| `--seconds S` | Length |
| `--channels N` | Channel count |
| `--bits 16\|24\|32\|f32\|f64` | WAV sample format |

## See also

- [User guide](user-guide.md)
- [Measurements](measurements.md): what the gain, limit and order do to the output
- [Design](design.md): the processing chain behind the options
- [C interface](c-api.md): the same settings from C

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
