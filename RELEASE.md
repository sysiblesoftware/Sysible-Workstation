# Shipping updates over apt

Installed Sysible systems update via the Sysible apt repo (aptly -> S3, GPG
signed). Every user-facing thing is a versioned `.deb`:

| What changes | Package | Applied by |
|---|---|---|
| Wallpapers | `sysible-artwork` | file install |
| Default wallpaper / desktop / accent | `sysible-desktop-gnome` | gschema |
| GRUB theme, login bg, app icons, Sora font | `sysible-branding` | postinst (update-grub, login gresource, icon/font caches) |
| Terminal + Atlas | `systerm` (built from its repo in CI) | file install |
| Repo config, keys, third-party sources | `sysible-release` | file install |
| The install set | `sysible-meta` | dependencies |

## To ship a change
1. Make the change (e.g. re-run `branding/render-branding.py`, edit a package).
2. Bump the affected package(s): `scripts/bump-version.sh <package> "what changed"`.
   apt only upgrades on a HIGHER version — no bump, no update.
3. Publish:
   - Push to `main`  -> `publish.yml` publishes the **sysible-dev** suite (testing).
   - `git tag vX.Y && git push --tags` -> **sysible-stable** (what end users get).
4. On a machine: `sudo apt update && sudo apt full-upgrade`.

## One-time to turn the repo on (Cloudflare — no AWS needed)

The repo is published to **Cloudflare R2** (S3-compatible). Do this once.

**A. Signing key** (`SYSIBLE_GPG_PRIVATE_KEY`) — you generate it, it's not from a vendor:
```sh
export GNUPGHOME="$HOME/.sysible-signing"
scripts/gen-signing-key.sh                       # creates the key + refreshes the public keyring
gpg --armor --export-secret-keys maintainers@sysible.com   # <- paste THIS into the GitHub secret
git add packages/sysible-release/keyrings/sysible-archive-keyring.gpg && git commit  # public half, so clients trust it
```

**B. Cloudflare R2 bucket + token:**
1. Cloudflare dashboard → **R2** → *Create bucket* named `sysible-apt`.
2. R2 → *Manage R2 API Tokens* → *Create API token* (Object Read & Write on that bucket).
   It shows an **Access Key ID** and **Secret Access Key** → these are your `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (R2 speaks the S3 API).
3. Your **Account ID** is on the R2 overview page → this is `R2_ACCOUNT_ID`.
4. Bucket → *Settings* → **Public access / Custom Domain** → connect `repo.sysible.com`
   (Cloudflare adds the DNS + CDN automatically since the domain is on Cloudflare).

**C. Put the values into GitHub** (repo → Settings → Secrets and variables → Actions):
| Name | Kind | Value |
|---|---|---|
| `SYSIBLE_GPG_PRIVATE_KEY` | secret | the armored private key from step A |
| `AWS_ACCESS_KEY_ID` | secret | R2 token Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | secret | R2 token Secret Access Key |
| `R2_ACCOUNT_ID` | **variable** | your Cloudflare account id (not secret) |

**D. Go live:** in `packages/sysible-release/apt/sources.list.d/sysible.sources`
flip `Enabled: no -> yes`, run `scripts/bump-version.sh sysible-release "enable repo"`,
commit, then `git tag v0.2 && git push --tags`. `publish.yml` builds + signs +
uploads to R2; installed systems then `apt update && apt full-upgrade`.
(Keep it disabled until `repo.sysible.com` resolves — an enabled dead source
breaks `apt update`.)
