#!/bin/sh
# Create the Sysible archive signing key on THIS build/publish host and refresh
# the public keyring that sysible-release ships. Run once. Keep the private key
# here (never commit it); commit only the regenerated public keyring.
#
#   ./scripts/gen-signing-key.sh
#   export GNUPGHOME="$HOME/.sysible-signing"
#   export SYSIBLE_GPG_KEY=maintainers@sysible.com
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
: "${GNUPGHOME:=$HOME/.sysible-signing}"
export GNUPGHOME
mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"

if gpg --list-secret-keys maintainers@sysible.com >/dev/null 2>&1; then
    echo "signing key already present in $GNUPGHOME"
else
    # SECURITY: give the key a finite lifetime (2 years) so a lost/compromised
    # key auto-expires, and rotate before it lapses (re-run this and ship the new
    # public keyring). `%no-protection` is only acceptable for an UNATTENDED CI
    # signer whose secret lives solely as a CI secret; for the STABLE/RELEASE key
    # prefer a passphrase-protected key on a hardware token (offline), separate
    # from this dev/publish key. Override the lifetime with SYSIBLE_KEY_EXPIRE.
    : "${SYSIBLE_KEY_EXPIRE:=2y}"
    cat > "$GNUPGHOME/keyparams" <<KP
%no-protection
Key-Type: EdDSA
Key-Curve: ed25519
Subkey-Type: ECDH
Subkey-Curve: cv25519
Name-Real: Sysible Archive Automatic Signing Key
Name-Email: maintainers@sysible.com
Expire-Date: $SYSIBLE_KEY_EXPIRE
%commit
KP
    gpg --batch --gen-key "$GNUPGHOME/keyparams"
    rm -f "$GNUPGHOME/keyparams"
fi

KEYRING="$ROOT/packages/sysible-release/keyrings/sysible-archive-keyring.gpg"
gpg --export maintainers@sysible.com > "$KEYRING"
FPR=$(gpg --list-keys --with-colons maintainers@sysible.com | awk -F: '/^fpr:/{print $10; exit}')

# The apt repo (repo.sysible.com) serves packages from BOTH the Workstation and the
# Server, all signed by this ONE key — so the SAME public keyring must ship in every
# repo's sysible-release, or apt clients from one ISO won't trust the other's builds.
# Copy it into any sibling checkout found next to this one so a rotation updates them
# all in one run.
this_dir=$(cd "$(dirname "$KEYRING")" && pwd)
for name in Sysible-Server sysible-server Sysible-Workstation sysible-workstation; do
    dst="$ROOT/../$name/packages/sysible-release/keyrings/sysible-archive-keyring.gpg"
    [ -d "$(dirname "$dst")" ] || continue
    [ "$(cd "$(dirname "$dst")" && pwd)" = "$this_dir" ] && continue
    cp -f "$KEYRING" "$dst" && echo "Also updated sibling keyring: $dst"
done

cat <<EOF

======================================================================
 New signing key created. Fingerprint: $FPR
 Public keyring written to this repo (and any sibling above).
======================================================================

Finish the rotation FROM THIS MACHINE (it now holds the new private key):

  1) Commit the public keyring in EVERY repo it was written to:
       git -C "$ROOT" add packages/sysible-release/keyrings/sysible-archive-keyring.gpg
       git -C "$ROOT" commit -m "release: rotate the archive signing key"
       git -C "$ROOT" push
     (repeat 'git -C <sibling-repo> ...' for each sibling listed above)

  2) Set the NEW private key as the publish secret in BOTH repos
     (piped, so it never lands in your shell history or a chat log):
       gpg --armor --export-secret-keys maintainers@sysible.com \\
         | gh secret set SYSIBLE_GPG_PRIVATE_KEY --repo sysiblesoftware/Sysible-Workstation
       gpg --armor --export-secret-keys maintainers@sysible.com \\
         | gh secret set SYSIBLE_GPG_PRIVATE_KEY --repo sysiblesoftware/Sysible-Server

  3) Rebuild the ISOs (new installs trust the new key) and re-run Publish (stable).
     Existing test VMs: reinstall from the new ISO, or import the new keyring by hand.

  Env for this shell:  export GNUPGHOME=$GNUPGHOME ; export SYSIBLE_GPG_KEY=maintainers@sysible.com
EOF
