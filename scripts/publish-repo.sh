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
# Publish prefix. aptly spells "the root of this endpoint" as ".", and an EMPTY
# positional argument is NOT the same thing: `publish switch` then hunts for a
# publication at prefix "" and reports it missing, which broke the second of two
# local publishes (no endpoint set) while the first succeeded. `publish snapshot`
# happens to normalize an empty prefix itself, which is why the old drop-and-
# create code never tripped over it. Normalize once, here, so every aptly call
# downstream is handed a form aptly recognizes.
case "$ENDPOINT" in
    "")  PREFIX="." ;;          # no endpoint: local filesystem, root prefix
    *:)  PREFIX="${ENDPOINT}." ;;  # "filesystem:local:" -> "filesystem:local:."
    *)   PREFIX="$ENDPOINT" ;;
esac

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

# 1. Repo exists (idempotent). Loading the .deb set happens inside the retry
# unit below, NOT here: `repo add` reads the repo's existing packages to spot
# conflicts, so a dangling reference aborts it before any publish is attempted.
# Reproduced locally by deleting one package record out of the LevelDB and
# leaving its repo reference, which is the shape CI hit:
#   ERROR: unable to load packages: unable to load package with key ...
aptly repo show "$SUITE" >/dev/null 2>&1 || \
    aptly repo create -distribution="$SUITE" -component=main "$SUITE"

# 2. (Re)publish.
#
# The published tree is regenerated from scratch on every CI run: the publish
# dir is ephemeral (a fresh runner each time, then `aws s3 sync`ed to R2) while
# the aptly DATABASE is restored from the bucket. So aptly always believes a
# publication exists for a directory that is, on disk, empty.
#
# This used to be `publish drop ... >/dev/null 2>&1 || true` followed by a fresh
# `publish`, and that is what broke every publish once the DB had recorded one.
# When the drop fails -- for ANY reason -- `|| true` swallows it, and the create
# two lines later dies with
#
#   ERROR: prefix/distribution already used by another published repo
#
# naming the publication it refuses to replace, while the real reason the drop
# failed is nowhere in the log. Both Sysible Server and Sysible Workstation
# failed their releases exactly this way, silently, every time.
#
# aptly has primitives for "replace whatever is published here", so use them
# instead of deleting and recreating: `publish switch` for a snapshot
# publication, `publish update` for a repo one. Both rewrite the ENTIRE tree --
# verified against an empty publish dir: pool/ and dists/ come back complete,
# InRelease, Release and Release.gpg included -- which is precisely what makes
# them correct when the directory is ephemeral.
#
# Nothing is swallowed any more. If aptly fails, this script fails.
#
# Ask the DB what is published, and make an UNREADABLE DB fatal. Testing this
# with `publish show ... >/dev/null 2>&1` would have kept the old bug's shape:
# any error -- including "this database is unreadable" -- reads as "nothing is
# published there", and the script would then take the create path and die on
# aptly's "already used" message with the real cause hidden again.
#
# `publish list -raw` prints one "<storage>:<prefix> <distribution>" per
# publication. An endpoint with no path, and the bare local filesystem, both
# normalize their prefix to ".".
PUBLISHED=$(aptly publish list -raw) || {
    echo "ERROR: aptly could not read its database (rootDir per ~/.aptly.conf)." >&2
    echo "Refusing to publish: an unreadable DB must not look like an empty one." >&2
    exit 1
}
if printf '%s\n' "$PUBLISHED" | grep -qx "$PREFIX $SUITE"; then
    REPUBLISH=yes
else
    REPUBLISH=no
fi

# A publish can fail on a package the DATABASE references but no longer holds:
#
#   ERROR: unable to switch: unable to load package with key
#     Pall sysible-app-connect 0.1.0+ci20261125182740.r... : key not found
#
# That is a corrupt shared database, not a corrupt .deb. It happened because
# the database used to travel as a non-atomic directory sync (see
# scripts/aptly-state.sh, which replaced it with a single object). The archive
# itself is fine -- the entry simply points at data that is not there.
#
# aptly names the exact key it could not load, so the repair does not have to
# guess: drop that one package from the local repo and try again. Whichever
# product owns it re-adds it on its next publish, so this self-heals rather
# than wedging the pipeline for every product at once. It is deliberately
# loud, because silently dropping packages from an archive would be worse
# than failing.
publish_attempt() {
    # Everything that READS the existing package set lives in here, so any of
    # it can trigger a repair and be retried.
    aptly repo add -force-replace "$SUITE" "$DIST"/*.deb || return 1
    if [ "$SUITE" = "sysible-stable" ]; then
        aptly snapshot create "$SNAP" from repo "$SUITE" || return 1
        if [ "$REPUBLISH" = yes ]; then
            aptly publish switch -batch -gpg-key="$GPGKEY" -component=main \
                "$SUITE" "$PREFIX" "$SNAP"
        else
            aptly publish snapshot -batch -gpg-key="$GPGKEY" -distribution="$SUITE" \
                -component=main "$SNAP" "$PREFIX"
        fi
    else
        if [ "$REPUBLISH" = yes ]; then
            aptly publish update -batch -gpg-key="$GPGKEY" "$SUITE" "$PREFIX"
        else
            aptly publish repo -batch -gpg-key="$GPGKEY" -distribution="$SUITE" \
                -component=main "$SUITE" "$PREFIX"
        fi
    fi
}

attempt=0
log=$(mktemp)
while :; do
    attempt=$((attempt + 1))
    # The attempt number keeps the snapshot name unique across retries; the rest
    # keeps it unique across runs and products sharing this database.
    SNAP="sysible-stable-$(date -u +%Y%m%d%H%M%S)-r${GITHUB_RUN_ID:-local}.a${GITHUB_RUN_ATTEMPT:-0}.p$$.t$attempt"

    if publish_attempt >"$log" 2>&1; then
        cat "$log"; rm -f "$log"; break
    fi
    cat "$log" >&2

    # "Pall <name> <version> <hash>" -- name and version are all we need.
    key=$(sed -n 's/.*unable to load package with key \(.*\): key not found.*/\1/p' "$log" | head -1)
    if [ -z "$key" ]; then
        rm -f "$log"
        echo "ERROR: publish failed for a reason that is not a dangling package reference." >&2
        exit 1
    fi
    # A rebuild fixes every dangling entry at once, so a second one means
    # something deeper than a half-synced database.
    if [ "$attempt" -ge 3 ]; then
        rm -f "$log"
        echo "ERROR: still failing after $((attempt - 1)) rebuild(s) — this database needs a human." >&2
        exit 1
    fi

    dangling=$(printf '%s\n' "$key" | awk '{print $2 " " $3}')
    echo "::warning::The aptly database references $dangling but cannot load it. Rebuilding $SUITE from the package pool."

    # swallow-ok: the snapshot may not have been created yet; its absence
    # is the desired state either way.
    aptly snapshot drop "$SNAP" >/dev/null 2>&1 || true  # swallow-ok
    if ! "$ROOT/scripts/repair-aptly-db.sh" "$SUITE"; then
        rm -f "$log"
        echo "ERROR: could not rebuild $SUITE from the pool." >&2
        exit 1
    fi
done

echo "Published $SUITE at prefix '$PREFIX'."
