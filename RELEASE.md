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

## One-time to turn the repo on (infra)
- Set CI secrets `SYSIBLE_GPG_PRIVATE_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
- Point `https://repo.sysible.io/apt` at the S3 bucket `s3://sysible-apt` (CDN/DNS).
- In `packages/sysible-release/apt/sources.list.d/sysible.sources` flip
  `Enabled: no` -> `yes` (and bump `sysible-release`), then cut a `vX.Y` tag.
  Until the host resolves, keep it disabled — an enabled dead source breaks
  `apt update`.
