# Sysible packaging + repo scripts

Run these on a Debian/Ubuntu build host (root or a sudo user). `build-all.sh`
installs its own build dependencies; you do not need to install them by hand.

## 1. One-time: signing key

Create the archive signing key **on this host** and refresh the public keyring
that `sysible-release` ships (never commit the private key):

```
./gen-signing-key.sh
export GNUPGHOME="$HOME/.sysible-signing"      # where the key now lives
export SYSIBLE_GPG_KEY=maintainers@sysible.com
git add ../packages/sysible-release/keyrings/sysible-archive-keyring.gpg
git commit -m "sysible-release: archive signing public key"
```

`gen-signing-key.sh` prints the fingerprint — that is the key apt clients trust.

## 2. Build every package

```
./build-all.sh          # installs build-deps, then -> ../dist/*.deb
```

## 3. Publish to the apt repo (aptly)

```
sudo apt install aptly awscli
cp aptly.conf.sample ~/.aptly.conf     # edit bucket/endpoint for your setup

# local filesystem (nginx serves repo.sysible.com/apt):
./publish-repo.sh sysible-dev

# or S3 + CloudFront (endpoint "sysible" in aptly.conf):
SYSIBLE_APTLY_ENDPOINT=s3:sysible: ./publish-repo.sh sysible-stable
```

- `sysible-dev` republishes in place on every push (CI target).
- `sysible-stable` cuts an immutable snapshot and switches the suite to it;
  rollback is `aptly publish switch` to an older snapshot.

The suites match `sysible-release`'s `sysible.sources` (`Suites: sysible-stable`).

## Common first-run errors

- `unmet build dependencies` — you ran `dpkg-buildpackage` directly; use
  `./build-all.sh`, which installs them.
- `GNUPGHOME ... does not exist` — you pointed `GNUPGHOME` at a placeholder.
  Run `gen-signing-key.sh` and export `GNUPGHOME="$HOME/.sysible-signing"`.
- `curl (60) SSL certificate problem` on a minimal Debian — `apt install
  ca-certificates` (the ISO `build.sh` now does this automatically).

## CI

`.github/workflows/ci.yml` builds + validates every package on push/PR.
`.github/workflows/publish.yml` publishes `sysible-dev` on `main` and
`sysible-stable` on `v*` tags — needs repo secrets `SYSIBLE_GPG_PRIVATE_KEY`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
