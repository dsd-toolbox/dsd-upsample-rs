# SPDX-License-Identifier: MIT OR Apache-2.0
"""Import shim for python-deltasigma 0.2.2 (BSD-2-Clause) on Python 3.9 / NumPy 1.21.

The package predates removals in the standard library; this restores the aliases it
needs before import. Used only by offline table generation; never by the library.
"""
import fractions
import math

import numpy.random as _npr

if not hasattr(fractions, "gcd"):
    fractions.gcd = math.gcd

# scaleABCD passes a float sample count to randn(); newer NumPy rejects that.
_randn = _npr.randn


def _randn_int(*shape):
    return _randn(*[int(s) for s in shape])


_npr.randn = _randn_int

import deltasigma  # noqa: E402,F401  (re-exported)

ds = deltasigma
