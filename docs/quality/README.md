[dsd-upsample-rs](../../README.md) › [Documentation](../README.md) › Quality against the previous release

# Quality against the previous release

Every release is measured against the previous one with
[dsd-measure](https://github.com/dsd-toolbox/dsd-measure) ([release test plan](../release-test-plan.md),
item 7). Each release gets a page here, `VERSION.md`, with one table by build and one sentence of
conclusion.

Releases: [0.1.0](0.1.0.md) (against its previous candidate), [0.1.1](0.1.1.md) (byte
identity with 0.1.0).

## What is measured

The suite is [`suites/upconverter.toml`](../../suites/upconverter.toml): a dsd-measure suite with
dsd-measure 0.1.2 pinned in it. The converter is run as a black box through its command line.
Every conversion is measured twice per build:

- **Part (a), equal explicit settings**: the same `--gain -3 --order 6` on both builds, so the
  converter is compared at equal rate, format and level. This is the regression gate.
- **Part (b), defaults**: each build at its own defaults. A default that moved between releases
  (a different default gain, say) shows here.

Every build's output is level-corrected by the gain that build applies, so its report reads at
dsd-measure's levels: the explicit `--gain` in part (a), and in part (b) the default that the
build's own `--help` states ("Defaults: ... --gain -6 (0 for PCM output)"). A build whose `--help`
states no default gain stops the run (exit status 2), and so does a measured gain error above
0.1 dB after the correction: the figures are never compared at a guessed level. A moved default
gain therefore shows in part (b) as what it is, a change of the signal against the modulator's
noise (SINAD, noise floor and dynamic range move; THD may move), and the build table on the page
names each build's default gain.

In both parts, any change beyond repeatability, in either direction, fails the comparison unless
the suite records a decision that explains it (`[[quality.explained]]`: version, part, metrics,
the expected range of the change in dB, optionally the conversions it covers, and the link to the
decision in [design](../design.md)). Such a change is listed on the page as "explained by
decision", never passed silently. One entry covers one range for its metrics, so a decision that
moves several figures by different amounts needs one entry per metric, and one per conversion
where the conversions move differently.

`paths` limits an entry to some conversions: a list of names or globs as the page names them,
either the Conversion column (`"PCM to DSD128"`, `"DSD64 to *"`) or with the input rate
(`"PCM to DSD128 from 44.1 kHz"`), with spaces or with hyphens (`"PCM-to-DSD128-*"`). An entry
without `paths` covers every conversion of its part. A `paths` entry that matches no conversion
of its part, or a malformed entry, stops the run before anything is measured (exit status 2).

```toml
[[quality.explained]]
version = "0.1.0-rc2"
part = "defaults"
metrics = ["dr_a_db"]
paths = ["PCM to DSD64"]
min_db = -3.5
max_db = -2.3
decision = "docs/design.md#decisions"
```

The 0.1.0-rc2 entries (the default gain of −6 dB instead of −3 dB, part (b)) are one per metric
and conversion, from the changes measured in the quick and full profiles ±0.3 dB, so a change in
the other direction fails wherever the measured changes have one sign. From PCM, SINAD fell by
2.1 to 3.4 dB, the dynamic range by 1.2 to 4.3 dB, the noise floor rose by 2.3 to 3.1 dB and THD by
0.2 to 3.9 dB; from DSD64 to DSD128 the changes are under 1.1 dB apart from the dynamic range; DSD64
to DSD256 moved by about repeatability or less, so it has no SINAD or THD entry and narrow noise-floor
and dynamic-range entries. The DSD128 dynamic-range entries (−3.3 to −0.9 dB from PCM, −2.3 to
+1.5 dB from DSD64) span both history-dependent states (Known limits) and apply to DSD128 only; the
one from DSD64 crosses zero. The suite's comment gives every measured figure and range.

The conversions:

| Conversion | Input rates | Measured as |
|---|---|---|
| PCM to DSD64, DSD128, DSD256 | 44.1 kHz and 48 kHz | dsd-measure class B (PCM in, DSD out, decoded by its reference decoder) |
| DSD64 to DSD128, DSD256 | DSD64 made from 44.1 kHz by dsd-measure's reference modulator | class B; the figures include that DSD64 stage |

For each conversion and build the page gives SINAD (= −THD+N) and THD of a 1 kHz tone at
0 dB SACD input, the A-weighted noise floor and dynamic range (20 Hz to 20 kHz), and the null
depth between the two builds. The null test converts one DSD64 source (dsd-measure's multitone
signal) with each build along the same path, decodes both outputs with the reference decoder and
compares them with `dsd-measure null`. Only equal input rate, output rate and format are
compared; a conversion that the previous build does not accept is listed without a comparison.

Levels: the converter maps WAV full scale to 0 dB SACD (50 % modulation), which is 6.02 dB below
dsd-measure's convention, and then applies its gain. Each device in the suite gives the correction
at a gain of 0 dB (`level_ref_db`: 6.0206 dB for PCM input, 0 for DSD input), and
`tools/quality-compare.sh` passes dsd-measure `level_ref_db` minus the build's gain. The null test
undoes each build's gain the same way before the two outputs are compared.

Not measured: alias (image) rejection. dsd-measure measures it for DSD-to-PCM devices only.

## Known limits

