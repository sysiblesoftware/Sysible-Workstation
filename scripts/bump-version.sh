#!/bin/sh
# Bump a Sysible package's debian/changelog: increment the version's last numeric
# component and prepend a new entry. apt only upgrades to a HIGHER version, so
# every user-facing change has to be bumped or installed systems never see it.
#
#   scripts/bump-version.sh <package> "what changed"
#
# <package> is a directory name under packages/ (e.g. sysible-release,
# sysible-artwork, sysible-branding). Prints "pkg: OLD -> NEW".
set -e
PKG="$1"; MSG="$2"
if [ -z "$PKG" ] || [ -z "$MSG" ]; then
    echo "usage: $0 <package> \"what changed\"" >&2
    exit 2
fi
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CH="$ROOT/packages/$PKG/debian/changelog"
[ -f "$CH" ] || { echo "no changelog: $CH" >&2; exit 1; }

# Current version is the text inside the first parentheses on line 1.
CUR=$(sed -n '1s/^[^(]*(\([^)]*\)).*/\1/p' "$CH")
[ -n "$CUR" ] || { echo "cannot parse version from $CH" >&2; exit 1; }

# Increment the last dot-separated component (0.1.0 -> 0.1.1). Any higher
# version is a valid upgrade; keeping it to the last component is predictable.
BASE=${CUR%.*}; LAST=${CUR##*.}
case "$LAST" in
    ''|*[!0-9]*) echo "last component of $CUR is not numeric; bump by hand" >&2; exit 1;;
esac
NEW="$BASE.$((LAST + 1))"

# RFC 2822 date for the changelog trailer.
DATE=$(date -R)
TMP=$(mktemp)
{
    echo "$PKG ($NEW) sysible; urgency=medium"
    echo
    echo "  * $MSG"
    echo
    echo " -- Sysible <maintainers@sysible.com>  $DATE"
    echo
    cat "$CH"
} > "$TMP"
mv "$TMP" "$CH"
echo "$PKG: $CUR -> $NEW"
