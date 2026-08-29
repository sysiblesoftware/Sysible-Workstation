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
# we FAIL CLOSED and install nothing. A keyring with no pin at all is likewise
# refused (fatal) — there is no warn-and-install path, so no vendor key can ever
# ship without fingerprint verification.
set -e
KR=/usr/share/keyrings
command -v update-ca-certificates >/dev/null 2>&1 && update-ca-certificates >/dev/null 2>&1 || true
mkdir -p "$KR"

# Pinned, upstream-verified fingerprints (space-separated; a keyring may legitimately
# hold more than one — e.g. a current + rotation key). A keyring with no pin here
# fails the build (fatal, see the empty-pin branch below), so add each fingerprint
# from a build log's "observed" line, confirmed on a trusted network, before wiring
# up its fetch.
pins_for() {
    case "$1" in
        docker.gpg)       echo "9DC858229FC7DD38854AE2D88D81803C0EBFCD88 D3306A018370199E527AE7997EA0A9C3F273FCD8" ;;
        hashicorp.gpg)    echo "798AEC654E5C15428C8E42EEAA16FCBCA621E701 EB0AF5E2994969596F99873E706E668369C085E9" ;;
        microsoft.gpg)    echo "BC528686B50D79E339D3721CEB3E94ADBE1229CF" ;;
        github-cli.gpg)   echo "2C6106201985B60E6C7AC87323F3D4EA75716059 7F38BBB59D064DBCB3D84D725612B36462313325" ;;   # gh is mid-rotation: cli.github.com's CDN serves two keyring variants (old primary 2C61..., new primary 7F38...). Accept either; both come from GitHub's TLS endpoint.
        kubernetes.gpg)   echo "DE15B14486CD377B9E876E1A234654DA9A296436" ;;   # pkgs.k8s.io v1.31 signing key (observed on a trusted network)
        google-cloud.gpg) echo "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796" ;;   # packages.cloud.google.com primary (Google's published Linux package signing key)
        *)                echo "" ;;   # no pin -> refused as fatal below (fail-closed)
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
    # Extract only PRIMARY key fingerprints — the fpr line immediately following
    # each pub record. In gpg --with-colons output every key emits an fpr line
    # for its primary AND one for each subkey; pinning subkey fingerprints would
    # make the build break every time an upstream rotates a subkey under a stable
    # primary. We pin the primary and let its self-signed subkeys ride along
    # (a forged subkey needs the primary's secret key, so this stays fail-closed
    # against a rogue primary while tolerating legitimate subkey rotation).
    got=$(gpg --show-keys --with-colons "$out" 2>/dev/null | awk -F: '/^pub:/{p=1;next} /^fpr:/&&p{print $10;p=0}')
    if [ -z "$got" ]; then
        echo "FATAL: no OpenPGP primary key found in $url" >&2; rm -f "$tmp" "$out"; exit 1
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
        echo "FATAL: $dest is not fingerprint-pinned (observed: $(echo $got | tr '\n' ' ')) — refusing to install" >&2
        rm -f "$tmp" "$out"; exit 1
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
