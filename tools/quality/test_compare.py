# SPDX-License-Identifier: MIT OR Apache-2.0
"""Unit tests for the explained-change check of tools/quality/compare.py (no measuring, no dsd-measure).

    python3 -I tools/quality/test_compare.py

Uses the suite's real [[quality.explained]] entries and the changes measured by the 0.1.0-rc2
quick- and full-profile dry runs (v0.1.0-rc1 against the build that moved the default gain, dsd-measure 0.1.2).
"""
import importlib.util
import sys
import tomllib
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    import numpy  # noqa: F401  (compare.py imports it for measuring; these tests do not need it)
except ImportError:
    sys.modules["numpy"] = types.ModuleType("numpy")
spec = importlib.util.spec_from_file_location("compare", HERE / "compare.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)

CFG = tomllib.loads(compare.SUITE.read_text())
RC2 = [e for e in CFG["quality"]["explained"] if e["version"] == "0.1.0-rc2"]
DEVICES = compare.Runner(types.SimpleNamespace(profile=None, only=None), CFG, HERE).devices()

#: (conversion, input rate) -> change per metric in dB (new minus previous), part (b), full profile.
FULL = {
    ("PCM to DSD64", 44100): {"sinad_db": -2.131, "thd_db": 1.318, "noise_a_dbfs": 2.981, "dr_a_db": -2.679},
    ("PCM to DSD128", 44100): {"sinad_db": -2.801, "thd_db": 1.695, "noise_a_dbfs": 2.873, "dr_a_db": -1.235},
    ("PCM to DSD256", 44100): {"sinad_db": -3.337, "thd_db": 3.643, "noise_a_dbfs": 2.955, "dr_a_db": -2.518},
    ("DSD64 to DSD128", 44100): {"sinad_db": -0.367, "thd_db": 1.090, "noise_a_dbfs": 0.241, "dr_a_db": 1.191},
    ("DSD64 to DSD256", 44100): {"sinad_db": 0.002, "thd_db": -0.017, "noise_a_dbfs": 0.094, "dr_a_db": -0.105},
    ("PCM to DSD64", 48000): {"sinad_db": -2.468, "thd_db": 1.288, "noise_a_dbfs": 2.996, "dr_a_db": -3.197},
    ("PCM to DSD128", 48000): {"sinad_db": -2.532, "thd_db": 1.510, "noise_a_dbfs": 3.028, "dr_a_db": -2.442},
    ("PCM to DSD256", 48000): {"sinad_db": -3.391, "thd_db": 2.553, "noise_a_dbfs": 3.098, "dr_a_db": -1.660},
}
#: The same from the quick-profile dry run: the changes its page flags (0.1 dB), the rest within
#: repeatability.
QUICK = {
    ("PCM to DSD64", 44100): {"sinad_db": -2.5, "thd_db": 0.2, "noise_a_dbfs": 3.0, "dr_a_db": -3.1},
    ("PCM to DSD128", 44100): {"sinad_db": -2.5, "thd_db": 1.5, "noise_a_dbfs": 2.3, "dr_a_db": -2.7},
    ("PCM to DSD256", 44100): {"sinad_db": -3.2, "thd_db": 3.9, "noise_a_dbfs": 2.8, "dr_a_db": -3.5},
    ("DSD64 to DSD128", 44100): {"sinad_db": -0.4, "thd_db": 1.0, "noise_a_dbfs": 0.3, "dr_a_db": -2.0},
    ("DSD64 to DSD256", 44100): {"noise_a_dbfs": 0.1},
    ("PCM to DSD64", 48000): {"sinad_db": -2.5, "thd_db": 1.5, "noise_a_dbfs": 2.9, "dr_a_db": -2.6},
    ("PCM to DSD128", 48000): {"sinad_db": -2.8, "thd_db": 1.5, "noise_a_dbfs": 2.4, "dr_a_db": -3.0},
    ("PCM to DSD256", 48000): {"sinad_db": -3.4, "thd_db": 2.4, "noise_a_dbfs": 2.8, "dr_a_db": -4.3},
}
MEASURED = [(n, r, m, d) for src in (FULL, QUICK) for (n, r), v in src.items() for m, d in v.items()]


def why(delta, name, rate, metric="dr_a_db", part="defaults", entries=RC2):
    return compare.explanation(entries, part, metric, delta, name, rate)


class Paths(unittest.TestCase):
    def test_no_paths_covers_every_conversion(self):
        e = {"part": "defaults", "metrics": ["dr_a_db"], "min_db": -5.0, "max_db": 5.0, "decision": "d"}
        for r, d in DEVICES:
            self.assertTrue(compare.covers(e, d["name"], r), d["name"])

    def test_spellings(self):
        cases = {
            "PCM to DSD128": True,
            "PCM to DSD128 from 44.1 kHz": True,
            "PCM to DSD128 from 48 kHz": False,
            "PCM-to-DSD128": True,
            "PCM-to-DSD128-*": True,
            "PCM-to-DSD128-from-44-1-kHz": True,
            "*DSD128": True,
            "PCM to DSD12": False,
            "PCM to DSD256": False,
            "DSD64 to DSD128": False,
        }
        for pat, want in cases.items():
            self.assertEqual(compare.covers({"paths": [pat]}, "PCM to DSD128", 44100), want, pat)

    def test_exact_name_does_not_cover_the_explicit_part(self):
        self.assertFalse(compare.covers({"paths": ["PCM to DSD128"]}, "PCM to DSD128 explicit", 44100))


class Rc2(unittest.TestCase):
    def test_every_measured_change_is_explained(self):
        for name, rate, m, delta in MEASURED:
            if abs(delta) > CFG["quality"]["repeatability"][m]:
                self.assertIsNotNone(why(delta, name, rate, m), f"{name} from {rate}: {m} {delta:+.3f}")

    def test_wrong_direction_fails(self):
        # Wherever an entry's range has one sign, the measured change with its sign flipped must fail.
        checked = 0
        for name, rate, m, delta in MEASURED:
            e = why(delta, name, rate, m)
            if e and (e["min_db"] > 0 or e["max_db"] < 0) and abs(delta) > 0.2:
                self.assertIsNone(why(-delta, name, rate, m), f"{name} from {rate}: {m} {-delta:+.3f}")
                checked += 1
        self.assertGreater(checked, 30)
        # The direction of the decision: SINAD and dynamic range fall, noise floor and THD rise.
        for name in ("PCM to DSD64", "PCM to DSD128", "PCM to DSD256"):
            for rate in (44100, 48000):
                for m, d in (("sinad_db", +0.5), ("dr_a_db", +0.5), ("noise_a_dbfs", -0.5), ("thd_db", -0.5)):
                    self.assertIsNone(why(d, name, rate, m), f"{name} from {rate}: {m} {d:+}")
        for m, d in (("sinad_db", +0.5), ("thd_db", -0.5), ("noise_a_dbfs", -0.5)):
            self.assertIsNone(why(d, "DSD64 to DSD128", 44100, m), m)

    def test_no_entry_without_a_measured_change(self):
        # DSD64 to DSD256 SINAD and THD stayed within repeatability: any change beyond it fails.
        for m in ("sinad_db", "thd_db"):
            for d in (-0.2, 0.2, -3.0):
                self.assertIsNone(why(d, "DSD64 to DSD256", 44100, m), f"{m} {d:+}")

    def test_pcm_ranges_do_not_cover_dsd64_input(self):
        # The PCM changes are about 3 dB: from DSD64 input they fail.
        self.assertIsNone(why(-2.5, "DSD64 to DSD128", 44100, "sinad_db"))
        self.assertIsNone(why(+3.0, "DSD64 to DSD128", 44100, "noise_a_dbfs"))
        self.assertIsNone(why(+3.0, "DSD64 to DSD256", 44100, "noise_a_dbfs"))
        self.assertIsNone(why(-0.4, "PCM to DSD64", 44100, "sinad_db"))

    def test_dsd128_range_only_on_dsd128(self):
        # -1.0 dB is inside the PCM to DSD128 range, outside the DSD64 and DSD256 ones.
        self.assertIsNotNone(why(-1.0, "PCM to DSD128", 48000))
        self.assertIsNone(why(-1.0, "PCM to DSD64", 48000))
        self.assertIsNone(why(-1.0, "PCM to DSD256", 48000))
        # +1.2 dB (DSD64 to DSD128, full) is explained there and nowhere else.
        self.assertIsNotNone(why(1.2, "DSD64 to DSD128", 44100))
        for name in ("DSD64 to DSD256", "PCM to DSD64", "PCM to DSD128", "PCM to DSD256"):
            self.assertIsNone(why(1.2, name, 44100), name)
        self.assertIsNone(why(+1.6, "DSD64 to DSD128", 44100))  # the DSD128 range still has an upper end

    def test_cross_state_jump_is_not_explained(self):
        # Builds in different DSD128 low-level states differ by about 10 dB (README, Known limits).
        for d in (-10.0, 10.0):
            self.assertIsNone(why(d, "PCM to DSD128", 44100))
            self.assertIsNone(why(d, "DSD64 to DSD128", 44100))

    def test_explicit_part_has_no_entries(self):
        for m in ("sinad_db", "thd_db", "noise_a_dbfs", "dr_a_db"):
            self.assertIsNone(why(-2.7, "PCM to DSD64 explicit", 44100, m, part="explicit"))
            self.assertIsNone(why(+2.7, "PCM to DSD64 explicit", 44100, m, part="explicit"))

    def test_every_entry_has_paths(self):
        self.assertTrue(all(e.get("paths") for e in RC2))


class CheckExplained(unittest.TestCase):
    def test_suite_entries_are_valid(self):
        compare.check_explained(CFG["quality"]["explained"], DEVICES)

    def bad(self, **kw):
        e = {"version": "x", "part": "defaults", "metrics": ["dr_a_db"], "min_db": -1.0, "max_db": 1.0, "decision": "d"}
        e.update(kw)
        with self.assertRaises(compare.Fail):
            compare.check_explained([e], DEVICES)

    def test_refused(self):
        self.bad(paths=["PCM to DSD512"])          # matches nothing
        self.bad(paths=["PCM to DSD64 explicit"])  # a part (a) name in a part (b) entry
        self.bad(paths="PCM to DSD64")             # not a list
        self.bad(paths=[])
        self.bad(paths=[""])
        self.bad(metrics=["dr_db"])
        self.bad(part="both")
        self.bad(min_db=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
