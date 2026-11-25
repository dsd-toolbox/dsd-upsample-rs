#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
# Release test plan item 7: measure the previous and the new build with the pinned dsd-measure
# suite (suites/upconverter.toml) and write docs/quality/VERSION.md.
#
#   tools/quality-compare.sh OLD-CLI NEW-CLI VERSION
#   tools/quality-compare.sh --dry-run [--profile quick] OLD-CLI NEW-CLI VERSION
#   tools/quality-compare.sh --repeat 3 CLI
#
# Exit status: 0 no regression, 1 a regression beyond repeatability, 2 the run failed.
# Needs dsd-measure (the version the suite pins) on PATH; its Python runs the comparison.
# Options and method: docs/quality/README.md.
set -eu
dm=$(command -v dsd-measure) || { echo "quality-compare: dsd-measure is not on PATH" >&2; exit 2; }
bin=$(dirname "$(readlink -f "$dm")")
py=$bin/python3
[ -x "$py" ] || py=$bin/python
[ -x "$py" ] || { echo "quality-compare: no Python next to $dm" >&2; exit 2; }
exec "$py" "$(dirname "$0")/quality/compare.py" "$@"
