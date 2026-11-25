#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# The converter under test, as a dsd-measure class B device: runs the CLI named by DSDUP_CLI
# with the arguments it is given (IN.wav OUT.dsf --rate N). Used by suites/upconverter.toml; the level
# correction for the gain the build applies is set per build by tools/quality/compare.py, not here;
# tools/quality-compare.sh sets DSDUP_CLI for each build.
: "${DSDUP_CLI:?set DSDUP_CLI to the dsd-upsample binary under test}"
exec "$DSDUP_CLI" "$@"
