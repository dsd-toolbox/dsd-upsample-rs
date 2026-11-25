#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Fails unless every ELF file given needs at most glibc FLOOR: the highest GLIBC_x.y
# symbol version in its dynamic symbol table must be <= FLOOR. The Linux archives promise
# glibc 2.34 or later (README, Platforms), so the release checks its binaries with this.
#
#   sh tools/glibc-floor.sh 2.34 target/release/dsd-upsample target/release/libdsd_upsample.so
set -eu
[ "$#" -ge 2 ] || { echo "usage: glibc-floor.sh FLOOR ELF..." >&2; exit 2; }
floor=$1; shift
case $floor in *[!0-9.]*|"") echo "glibc-floor.sh: bad floor '$floor'" >&2; exit 2 ;; esac
fail=0
for f in "$@"; do
    [ -f "$f" ] || { echo "glibc-floor.sh: $f: no such file" >&2; exit 2; }
    # Version references in .dynsym/.gnu.version_r (objdump -T), e.g. "GLIBC_2.34".
    need=$(objdump -T "$f" | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/^GLIBC_//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)
    if [ -z "$need" ]; then
        echo "glibc-floor.sh: $f: no GLIBC symbol versions found" >&2
        fail=1
        continue
    fi
    top=$(printf '%s\n%s\n' "$need" "$floor" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)
    if [ "$top" = "$floor" ] || [ "$need" = "$floor" ]; then
        echo "ok    $f needs glibc $need (floor $floor)"
    else
        echo "FAIL  $f needs glibc $need, above the floor $floor"
        objdump -T "$f" | grep "GLIBC_$need" | head -n 5
        fail=1
    fi
done
exit $fail