- Null test, dsd-measure 0.1.2: it aligns the two outputs over their full bandwidth. When the
  two builds' modulators take different paths (any change of level or settings in part (b)),
  their shaped noise above 20 kHz is uncorrelated and, at DSD64 and DSD128, louder than the
  audio band, so the alignment fails and reports a depth near 0 dB with inverted polarity and a
  large delay. `tools/quality/null-chain.py` therefore low-passes both outputs at 24 kHz (and
  undoes each build's gain) before the comparison: with it, part (b) of 0.1.0-rc1 against the
  −6 dB default nulls by 96 dB (PCM to DSD64), 135 dB (PCM to DSD128), 142 dB (DSD64 to
  DSD128) and 154 dB (PCM to DSD256). A null depth under 40 dB is still checked by hand before it
  is quoted.
- Dynamic range at DSD128: the noise under a −60 to −80 dB SACD tone at DSD128 depends on the
  signal's history. Started with a ramp it sits about 10 dB below the converter's noise at
  higher levels (A-weighted dynamic range about 162 dB); started abruptly, after a louder
  passage or after silence, it sits at that level (148.2 to 152.7 dB in the runs recorded in the
  suite), and it can move from the first to the second within seconds. DSD64 and DSD256 vary by less than 1 dB. dsd-measure's
  level staircase reaches the −60 dB step in one of the two states depending on what came before,
  so the same build reads about 152.7 dB from 48 kHz and 161.6 dB from 44.1 kHz in the quick
  profile, and a change elsewhere in the chain can move the figure by about 10 dB without any
  change of the converter's noise. A DSD128 dynamic-range change beyond repeatability is
  therefore checked against the state of both builds before it is explained or failed.
  `tools/quality/low-level-state.py CLI 48000 128 -3 -60` shows it: one line per start (abrupt,
  ramped, after a louder passage, after silence), the dynamic range of each 0.74 s window over
  12 s.

## Repeatability

The converter's output is deterministic within a release, and dsd-measure's signals and
analysis are deterministic too, so a figure is only flagged when it moves by more than the
suite's stated repeatability (`[quality.repeatability]`), which is the 0.1 dB resolution of the
reports. The measured spread of repeated runs of one build is below.

| Runs | Build | dsd-measure, profile | Largest spread, any metric, any conversion | Null test against itself |
|---|---|---|---|---|
| 3 | v0.1.0-rc1 (SHA-256 `03b52add…`) | 0.1.2 before its tag, quick | 0.0000 dB | identical on all 8 conversions |

The same build measured with dsd-measure 0.1.1 gave the same figures to 0.001 dB.

## Byte identity

A patch release that changes no arithmetic of the conversion is shown byte-identical to the
previous release instead of being measured again: identical output gives identical figures.
`tools/quality/identity.sh OLD-CLI NEW-CLI WORKDIR` converts the same inputs (made by the old
build's `gen`) with both builds over 111 cases (every input and output rate, both threading
paths, the options that change the output, refusals and batch mode) and compares the outputs
byte for byte; exit status 0 when every case is the same. The release's page then gives the
case counts, the builds' SHA-256 and a run in which the check fails on purpose.

## Run it

On Linux, with dsd-measure 0.1.2 installed (`pipx install
git+https://github.com/dsd-toolbox/dsd-measure@v0.1.2`) and the two release binaries:

```sh
tools/quality-compare.sh old/dsd-upsample new/dsd-upsample 0.1.0
```

It measures both builds, writes `docs/quality/0.1.0.md` and keeps the full dsd-measure reports
in `target/quality/0.1.0/`. Exit status: 0 every change beyond repeatability is explained by a
recorded decision (or there is none), 1 at least one is not, 2 the run failed. A failure blocks
the release until the change is fixed or explained and accepted in the design decisions.

| Option | Meaning |
|---|---|
| `--jobs N` | dsd-measure processes at a time (default 4) |
| `--old-label TEXT`, `--new-label TEXT` | Build names in the table (default: `--version` output and VERSION) |
| `--dry-run` | Run with another dsd-measure version or `--profile`; the page goes to `target/quality/` and is marked as a dry run |
| `--profile quick` | dsd-measure's quick profile instead of the suite's full one, for iterating; dry runs only |
| `--repeat N CLI` | Measure one build N times and print the spread per metric |
| `--resume` | Keep the work folder and reuse the device reports and null tests already in it (after an interrupted run) |
| `--only GLOB` | Measure and null-test only the devices whose name matches (repeatable, for example `--only '*DSD256*'`); writes no page. For splitting a run across machines |
| `--merge DIR` | Copy the device reports and null tests of another work folder in first (repeatable; implies `--resume`), then measure whatever is still missing and write the page |

To split a run, measure each share in its own work folder with `--only`, copy the folders to one
machine and run once more with a `--merge` for each. Every device report and null test records
where it ran (host, CPU, wall time, peak memory of its largest process) next to it
(`NAME.host.json`); the page names the CPUs and `summary.json` keeps the rest.

The gate uses dsd-measure's full profile (the suite's `profile`). With dsd-measure 0.1.2 it needs
more than 20 GB for a single DSD256 conversion (the 60 s stability holds are held in memory
whole), so `--jobs` is set by memory, not by cores: plan for 24 GB per job. While iterating, run
`tools/quality-compare.sh --dry-run --profile quick OLD-CLI NEW-CLI VERSION`: both parts for two
builds take about 30 minutes with `--jobs 8` on a Ryzen AI 9 HX 370 with 12 threads (the
DSD64-input rows take longest: the reference modulator runs in every test) and stay under 20 GB.
A quick-profile page is marked as a dry run and is not a release record.

Part of the [DSD Toolbox](https://github.com/dsd-toolbox/dsd-toolbox).
