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
    cat > "$GNUPGHOME/keyparams" <<KP
%no-protection
Key-Type: EdDSA
Key-Curve: ed25519
Subkey-Type: ECDH
Subkey-Curve: cv25519
Name-Real: Sysible Archive Automatic Signing Key
Name-Email: maintainers@sysible.com
Expire-Date: 0
%commit
KP
    gpg --batch --gen-key "$GNUPGHOME/keyparams"
    rm -f "$GNUPGHOME/keyparams"
fi

gpg --export maintainers@sysible.com > "$ROOT/packages/sysible-release/keyrings/sysible-archive-keyring.gpg"
FPR=$(gpg --list-keys --with-colons maintainers@sysible.com | awk -F: '/^fpr:/{print $10; exit}')
echo
echo "Public keyring written: packages/sysible-release/keyrings/sysible-archive-keyring.gpg"
echo "Fingerprint: $FPR"
echo "Now:  export GNUPGHOME=$GNUPGHOME ; export SYSIBLE_GPG_KEY=maintainers@sysible.com"
echo "And commit the updated public keyring so apt clients trust this key."
