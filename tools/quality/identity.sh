#!/bin/bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# Byte identity of two CLI builds' output (docs/quality/README.md, "Byte identity"): the same
# inputs, made by OLD's own `gen`, converted by both with the same options, and the outputs
# compared byte for byte. 105 single-file cases (DSF, DFF and WAV input at every input rate;
# mono, stereo and 6 channels; every output rate; both threading paths; orders, dither, gain,
# limit, cutoff, DFF output, tags), 4 refusals (exit status and message equal) and batch mode
# with 1 and 4 workers. Prints one line per case and a summary; exit status 0 when every case
# is the same. WORKDIR is emptied first.
#
#   tools/quality/identity.sh OLD-CLI NEW-CLI WORKDIR
set -u
[ $# -eq 3 ] || { echo "usage: $0 OLD-CLI NEW-CLI WORKDIR" >&2; exit 2; }
OLD=$(readlink -f "$1") NEW=$(readlink -f "$2") W=$(readlink -m "$3")
case $W in /|"$HOME") echo "identity: WORKDIR $W refused" >&2; exit 2;; esac
rm -rf "$W"; mkdir -p "$W/in" "$W/old" "$W/new" "$W/bo" "$W/bn"
g() { "$OLD" gen "$@" >/dev/null 2>&1 || { echo "gen failed: $*"; exit 2; }; }
cd "$W/in" || exit 2
g d64.dsf --rate 64 --freq 997 --level -6 --seconds 10
g d64loud.dsf --rate 64 --freq 3000 --level 3 --seconds 4
g d64six.dsf --rate 64 --freq 440 --level -10 --seconds 3 --channels 6
g d64mono.dsf --rate 64 --freq 1000 --level -20 --seconds 3 --channels 1
g d64.dff --rate 64 --freq 997 --level -6 --seconds 5
g d128.dsf --rate 128 --freq 997 --level -6 --seconds 4
g d256.dsf --rate 256 --freq 997 --level -6 --seconds 3
g p441.wav --fs 44100 --freq 997 --level -1 --seconds 10 --bits 24
g p441loud.wav --fs 44100 --freq 5000 --level 0 --seconds 4 --bits 24
g p441mono.wav --fs 44100 --freq 1000 --level -20 --seconds 3 --channels 1 --bits 16
g p48.wav --fs 48000 --freq 997 --level -3 --seconds 5 --bits 16
g p48six.wav --fs 48000 --freq 440 --level -10 --seconds 3 --channels 6 --bits 24
g p882.wav --fs 88200 --freq 997 --level -3 --seconds 4 --bits f32
g p96.wav --fs 96000 --freq 997 --level -3 --seconds 3 --bits 32
g p1764.wav --fs 176400 --freq 997 --level -3 --seconds 3 --bits 24
g p192.wav --fs 192000 --freq 997 --level -3 --seconds 3 --bits f64
g p3528.wav --fs 352800 --freq 997 --level -3 --seconds 2 --bits 24
g p384.wav --fs 384000 --freq 997 --level -3 --seconds 2 --bits 24
cd "$W" || exit 2
n=0 same=0 diff=0 errs=0
case_() { # name ext args...
  local name=$1 ext=$2; shift 2
  local ro rn
  "$OLD" "$@" "old/$name.$ext" >/dev/null 2>"old/$name.err"; ro=$?
  "$NEW" "$@" "new/$name.$ext" >/dev/null 2>"new/$name.err"; rn=$?
  n=$((n+1))
  if [ $ro -ne $rn ]; then echo "DIFF-EXIT $name old=$ro new=$rn"; diff=$((diff+1)); return; fi
  if [ $ro -ne 0 ]; then
    if cmp -s "old/$name.err" "new/$name.err"; then echo "SAME-REFUSAL $name exit=$ro"; same=$((same+1)); errs=$((errs+1));
    else echo "DIFF-MESSAGE $name exit=$ro"; diff=$((diff+1)); fi
    return
  fi
  if cmp -s "old/$name.$ext" "new/$name.$ext"; then
    echo "SAME $name $(sha256sum < "new/$name.$ext" | cut -c1-16) $(stat -c %s "new/$name.$ext")"; same=$((same+1))
  else echo "DIFF $name"; diff=$((diff+1)); fi
}
for f in d64.dsf d64loud.dsf d64six.dsf d64mono.dsf d64.dff d128.dsf d256.dsf; do
  b=${f%.*}-${f##*.}
  for r in 128 256; do
    case_ "$b-r$r" dsf "in/$f" --rate $r
    case_ "$b-r$r-st" dsf "in/$f" --rate $r --single-thread
  done
done
for f in d64.dsf d64six.dsf d64.dff; do
  b=${f%.*}-${f##*.}
  for r in pcm88 pcm176 pcm352; do case_ "$b-$r" wav "in/$f" --rate $r; done
  case_ "$b-pcm176-c30" wav "in/$f" --rate pcm176 --cutoff 30
  case_ "$b-r128-cwide" dsf "in/$f" --rate 128 --cutoff wide
  case_ "$b-r256-c40" dsf "in/$f" --rate 256 --cutoff 40
done
for f in p441.wav p441loud.wav p441mono.wav p48.wav p48six.wav p882.wav p96.wav p1764.wav p192.wav p3528.wav p384.wav; do
  b=${f%.*}
  for r in 64 128 256; do
    case_ "$b-r$r" dsf "in/$f" --rate $r
  done
  case_ "$b-r128-st" dsf "in/$f" --rate 128 --single-thread
done
# options
case_ p441-r64-o8 dsf in/p441.wav --rate 64 --order 8
case_ p441-r64-o5 dsf in/p441.wav --rate 64 --order 5
case_ p441-r128-o5 dsf in/p441.wav --rate 128 --order 5
case_ p441-r128-o7 dsf in/p441.wav --rate 128 --order 7
case_ p441-r128-o8 dsf in/p441.wav --rate 128 --order 8
case_ p441-r256-o8 dsf in/p441.wav --rate 256 --order 8
case_ p441-r128-dither dsf in/p441.wav --rate 128 --dither
case_ p48six-r256-dither dsf in/p48six.wav --rate 256 --dither
case_ p441loud-r128-g0 dsf in/p441loud.wav --rate 128 --gain 0
case_ p441loud-r256-g0-l06 dsf in/p441loud.wav --rate 256 --gain 0 --limit 0.6
case_ d64loud-r128-g0 dsf in/d64loud.dsf --rate 128 --gain 0
case_ d64-r256-g-3 dsf in/d64.dsf --rate 256 --gain -3
case_ p441-r128-dff dff in/p441.wav --rate 128 --format dff
case_ d64-r256-dff dff in/d64.dsf --rate 256 --format dff
case_ p441-r128-tag dsf in/p441.wav --rate 128 --tag title=Identity --tag artist=Test
case_ d64-r128-tag dsf in/d64.dsf --rate 128 --tag album=Identity
# refusals: order 8 at DSD128 from DSD, DSD64 output from DSD input, a PCM rate from DSD128
case_ d64-r128-o8 dsf in/d64.dsf --rate 128 --order 8
case_ d64-r64 dsf in/d64.dsf --rate 64
case_ d128-pcm176 wav in/d128.dsf --rate pcm176
# batch mode (the worker threads are now joined): every input, two worker counts
for j in 1 4; do
  for d in bo bn; do rm -rf "$W/$d/j$j"; mkdir -p "$W/$d/j$j"; done
  "$OLD" in/p441.wav in/p48.wav in/p882.wav in/p1764.wav in/p384.wav in/p48six.wav in/d64.dsf in/d64six.dsf in/d128.dsf in/d256.dsf --rate 256 --out-dir "bo/j$j" --jobs $j >/dev/null 2>"bo/j$j.err"; ro=$?
  "$NEW" in/p441.wav in/p48.wav in/p882.wav in/p1764.wav in/p384.wav in/p48six.wav in/d64.dsf in/d64six.dsf in/d128.dsf in/d256.dsf --rate 256 --out-dir "bn/j$j" --jobs $j >/dev/null 2>"bn/j$j.err"; rn=$?
  n=$((n+1))
  if [ $ro -eq 0 ] && [ $rn -eq 0 ] && diff -r "bo/j$j" "bn/j$j" >/dev/null && [ "$(find "bn/j$j" -type f | wc -l)" -eq 10 ]; then
    echo "SAME batch-jobs$j 10 files"; same=$((same+1))
  else echo "DIFF batch-jobs$j old=$ro new=$rn"; diff=$((diff+1)); fi
done
echo "identity: $n cases, $same same ($errs of them identical refusals), $diff different"
[ $diff -eq 0 ]
