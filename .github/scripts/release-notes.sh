#!/bin/sh
# Release notes from CHANGELOG.md: the body of the "## VERSION - DATE" section, up to the
# next "## " heading.
#   sh .github/scripts/release-notes.sh [--allow-placeholder] [--link-base URL] VERSION [CHANGELOG]
# Fails if the section is missing or empty, or if its heading has no real date (YYYY-MM-DD).
# --allow-placeholder accepts the LAUNCH-DATE placeholder: for checks on untagged refs only.
# --link-base URL rewrites relative links (docs/x.md) to URL/docs/x.md, since a release page
# does not resolve links against the repository.
set -eu
allow=0
base=
while [ $# -gt 0 ]; do
  case $1 in
    --allow-placeholder) allow=1; shift ;;
    --link-base) [ $# -ge 2 ] || { echo "error: --link-base needs a URL" >&2; exit 2; }; base=${2%/}; shift 2 ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "usage: $0 [--allow-placeholder] [--link-base URL] VERSION [CHANGELOG]" >&2; exit 2; }
version=$1
changelog=${2:-CHANGELOG.md}
[ -r "$changelog" ] || { echo "error: cannot read $changelog" >&2; exit 1; }

heading=$(awk -v v="$version" 'index($0, "## " v " - ") == 1 { print; exit }' "$changelog")
[ -n "$heading" ] || { echo "error: no '## $version - DATE' section in $changelog" >&2; exit 1; }
date=${heading#"## $version - "}
case $date in
  LAUNCH-DATE)
    [ "$allow" = 1 ] || { echo "error: $changelog section $version still says LAUNCH-DATE" >&2; exit 1; } ;;
  [0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]) ;;
  *) echo "error: $changelog section $version has no date (YYYY-MM-DD): '$heading'" >&2; exit 1 ;;
esac

body=$(awk -v v="$version" '
  index($0, "## " v " - ") == 1 { on = 1; next }
  on && /^## / { exit }
  on { print }' "$changelog")
printf '%s\n' "$body" | grep -q '[^[:space:]]' \
  || { echo "error: $changelog section $version is empty" >&2; exit 1; }
if [ "$allow" = 0 ] && printf '%s\n' "$body" | grep -q 'LAUNCH-DATE'; then
  echo "error: $changelog section $version still says LAUNCH-DATE" >&2; exit 1
fi
if [ -n "$base" ]; then
  body=$(printf '%s\n' "$body" | sed -e "s|](\([^)#:][^):]*\))|]($base/\1)|g")
fi
# Trim leading and trailing blank lines.
printf '%s\n' "$body" | awk 'NF { started = 1 } started { lines[++n] = $0 }
  END { while (n > 0 && lines[n] ~ /^[[:space:]]*$/) n--; for (i = 1; i <= n; i++) print lines[i] }'
