#!/bin/sh
# Move the aptly database between the runner and object storage, ATOMICALLY.
#
# It used to be `aws s3 sync` in both directions over the LevelDB directory,
# with no --delete either way. Two things follow from that, and the second one
# took down publishing:
#
#   1. Nothing is ever removed from the bucket. LevelDB deletes its old .ldb,
#      .log and MANIFEST files as it compacts, so every generation it has ever
#      written accumulates there. Measured in a local harness: 10 files after
#      one publish, 22 after four.
#
#   2. A directory sync is not atomic and has no consistent snapshot. Restoring
#      can therefore assemble a database whose CURRENT/MANIFEST reference keys
#      whose data files were never fetched, or were superseded. aptly then fails
#      with, verbatim from the 18:50 run:
#
#        ERROR: unable to switch: unable to load package with key
#          Pall sysible-app-connect 0.1.0+ci... : key not found
#
# A single object fixes both. S3 PUT is all-or-nothing, so a reader sees the
# whole previous database or the whole new one, never a mixture, and there is
# nothing to accumulate because each publish replaces one key.
#
# Usage:  aptly-state.sh restore|persist
#
# Environment:
#   APTLY_ROOT    the aptly rootDir to read/write      (default $HOME/.aptly)
#   STATE_URI     legacy directory prefix, still read once for migration
#   STATE_TAR     the object this script owns          (default $STATE_URI.tar.gz)
#   R2_ENDPOINT   S3 endpoint
set -eu

ACTION="${1:?usage: aptly-state.sh restore|persist}"
APTLY_ROOT="${APTLY_ROOT:-$HOME/.aptly}"
: "${STATE_URI:?STATE_URI is required}"
: "${R2_ENDPOINT:?R2_ENDPOINT is required}"
STATE_TAR="${STATE_TAR:-${STATE_URI%/}.tar.gz}"
S3="aws s3 --endpoint-url $R2_ENDPOINT"

case "$ACTION" in
restore)
    mkdir -p "$APTLY_ROOT"
    err=$(mktemp)
    if $S3 cp "$STATE_TAR" - 2>"$err" | tar -xzf - -C "$APTLY_ROOT"; then
        echo "restored aptly database from $STATE_TAR"
        rm -f "$err"; exit 0
    fi

    # Distinguish "there is no database yet" from "the fetch broke". Treating
    # the second as the first is how a publish would quietly rebuild an empty
    # archive and then persist it over the real one.
    if grep -qiE '404|NoSuchKey|Not Found|does not exist' "$err"; then
        echo "no $STATE_TAR yet — falling back to the legacy directory at $STATE_URI"
        rm -f "$err"
        if $S3 sync "$STATE_URI" "$APTLY_ROOT" >/dev/null 2>&1 && [ -d "$APTLY_ROOT/db" ]; then
            echo "migrated the legacy directory; this run will persist a tarball"
        else
            echo "no prior aptly state at all — treating this as a first publish"
        fi
        exit 0
    fi

    echo "ERROR: could not read the aptly database from $STATE_TAR" >&2
    sed 's/^/  /' "$err" >&2
    echo "Refusing to publish against an unknown database state." >&2
    rm -f "$err"; exit 1
    ;;

persist)
    [ -d "$APTLY_ROOT/db" ] || { echo "ERROR: $APTLY_ROOT/db missing; refusing to persist an empty database." >&2; exit 1; }
    # Keep the previous generation under a dated key before replacing it, so a
    # bad publish is recoverable rather than merely diagnosable.
    stamp=$(date -u +%Y%m%d%H%M%S)
    if $S3 ls "$STATE_TAR" >/dev/null 2>&1; then
        $S3 cp "$STATE_TAR" "${STATE_TAR%.tar.gz}-backup-$stamp.tar.gz" >/dev/null \
            && echo "previous database kept as ${STATE_TAR%.tar.gz}-backup-$stamp.tar.gz"
    fi
    tar -czf - -C "$APTLY_ROOT" . | $S3 cp - "$STATE_TAR"
    echo "persisted aptly database to $STATE_TAR"
    ;;
*)
    echo "usage: aptly-state.sh restore|persist" >&2; exit 2;;
esac
