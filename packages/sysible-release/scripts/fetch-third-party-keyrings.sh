#!/bin/sh
# Populate /usr/share/keyrings with the upstream vendor signing keys that the
# .sources files in this package reference. Run at ISO build time (live-build
# hook) or once on a fresh install — dpkg builds have no network, so the keys
# are fetched here rather than vendored. Each key is stored (dearmored where
# armored) at the exact path named by Signed-By in its .sources file.
#
# SUPPLY-CHAIN INTEGRITY: every fetched keyring is checked against a pinned set
# of OpenPGP fingerprints. If a download contains any key that is NOT pinned
# (tampering, a hijacked mirror, or a CA-intercepting proxy swapping the key),
# we FAIL CLOSED and install nothing. Keys whose fingerprints could not be
# verified upstream at authoring time carry an empty pin: their fingerprint is
# logged loudly for pinning, but not yet enforced (fetch still relies on TLS).
set -e
KR=/usr/share/keyrings
command -v update-ca-certificates >/dev/null 2>&1 && update-ca-certificates >/dev/null 2>&1 || true
mkdir -p "$KR"

# Pinned, upstream-verified fingerprints (space-separated; a keyring may legitimately
# hold more than one — e.g. a current + rotation key). Fill the empty ones from a
# build log's "observed" line once confirmed on a trusted network.
pins_for() {
    case "$1" in
        docker.gpg)      echo "9DC858229FC7DD38854AE2D88D81803C0EBFCD88 D3306A018370199E527AE7997EA0A9C3F273FCD8" ;;
        hashicorp.gpg)   echo "798AEC654E5C15428C8E42EEAA16FCBCA621E701 EB0AF5E2994969596F99873E706E668369C085E9" ;;
        microsoft.gpg)   echo "BC528686B50D79E339D3721CEB3E94ADBE1229CF" ;;
        github-cli.gpg)  echo "5700BAB26C8DE75F3EE323FEE5FAF19590714157" ;;   # GitHub rotated the gh apt key (old: 2C6106201985B60E6C7AC87323F3D4EA75716059)
        *)               echo "" ;;   # kubernetes.gpg, google-cloud.gpg — logged, not yet enforced
    esac
}

fetch() {  # fetch <url> <dest.gpg>
    url="$1"; dest="$2"
    printf 'sysible-release: fetching %s\n' "$dest"
    tmp=$(mktemp); out="$tmp.gpg"
    curl -fsSL --connect-timeout 20 --max-time 120 --retry 3 --retry-delay 3 "$url" -o "$tmp"
    # Store as a binary keyring: dearmor ASCII-armored keys; pass binary through.
    if head -c 40 "$tmp" | grep -q 'BEGIN PGP'; then
        gpg --dearmor < "$tmp" > "$out"
    else
        cp "$tmp" "$out"
    fi
    got=$(gpg --show-keys --with-colons "$out" 2>/dev/null | awk -F: '/^fpr:/{print $10}')
    if [ -z "$got" ]; then
        echo "FATAL: no OpenPGP key found in $url" >&2; rm -f "$tmp" "$out"; exit 1
    fi
    pins=$(pins_for "$dest")
    if [ -n "$pins" ]; then
        for f in $got; do
            case " $pins " in
                *" $f "*) ;;
                *) echo "FATAL: $dest contains unpinned key $f (expected: $pins) — refusing to trust it" >&2
                   rm -f "$tmp" "$out"; exit 1 ;;
            esac
        done
        printf '  verified pinned fingerprint(s): %s\n' "$(echo $got | tr '\n' ' ')"
    else
        printf '  WARNING: %s is not fingerprint-pinned yet. Observed: %s\n' "$dest" "$(echo $got | tr '\n' ' ')"
    fi
    install -m0644 "$out" "$KR/$dest"
    rm -f "$tmp" "$out"
}

fetch https://download.docker.com/linux/debian/gpg                      docker.gpg
fetch https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key           kubernetes.gpg
fetch https://apt.releases.hashicorp.com/gpg                            hashicorp.gpg
fetch https://packages.microsoft.com/keys/microsoft.asc                 microsoft.gpg
fetch https://cli.github.com/packages/githubcli-archive-keyring.gpg      github-cli.gpg
fetch https://packages.cloud.google.com/apt/doc/apt-key.gpg             google-cloud.gpg

echo "sysible-release: vendor keyrings installed in $KR"
