#!/bin/sh
# Bump a Sysible package's version so apt sees an upgrade, then commit + tag to
# ship it. Usage: scripts/bump-version.sh <package> "changelog message"
set -e
PKG="$1"; MSG="${2:-update}"
CL="packages/$PKG/debian/changelog"
[ -f "$CL" ] || { echo "no such package: $PKG ($CL missing)"; exit 1; }
VER=$(sed -n '1s/^[^(]*(\([^)]*\)).*/\1/p' "$CL")
BASE=${VER%.*}; PATCH=${VER##*.}; NEW="$BASE.$((PATCH+1))"
DATE=$(date -u +'%a, %d %b %Y %H:%M:%S +0000')
printf '%s (%s) sysible; urgency=medium\n\n  * %s\n\n -- Sysible <maintainers@sysible.io>  %s\n\n%s' \
    "$PKG" "$NEW" "$MSG" "$DATE" "$(cat "$CL")" > "$CL"
echo "$PKG: $VER -> $NEW"
echo "Next: git commit, then push to main (sysible-dev) or 'git tag vX.Y && git push --tags' (sysible-stable)."
