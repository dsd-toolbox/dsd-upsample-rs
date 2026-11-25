[dsd-upsample-rs](../README.md) › [Documentation](README.md) › User guide

# User guide

How to convert files with the `dsd-upsample` command, one at a time or in batches, and what
its report means. Installing is in the [install guides](install/README.md); every option is
in [options](options.md).

## Inputs and outputs

- **Inputs:** DSF and DFF (DSDIFF) at DSD64, DSD128 and DSD256; WAV or FLAC at 44.1, 88.2,
  176.4 or 352.8 kHz, or at 48, 96, 192 or 384 kHz (see
  [48 kHz-family input](#48-khz-family-input)).
- **Outputs:** DSD64 (PCM input only), DSD128 or DSD256 as DSF or DFF; 24-bit PCM WAV at
  88.2, 176.4 or 352.8 kHz from DSD64.
- The output format follows OUT's extension (`.dsf`, `.dff`, `.wav`), or `--format`.

## Convert a file

Give the input, the output and the rate. This writes a DSD64 test tone and converts it to
DSD256:

```sh
dsd-upsample gen tone.dsf --rate 64 --freq 1000 --level -6 --seconds 5
dsd-upsample tone.dsf tone256.dsf --rate 256
```

While it runs, the converter writes to a temporary file next to the output,
`NAME.partN.EXT` (for example `tone256.part1.dsf`), and renames it to the output's name when
it has finished. If the conversion fails or you press Ctrl-C, the temporary file is removed:
no half-written file is left under the output's name, and an existing output is replaced
only by a complete one. A second Ctrl-C quits at once and may leave the temporary file.

The defaults (order 6; gain -6 dB; input limit 0.51) suit most material; the
[measurements](measurements.md) show what changing them does. The output is 6 dB quieter
than the reference level: PCM full scale lands at −6 dB SACD (25 % modulation; a gain of
0 dB would put it at 0 dB SACD, 50 %), and DSD input comes out 6 dB lower than it went
in. That headroom is what keeps loud material from being limited (PCM true peaks up to
+6 dBTP, DSD up to 100 % modulation); turn the volume up by 6 dB to compare with the
source. `--gain -3` or `--gain 0` gives a louder file, and
the report then counts the samples that were limited. `--tag KEY=VALUE` writes
ID3v2 tags into DSF output.

## Convert many files

`--out-dir DIR` converts every input to `DIR/<name><suffix>.<format>`, `--jobs N` files at a
time (default: CPU threads / 4). DIR must exist: create it first (`mkdir DIR`). Inputs whose outputs would collide, or overwrite an input,
are refused before anything starts. Ctrl-C stops the files in progress (removing their
temporary files) and starts no more.

## Follow progress from another program

`--json` (with `--out-dir`) prints one JSON object per line on stdout: a progress event
(input, percent) every 5 % and a done event per file. The done event has `input`, `output`
and `ok`; a failed file adds `error`, a converted one adds:

| Field | Meaning |
|---|---|
| `samples` | Output samples per channel |
| `limited` | Samples limited before the modulator, all channels together |
| `clipped` | Samples with clipped modulator states, all channels together |
| `resets` | Modulator resets, all channels together |
| `clamped` | PCM output: samples clamped to 24 bits, all channels together (0 for DSD output) |
| `warning` | Only when present: the warning the report prints (see below) |

```json
{"event":"done","input":"in.dsf","output":"out/in.dsf","ok":true,"samples":564480,"limited":0,"clipped":0,"resets":0,"clamped":0}
```

## 48 kHz-family input

WAV or FLAC at 48, 96, 192 or 384 kHz converts like any other input. The converter first
changes the rate by 147/160 to 44.1, 88.2, 176.4 or 352.8 kHz with a synchronous polyphase
filter (linear phase, flat to 20 kHz at 48 kHz input and to 40, 80 or 160 kHz at the
higher rates, stopband 244.6 dB below the signal at the new rate's Nyquist frequency and
256 dB below from the input's), then
runs the chain it uses for that rate. The output has `input samples x output rate / input
rate` samples, rounded down, and starts at the same instant as the input. The rate change
adds no measurable noise or distortion, and with the default threads no measurable time:
[measurements](measurements.md#48-khz-family-input) and
[resampler design](resampler-design.md).

## Report and speed

Each conversion prints its speed as a multiple of real time and, per channel, how many input
samples were limited, how many samples had clipped modulator states and how many resets
occurred. Whenever any sample was limited, however few, a line gives the count and the share
for the file (`limited: 7884 of 8288870400 samples (9.5e-5 %) were above the input limit;
a lower --gain avoids it`), and batch mode ends with the total over all files and how many
files it concerns. When 1 % or more of a channel's samples were limited, it also prints a warning
with the likely cause: a DC offset in the source (an input mean of 0.1 of full scale or more,
named with its value and channel; some releases carry one) or a source too loud for the
input limit. The warning changes nothing in the output; a lower `--gain` reduces the
limiting. Each channel runs on two threads (front end and modulator); the modulator sets the
pace: a stereo file converts to DSD256 at about 8.6 × real time with the default threads on
an Intel Core i9-13900H (both channels in parallel; [speed](measurements.md#speed) has the
conditions), so batch mode is what uses a large machine.

## Memory

Each conversion holds a bounded queue of audio blocks between its threads. In a one-hour batch
run under a heap profiler, heaptrack (two stereo DSD64, DSD128 and DSD256 files at a time, to
DSD128) the live heap peaked at 40 to 49 MiB, and nothing grew with the number of files.
Multichannel files need about twice that: two files at a time from a mix that includes 5- and
6-channel files peaked at 99 to 104 MiB, measured with an exact counting allocator. A DSF
input's metadata tag (ID3) is copied to DSF output (unless `--tag` replaces it) and is held in
memory twice while the file converts; a tag larger than 16 MiB is not carried over.

## Troubleshooting

- **`--rate 64` is refused:** DSD64 output needs PCM input (WAV or FLAC).
- **`unsupported: PCM input at 32000 Hz`** (or another rate): PCM input must be at 44.1,
  88.2, 176.4, 352.8, 48, 96, 192 or 384 kHz; resample other rates to one of them first.
- **`the DSF header declares 0 samples per channel, but its data chunk holds N bytes`:** the
  file's header is damaged; nothing is converted, because the audio's real length is unknown.
  Re-extract or re-download the file.
- **`--jobs, --suffix and --json need --out-dir`:** these options apply to batch mode only.
- **`--tag is for single files, not --out-dir`:** tag files one at a time.
- **`--out-dir out: not a directory`:** DIR must exist; create it first (`mkdir out`).
- **`--format ... does not fit --rate`** (batch mode), **`DSD output needs a .dsf or .dff file
  (or --format)`** or **`PCM output needs a .wav file (or --format wav)`** (one file): DSD
  rates write DSF or DFF, PCM rates write WAV.
- **A batch is refused before it starts:** two inputs would write the same output, or an
  output would replace an input; use `--suffix` or another `--out-dir`.
- **The output exists already:** it is replaced when the conversion succeeds, unless you
  pass `--no-overwrite`, which also refuses to replace a file that appears while the
  conversion runs.
- **A `NAME.part1.dsf` file is left over:** the converter was killed (or Ctrl-C was pressed
  twice) before it could clean up; delete the file.
- **Interrupted, exit status 130:** Ctrl-C stopped the conversion; unfinished outputs were
  removed.
- **Limited samples in the report:** at the default gain this takes a PCM true peak above
  +6.17 dBTP, a DC offset in the source, or a raised `--gain`; lower `--gain`. Clipped
  states or resets mean the modulator overloaded, which no accepted setting did on the
  test set. See [modulator design](modulator-design.md#stability-study).

## See also

- [Options](options.md)
- [Install guides](install/README.md)
- [Measurements](measurements.md)

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
