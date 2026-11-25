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

ACTION="${1:?usage: aptly-state.sh lock|unlock|restore|persist}"
APTLY_ROOT="${APTLY_ROOT:-$HOME/.aptly}"
: "${STATE_URI:?STATE_URI is required}"
: "${R2_ENDPOINT:?R2_ENDPOINT is required}"
STATE_TAR="${STATE_TAR:-${STATE_URI%/}.tar.gz}"
S3="aws s3 --endpoint-url $R2_ENDPOINT"

LOCK="${LOCK_URI:-${STATE_URI%/}.lock}"
LOCK_TTL="${LOCK_TTL:-1800}"          # a crashed run must not block forever
HOLDER="${GITHUB_REPOSITORY:-local}/${GITHUB_RUN_ID:-$$}/${GITHUB_RUN_ATTEMPT:-0}"

case "$ACTION" in
lock)
    # Sysible Server and Sysible Workstation publish into ONE database, and a
    # GitHub concurrency group is per-REPOSITORY, so nothing serialises them.
    # Two pushes two seconds apart produced two concurrent publishes on
    # 25 November; whichever persisted last would have dropped the other's
    # packages, database record and pool file together.
    #
    # This is an advisory lock, not a mutex: S3 has no compare-and-swap that
    # the AWS CLI exposes, so it writes, waits, and reads back to see whose
    # write survived. That narrows the window to the read-back interval rather
    # than closing it. Good enough to stop two scheduled publishes colliding;
    # not a substitute for giving each product its own archive, which is the
    # real fix if this keeps happening.
    i=0
    while [ "$i" -lt 60 ]; do
        i=$((i + 1))
        held=$($S3 cp "$LOCK" - 2>/dev/null || true)
        if [ -n "$held" ]; then
            when=$(printf '%s' "$held" | awk '{print $2}')
            now=$(date -u +%s)
            if [ -n "$when" ] && [ "$((now - when))" -lt "$LOCK_TTL" ]; then
                owner=$(printf '%s' "$held" | awk '{print $1}')
                [ "$owner" = "$HOLDER" ] && { echo "lock: already held by this run"; exit 0; }
                echo "lock: held by $owner, waiting ($i/60)"
                sleep 10
                continue
            fi
            echo "lock: found a stale lock older than ${LOCK_TTL}s — taking it"
        fi
        printf '%s %s\n' "$HOLDER" "$(date -u +%s)" | $S3 cp - "$LOCK" >/dev/null
        sleep 3
        back=$($S3 cp "$LOCK" - 2>/dev/null || true)
        if [ "$(printf '%s' "$back" | awk '{print $1}')" = "$HOLDER" ]; then
            echo "lock: acquired by $HOLDER"
            exit 0
        fi
        echo "lock: lost the race, retrying"
        sleep 7
    done
    echo "ERROR: could not acquire the publish lock at $LOCK after 10 minutes." >&2
    echo "If a previous run died holding it, delete that object and retry." >&2
    exit 1
    ;;

unlock)
    held=$($S3 cp "$LOCK" - 2>/dev/null || true)
    owner=$(printf '%s' "$held" | awk '{print $1}')
    if [ -z "$held" ]; then
        echo "unlock: no lock present"
    elif [ "$owner" = "$HOLDER" ]; then
        $S3 rm "$LOCK" >/dev/null && echo "unlock: released by $HOLDER"
    else
        # Never delete someone else's lock: that is how two runs end up both
        # believing they hold it.
        echo "unlock: lock belongs to $owner, leaving it alone"
    fi
    ;;

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
    echo "usage: aptly-state.sh lock|unlock|restore|persist" >&2; exit 2;;
esac
