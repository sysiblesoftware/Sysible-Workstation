#!/bin/sh
# Build every Sysible package to a .deb and collect them in ../dist/.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$ROOT/dist"
mkdir -p "$DIST"
rm -f "$DIST"/*.deb

if [ "$(id -u)" = 0 ]; then SUDO=; else SUDO="sudo"; fi
if [ "${SYSIBLE_SKIP_DEPS:-0}" != "1" ]; then
    echo "== installing build dependencies =="
    $SUDO apt-get update -qq || true
    $SUDO apt-get install -y --no-install-recommends \
        build-essential debhelper dh-python python3-all python3-setuptools \
        pybuild-plugin-pyproject
fi

# --- Cache-safe unique versions -------------------------------------------
# The apt pool is served through Cloudflare and cached `immutable`, but pool
# paths are NOT content-addressed: they're named `<pkg>_<version>_<arch>.deb`.
# So rebuilding the SAME version with different bytes (any non-reproducible
# build, or an edit that keeps the changelog version) re-uploads to the SAME
# path while the fresh no-cache index describes the new bytes — the edge keeps
# serving the OLD cached .deb and apt dies with "File has unexpected size".
#
# Fix at the root: stamp a unique, monotonic suffix onto every package version
# in CI (SYSIBLE_VERSION_SUFFIX, e.g. "+ci<run-number>"), so each publish lands
# at a BRAND-NEW pool path the edge has never cached. `aptly repo add
# -force-replace` then drops the old version, apt sees a higher version and
# fetches the fresh path (cache miss → correct bytes). This self-heals a stale
# repo on the very next publish with no CDN purge required. Left empty for local
# builds so developer .debs keep their clean changelog version.
#
# Dependency-free: dpkg-parsechangelog (dpkg-dev) + date -uR (coreutils), both
# already present — no devscripts/dch needed.
SUFFIX="${SYSIBLE_VERSION_SUFFIX:-}"
stamp_changelog() {
    # $1 = path to a debian/changelog. Prepends a new top entry that only bumps
    # the version to <base><SUFFIX>, leaving package contents untouched.
    cl="$1"
    [ -n "$SUFFIX" ] || return 0
    src=$(dpkg-parsechangelog -l "$cl" -S Source)
    ver=$(dpkg-parsechangelog -l "$cl" -S Version)
    dist=$(dpkg-parsechangelog -l "$cl" -S Distribution)
    [ "$dist" = "UNRELEASED" ] && dist=sysible
    # Idempotent: never stamp twice in one run.
    case "$ver" in *"$SUFFIX") return 0 ;; esac
    newver="${ver}${SUFFIX}"
    ts=$(date -uR)
    tmp=$(mktemp)
    {
        printf '%s (%s) %s; urgency=medium\n\n' "$src" "$newver" "$dist"
        printf '  * CI build %s — unique version for cache-safe publishing.\n\n' "${SUFFIX#+}"
        printf ' -- Sysible <maintainers@sysible.com>  %s\n\n' "$ts"
        cat "$cl"
    } > "$tmp"
    mv "$tmp" "$cl"
    echo "   version → $newver"
}

for pkg in "$ROOT"/packages/*/; do
    [ -f "${pkg}debian/control" ] || continue
    echo "== building $(basename "$pkg") =="
    stamp_changelog "${pkg}debian/changelog"
    ( cd "$pkg" && dpkg-buildpackage -us -uc -b )
    mv "$ROOT"/packages/*.deb "$DIST"/ 2>/dev/null || true
    rm -f "$ROOT"/packages/*.buildinfo "$ROOT"/packages/*.changes 2>/dev/null || true
done

# --- SysTerm: external repo, built here so its .deb publishes to the apt repo
# alongside the sysible-* packages (sysible-meta Depends: systerm). Guarded so an
# offline/ISO context can skip it (the ISO build already builds SysTerm itself).
if [ "${SYSIBLE_SKIP_SYSTERM:-0}" != "1" ]; then
    echo "== building systerm (from dev) =="
    rm -rf /tmp/systerm-src
    if git clone --depth 1 --branch dev https://github.com/sysiblesoftware/SysTerm /tmp/systerm-src; then
        stamp_changelog /tmp/systerm-src/debian/changelog
        if ( cd /tmp/systerm-src && dpkg-buildpackage -us -uc -b ); then
            mv /tmp/systerm_*.deb "$DIST"/ 2>/dev/null || true
        else
            echo "WARNING: systerm build failed — publishing without it" >&2
        fi
    else
        echo "WARNING: systerm clone failed — publishing without it" >&2
    fi
fi

echo
echo "Built into $DIST:"
ls -1 "$DIST"/*.deb
