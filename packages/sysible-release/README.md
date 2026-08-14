# sysible-release

Bootstraps apt for Sysible Workstation:

- `usr/share/keyrings/sysible-archive-keyring.gpg` — the Sysible repo signing key
  (fingerprint CFA4 B4E9 5EF5 44E0 6CEE D401 FBF0 856C D302 1431).
- `etc/apt/sources.list.d/sysible.sources` — the Sysible repo (only `sysible-*`).
- `etc/apt/sources.list.d/*.sources` — upstream vendor repos for the tools that
  are not in Debian or that we want newer than Debian (Docker CE, Kubernetes,
  Helm, HashiCorp, OpenTofu, VS Code, Google Cloud CLI).

The vendor **keyrings** are fetched by `usr/share/sysible/scripts/fetch-third-party-keyrings.sh`
during the ISO build (dpkg builds have no network). Until they're present, apt
simply skips those repos with a warning; the Sysible repo works regardless.

When rebasing onto a new Debian release, update the codename in the vendor
`.sources` (e.g. `bookworm` → `trixie`) and the Kubernetes minor version.
