#!/bin/sh
# Fast, environment-independent branding guard.
#
# Verifies every committed logo asset still matches the sha256 recorded in the
# branding manifest — i.e. nothing has drifted from the canonical mark
# (branding/logo/sysible-mark.svg). This is the check that stops the boot logo
# from silently falling behind the dock icon again.
#
# It compares sha256 of the COMMITTED bytes to the manifest, so it does NOT
# re-render and is immune to Pillow/cairosvg/FreeType version differences — the
# same result on any machine. Run it in CI BEFORE the ~35-minute ISO build so a
# stale logo fails in seconds.
#
# If it fails: run  python3 branding/render-branding.py  and commit the result.
set -e
cd "$(CDPATH= cd "$(dirname "$0")/.." && pwd)"

MAN=branding/logo/BRANDING.manifest
IMG_MAN=live-build/config/includes.chroot/usr/share/sysible/branding.manifest

[ -f "$MAN" ] || { echo "verify-branding: missing $MAN — run branding/render-branding.py" >&2; exit 1; }

# The in-image twin must be identical, or the installed system would verify
# against a different manifest than CI does.
if ! cmp -s "$MAN" "$IMG_MAN"; then
    echo "verify-branding: $IMG_MAN differs from $MAN (regenerate branding)" >&2
    exit 1
fi

fail=0
while IFS= read -r line; do
    case "$line" in ''|'#'*) continue;; esac
    sha=${line%% *}
    path=${line#* }
    path=${path# }
    if [ ! -f "$path" ]; then
        echo "verify-branding: MISSING $path" >&2; fail=1; continue
    fi
    act=$(sha256sum "$path" | awk '{print $1}')
    if [ "$act" != "$sha" ]; then
        echo "verify-branding: DRIFT $path" >&2
        echo "    manifest=$sha" >&2
        echo "    actual  =$act" >&2
        fail=1
    fi
done < "$MAN"

if [ "$fail" != 0 ]; then
    echo >&2
    echo "Branding assets are out of sync with the canonical mark." >&2
    echo "Fix: python3 branding/render-branding.py   (then commit the regenerated files)" >&2
    exit 1
fi

n=$(grep -cvE '^\s*(#|$)' "$MAN")
echo "verify-branding: OK — $n assets match the canonical mark (branding/logo/sysible-mark.svg)."
