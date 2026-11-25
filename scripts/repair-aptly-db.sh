#!/bin/sh
# Rebuild a local aptly repo from the package pool, for when the database
# references a package it cannot load:
#
#   ERROR: unable to load packages: unable to load package with key
#     Pall sysible-app-connect 0.1.0+ci... : key not found
#
# WHY A REBUILD AND NOT A TARGETED REMOVE. Every aptly CLI path that touches a
# repo loads its whole package set first, so `repo remove`, `repo add` and
# `repo show -with-packages` all die on the same dangling entry that needs
# removing. Verified against a database corrupted on purpose: by raw package
# ref, by name, and by query -- all three fail identically. aptly has no way to
# repair this from the command line, so the repair has to go around it.
#
# The pool is the source of truth: it holds the actual .deb files, and a
# dangling entry means the DATABASE RECORD is missing, usually not the file. So
# dropping the repo record and re-adding from the pool restores the package
# rather than dropping it -- including packages belonging to OTHER products
# that share this suite, which a targeted removal would have evicted from the
# archive until they next published.
#
# Only the newest version of each package/architecture is re-added. The pool
# keeps every +ci build ever published; adding all of them would publish every
# historical version, growing the index and the published pool without bound.
#
# Usage: repair-aptly-db.sh <suite>
set -eu

SUITE="${1:?usage: repair-aptly-db.sh <suite>}"
ROOTDIR=$(aptly config show 2>/dev/null \
          | sed -n 's/.*"rootDir"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
[ -n "$ROOTDIR" ] || { echo "repair: cannot read rootDir from aptly config" >&2; exit 1; }
POOL="$ROOTDIR/pool"
[ -d "$POOL" ] || { echo "repair: no package pool at $POOL — nothing to rebuild from" >&2; exit 1; }

echo "repair: rebuilding '$SUITE' from the package pool at $POOL"

pick=$(mktemp -d)
trap 'rm -rf "$pick"' EXIT
found=0
for f in $(find "$POOL" -name '*.deb' 2>/dev/null); do
    pn=$(dpkg-deb -f "$f" Package 2>/dev/null) || continue
    pv=$(dpkg-deb -f "$f" Version 2>/dev/null) || continue
    pa=$(dpkg-deb -f "$f" Architecture 2>/dev/null) || continue
    [ -n "$pn" ] && [ -n "$pv" ] || continue
    found=$((found + 1))
    slot="$pick/${pn}.${pa}"
    if [ -f "$slot" ]; then
        cv=$(cut -d' ' -f1 < "$slot")
        dpkg --compare-versions "$pv" gt "$cv" || continue
    fi
    printf '%s %s\n' "$pv" "$f" > "$slot"
done
[ "$found" -gt 0 ] || { echo "repair: the pool holds no readable .deb files" >&2; exit 1; }

# Drop the repo RECORD only. Snapshots and the published tree are separate
# objects; the publish that follows this repair re-creates what it needs.
# swallow-ok: the repo record may already be gone, which is where this is
# trying to get to. A real problem surfaces on the create/add below.
aptly repo drop -force "$SUITE" >/dev/null 2>&1 || true  # swallow-ok
aptly repo create -distribution="$SUITE" -component=main "$SUITE" >/dev/null

set --
for slot in "$pick"/*; do
    [ -f "$slot" ] || continue
    set -- "$@" "$(cut -d' ' -f2- < "$slot")"
done
[ "$#" -gt 0 ] || { echo "repair: nothing selected to re-add" >&2; exit 1; }
aptly repo add -force-replace "$SUITE" "$@" >/dev/null

echo "repair: '$SUITE' rebuilt — $# package(s) re-added, newest of each, from $found pool file(s)"
