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

for pkg in "$ROOT"/packages/*/; do
    [ -f "${pkg}debian/control" ] || continue
    echo "== building $(basename "$pkg") =="
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
