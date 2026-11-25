# Provenance

Source and licence of every borrowed idea, design method or table.

| Item | Source | Licence | Used for |
|---|---|---|---|
| NTF synthesis, CRFB realisation, state scaling | [python-deltasigma](https://github.com/ggventurini/python-deltasigma) 0.2.2 (G. Venturini), a port of R. Schreier's [Delta-Sigma Toolbox](https://www.mathworks.com/matlabcentral/fileexchange/19-delta-sigma-toolbox); run offline by `tools/gen_tables.py` | BSD-2-Clause | Modulator coefficient tables in `tables.rs` |
| Audio-band NTFs: Legendre zeros, maximally flat poles bisected to H_inf, CRFB coefficients from the pole polynomial | Our own NumPy code (`tools/modulator/design.py`), after [Schreier 1993](https://doi.org/10.1109/82.242348) and the pole family of the [Delta-Sigma Toolbox](https://www.mathworks.com/matlabcentral/fileexchange/19-delta-sigma-toolbox)'s `synthesizeNTF` (R. Schreier; [python-deltasigma](https://github.com/ggventurini/python-deltasigma) port, BSD-2-Clause) | Literature; BSD-2-Clause | Audio-band tables in `tables.rs` |
| Second-order modulator of loud test tones (two integrators, noise transfer function (1 − z⁻¹)²) | J. C. Candy, ["A Use of Double Integration in Sigma Delta Modulation"](https://doi.org/10.1109/TCOM.1985.1096276), IEEE Trans. Commun., 1985; our own Rust code | Literature | `testsignal.rs`, DSD test tones above 0 dB SACD |
| Legendre-zero reference modulator and stability ladder (idea) | [dsd-measure](https://github.com/dsd-toolbox/dsd-measure) (a DSD Toolbox project) | MIT OR Apache-2.0 | Starting point of the design study |
| CLANS pole optimisation (evaluated, not used) | Kenney & Carley, ["Design of multibit noise-shaping data converters"](https://doi.org/10.1007/BF01239365), Analog Integrated Circuits and Signal Processing 3, 1993; [python-deltasigma](https://github.com/ggventurini/python-deltasigma) `clans` | Literature; BSD-2-Clause | `docs/modulator-design.md` |
| CRFB structure and naming | R. Schreier & G. C. Temes, [*Understanding Delta-Sigma Data Converters*](https://doi.org/10.1109/9780470546772), Wiley 2005, ch. 4 and 8 | Literature | `modulator.rs` |
| Optimised NTF zeros, H_inf criterion (Lee) | [Schreier 1993](https://doi.org/10.1109/82.242348) (IEEE TCAS-II 40(8)); Lee 1987 (MIT thesis) via the textbook above | Literature | Modulator design |
| Kaiser window design, length and beta formulas | J. F. Kaiser, "Nonrecursive digital filter design using the I0-sinh window function", Proc. IEEE ISCAS 1974, pp. 20–23 (no online copy known); Oppenheim & Schafer, [*Discrete-Time Signal Processing*](https://openlibrary.org/works/OL3270902W), 3rd edition, Pearson 2010 | Literature | All FIR tables |
| Rational polyphase resampling (147/160) | Crochiere & Rabiner, [*Multirate DSP*](https://openlibrary.org/books/OL3502774M), 1983, ch. 2-3; our own NumPy design (`tools/gen_resampler.py`) and Rust code | Literature | `resample_table.rs`, `Resampler` in `filters.rs` |
| Half-band interpolators, multistage rate change | [Mintzer 1982](https://doi.org/10.1109/TASSP.1982.1163950); Crochiere & Rabiner, [*Multirate DSP*](https://openlibrary.org/books/OL3502774M), 1983 | Literature | `HB_*` tables |
| Byte lookup FIR (distributed arithmetic) | [Peled & Liu 1974](https://doi.org/10.1109/TASSP.1974.1162619); [White 1989](https://doi.org/10.1109/53.29648) | Literature | DSD128/256 decimator |
| Integrator clipping and reset for stability | [Schreier & Temes 2005](https://doi.org/10.1109/9780470546772), ch. 4 (stability of high-order modulators) | Literature | `modulator.rs` |
| SplitMix64 | Steele, Lea & Flood, [OOPSLA 2014](https://doi.org/10.1145/2660193.2660195) | Literature | Dither generator |
| 7-term Blackman-Harris window | H.-H. Albrecht, [ICASSP 2001](https://doi.org/10.1109/ICASSP.2001.940309) | Literature | `tools/measure.py`, `tools/measure/analyse.py` |
| Software reference decode (Archimago's "perfect DAC") measurement method, signal set (silence and ramp, 32-tone multitone, J-Test, SoX-DSD comparison) | [Archimago](https://archimago.blogspot.com/), [2021-10](https://archimago.blogspot.com/2021/10/measurements-look-at-dsd-and-using-sox.html) and [2022-06](https://archimago.blogspot.com/2022/06/notes-on-dac-dsd-1-bit-pdm-measurements.html) articles; the [dsd-measure footprint](https://github.com/dsd-toolbox/dsd-measure/blob/main/docs/footprint.md) (MIT OR Apache-2.0) for the test definitions | Method only; no text or figures copied | `tools/measure/`, `docs/measurements-dsd.md` |
| SINAD as the headline figure, 32-tone multitone | [Audio Science Review](https://www.audiosciencereview.com/) practice | Method only | `tools/measure/analyse.py` |
| J-Test in measurement reports | [Stereophile](https://www.stereophile.com/content/measurements-maps-precision) (J. Atkinson) practice; the test signal after J. Dunn | Method only | `tools/measure/signals.py` |
| 28-bit window density rule (at most 24 of 28 ones) | As restated in Archimago's [2022-06](https://archimago.blogspot.com/2022/06/notes-on-dac-dsd-1-bit-pdm-measurements.html) article | Public description | `tools/measure/density.py` |
| A-weighting | [IEC 61672](https://webstore.iec.ch/en/publication/5708) (published curve formula) | Literature | `tools/measure/analyse.py` |
| 0 dB SACD = 50 % modulation | Cirrus Logic CS4398 data sheet (DS568F1), analog characteristics, note 3 ([page 9](https://www.manualsdir.com/manuals/466334/cirrus-logic-cs4398.html?page=9)) | Public data sheet; one phrase quoted | `docs/modulator-design.md` (headroom, levels) |
| Super Audio CD level 6 dB below PCM full scale, undone by DSD to PCM conversion | Roon Labs, ["DSD to PCM Settings"](https://help.roonlabs.com/portal/en/kb/articles/dsd-to-pcm-settings) | Public documentation; cited, not copied | `docs/modulator-design.md` (headroom) |
| True peak (dBTP) | ITU-R [BS.1770](https://www.itu.int/rec/R-REC-BS.1770) (in force: BS.1770-5, 11/2023) | Published recommendation | `docs/modulator-design.md` (headroom), `tools/stability/` |
| True-peak levels of about 107,000 tracks by genre | Archimago, ["A look at the music library: How much DAC intersample overhead is enough?"](https://archimago.blogspot.com/2025/08/a-look-at-music-library-how-much.html), 2025-08-09 | Figures cited only | `docs/modulator-design.md` (headroom) |
| Intersample overs on commercial CDs | J. Siau, Benchmark Media Systems, ["Intersample Overs in CD Recordings"](https://benchmarkmedia.com/blogs/application_notes/intersample-overs-in-cd-recordings) | Figures cited only | `docs/modulator-design.md` (headroom) |
| Intersample overs, early paper | S. H. Nielsen and T. Lund, AES, 2000 ([AES e-library 9087](https://www.aes.org/e-lib/browse.cfm?elib=9087)) | Literature | `docs/modulator-design.md` (headroom) |
| Pink noise filter (seven first-order sections on white noise) | Paul Kellet's "refined" pink noise filter, as published in the music-dsp code archive ([musicdsp.org](https://www.musicdsp.org/en/latest/Filters/76-pink-noise-filter.html)) | Public posting, coefficients only | `crates/dsd-upsample/tests/stability.rs` |
| Pink noise by 1/√f spectral shaping | Textbook method | Literature | `tools/stability/stab.py` |
| Same-file test (device and inode, or volume and file index on Windows) | `same-file` crate (A. Gallant) | Unlicense OR MIT | Dependency |
| Ctrl-C handling in the CLI | `ctrlc` crate | MIT OR Apache-2.0 | Dependency (CLI only) |
| DSF/DFF/WAV I/O, DSD64 decimator | `dsd2pcm` crate (sibling repo, MIT OR Apache-2.0), itself ported from scarletbook-pcm 0.7.0 (MIT OR Apache-2.0) | MIT OR Apache-2.0 | Dependency |
| SHA-256 for the golden-hash tests | `sha2` crate (RustCrypto) | MIT OR Apache-2.0 | Dev-dependency (tests only) |
| Offline table generation and measurement scripts | NumPy (BSD-3-Clause), SciPy (BSD-3-Clause), [python-deltasigma](https://github.com/ggventurini/python-deltasigma) (BSD-2-Clause), Matplotlib (Matplotlib licence, PSF-based), pinned in `tools/requirements.txt` | As listed | `tools/` only; never linked into the library |

No GPL or LGPL code, tables or coefficients are used. SoX source was not consulted for the
library's design. SoX-DSD (GPL-2.0-or-later) is only run as a separate binary to provide
reference measurements; nothing from it is copied or linked.
