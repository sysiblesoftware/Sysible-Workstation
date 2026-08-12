#!/bin/sh
# Publish the built .deb files to the Sysible apt repo with aptly, signed with
# the Sysible archive key. Two suites:
#   sysible-dev     mutable, republished in place on every push (CI)
#   sysible-stable  immutable snapshots, promoted for releases
#
# Usage:
#   ./publish-repo.sh [sysible-dev|sysible-stable]
#
# Environment:
#   SYSIBLE_GPG_KEY        signing key id/email        (default maintainers@sysible.com)
#   SYSIBLE_APTLY_ENDPOINT aptly publishing endpoint    (default "" = local filesystem
#                          rootDir; for S3 use e.g. "s3:sysible:")
#   GNUPGHOME              must hold the private signing key
set -e

SUITE="${1:-sysible-dev}"
case "$SUITE" in sysible-dev|sysible-stable) ;; *) echo "unknown suite: $SUITE" >&2; exit 2;; esac

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$ROOT/dist"
GPGKEY="${SYSIBLE_GPG_KEY:-maintainers@sysible.com}"
ENDPOINT="${SYSIBLE_APTLY_ENDPOINT:-}"     # "" -> filesystem:; else e.g. s3:sysible:
PREFIX="${ENDPOINT}"                        # publish prefix (endpoint or empty)

# Ensure a signing key exists. Auto-create ONLY for a local filesystem publish;
# for a remote repo (S3/R2) refuse — auto-generating a throwaway key here would
# sign the archive with a key whose public half clients don't have, silently
# producing a repo nobody can verify. The key must be imported first.
if ! gpg --list-secret-keys "$GPGKEY" >/dev/null 2>&1; then
    if [ -n "$ENDPOINT" ]; then
        echo "ERROR: no signing key for '$GPGKEY' in GNUPGHOME=${GNUPGHOME:-$HOME/.gnupg}." >&2
        echo "Import the private key before publishing to '$ENDPOINT' — refusing to auto-generate a key clients won't trust." >&2
        exit 1
    fi
    echo "No signing key for '$GPGKEY' in GNUPGHOME=${GNUPGHOME:-$HOME/.gnupg}; generating it (local filesystem publish)..."
    "$ROOT/scripts/gen-signing-key.sh"
fi

ls "$DIST"/*.deb >/dev/null 2>&1 || { echo "no .deb in $DIST — run build-all.sh first" >&2; exit 1; }

# 1. Repo exists (idempotent), then (re)load the current .deb set.
aptly repo show "$SUITE" >/dev/null 2>&1 || \
    aptly repo create -distribution="$SUITE" -component=main "$SUITE"
aptly repo add -force-replace "$SUITE" "$DIST"/*.deb

if [ "$SUITE" = "sysible-dev" ]; then
    # Dev: publish the repo directly and update in place — fast, mutable.
    if aptly publish list -raw 2>/dev/null | grep -q "${PREFIX} ${SUITE}$"; then
        aptly publish update -batch -gpg-key="$GPGKEY" "$SUITE" "$PREFIX"
    else
        aptly publish repo -batch -gpg-key="$GPGKEY" -distribution="$SUITE" \
            -component=main "$SUITE" "$PREFIX"
    fi
else
    # Stable: immutable snapshot, then switch the published suite to it.
    SNAP="sysible-stable-$(date -u +%Y%m%d%H%M%S)"
    aptly snapshot create "$SNAP" from repo "$SUITE"
    if aptly publish list -raw 2>/dev/null | grep -q "${PREFIX} ${SUITE}$"; then
        aptly publish switch -batch -gpg-key="$GPGKEY" "$SUITE" "$PREFIX" "$SNAP"
    else
        aptly publish snapshot -batch -gpg-key="$GPGKEY" -distribution="$SUITE" \
            -component=main "$SNAP" "$PREFIX"
    fi
fi

echo "Published $SUITE (endpoint '${PREFIX:-filesystem}')."
