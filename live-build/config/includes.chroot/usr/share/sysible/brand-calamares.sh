#!/bin/sh
# Rebuild Debian's Calamares with the Sysible partition/status icons and install
# it over the stock package. Runs inside the live-build chroot (the matching
# Debian environment), so the source and version line up exactly.
#
# `set -e`: any step failing aborts the whole thing; the caller (the hook) treats
# a non-zero exit as non-fatal and keeps the stock Calamares, so a build-env
# hiccup here never breaks the ISO.
set -e

ICONS=/usr/share/sysible/calamares-icons
export DEBIAN_FRONTEND=noninteractive

echo "== sysible: rebranding Calamares icons =="
[ -d "$ICONS" ]

# deb-src for bookworm main, so we can fetch the source + build-deps.
if ! grep -Rqs '^deb-src .*bookworm' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
    echo "deb-src http://deb.debian.org/debian bookworm main" \
        > /etc/apt/sources.list.d/sysible-calamares-src.list
fi
apt-get update
apt-get install -y --no-install-recommends build-essential fakeroot dpkg-dev
apt-get build-dep -y calamares

work="$(mktemp -d)"
cd "$work"
apt-get source calamares
src="$(find . -maxdepth 1 -type d -name 'calamares-*' | head -1)"
[ -n "$src" ]

# Swap each icon resource wherever it lives in the source tree (path-agnostic
# across Calamares versions).
swapped=0
for f in partition-disk partition-erase-auto partition-alongside partition-replace-os \
         partition-manual state-ok state-warning state-error; do
    for tgt in $(find "$src" -type f -name "$f.svg" 2>/dev/null); do
        cp -f "$ICONS/$f.svg" "$tgt"
        swapped=$((swapped + 1))
    done
done
echo "== sysible: swapped $swapped Calamares icon file(s) =="
[ "$swapped" -gt 0 ]

( cd "$src" && dpkg-buildpackage -us -uc -b )
dpkg -i "$work"/calamares_*.deb
apt-get -y -f install

# Keep the ISO lean: drop build-deps and the source tree again.
cd /
rm -rf "$work"
rm -f /etc/apt/sources.list.d/sysible-calamares-src.list
apt-get -y autoremove --purge || true
apt-get clean || true
echo "== sysible: Calamares rebrand complete =="
