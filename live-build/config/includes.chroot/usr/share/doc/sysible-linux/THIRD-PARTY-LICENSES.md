# Sysible Workstation — third-party licenses & written offer for source

Sysible Workstation is a Debian-based live/installable system: an aggregate of many
independent programs, each under its own license. This document (a) makes the
GPL/LGPL written offer for corresponding source code, (b) lists the non-Debian
components Sysible bundles and their licenses, and (c) records the software
Sysible deliberately does **not** ship and why.

_A copy of this file ships on every installed system at
`/usr/share/doc/sysible-linux/THIRD-PARTY-LICENSES.md`._

---

## 1. The base system (Debian)

The great majority of packages come unmodified from Debian's `main` component,
which follows the Debian Free Software Guidelines. Each installed package
carries its own license and copyright in
`/usr/share/doc/<package>/copyright` on the running system.

## 2. Written offer for corresponding source (GPL/LGPL/MPL §3)

For any GPL-, LGPL-, MPL-, or other copyleft-licensed binary distributed as part
of a Sysible Workstation ISO, we make the following offer, **valid for three (3) years
from the date you received the image**:

> You may obtain the complete corresponding source code for any copyleft
> component in this release. There are three ways, any of which we honor:
>
> 1. **Debian source** — for a package that came from Debian, the source is in
>    Debian's archive. The image ships Debian's `deb-src` source mirrors, so on
>    an installed system run `apt-get source <package>` for the exact version
>    installed, or fetch it from <https://snapshot.debian.org> pinned to that
>    version.
> 2. **Sysible source** — for Sysible's own packages and for the build
>    definition of the image itself, see
>    <https://github.com/sysiblesoftware/Sysible-Linux> and the other
>    repositories under <https://github.com/sysiblesoftware>.
> 3. **By request** — if you cannot retrieve a specific component's source by
>    (1) or (2), email **source@sysible.com** with the release tag (e.g.
>    `v1.0.1`), the architecture, and the package name. We will send the
>    corresponding source at no charge beyond the cost of physical distribution.

## 3. Bundled non-Debian components

These tools are pulled from upstream apt repositories (wired up by the
`sysible-release` package) or otherwise integrated, rather than taken from
Debian `main`. They are redistributable under the licenses below; each ships its
own full license text in its package or upstream repository.

| Component | License | Upstream |
|-----------|---------|----------|
| Docker Engine / CLI / containerd (`docker-ce`, `docker-compose-plugin`, `containerd.io`) | Apache-2.0 | https://github.com/moby/moby |
| Kubernetes CLI (`kubectl`) | Apache-2.0 | https://github.com/kubernetes/kubernetes |
| Helm (`helm`) | Apache-2.0 | https://github.com/helm/helm |
| OpenTofu (`opentofu`) | MPL-2.0 | https://github.com/opentofu/opentofu |
| k9s (`k9s`) | Apache-2.0 | https://github.com/derailed/k9s |
| SOPS (`sops`) | MPL-2.0 | https://github.com/getsops/sops |
| eza (`eza`) | MIT | https://github.com/eza-community/eza |
| PowerShell (`powershell`) | MIT | https://github.com/PowerShell/PowerShell |
| Ollama (`ollama`) | MIT | https://github.com/ollama/ollama |
| VSCodium (`codium`) | MIT | https://github.com/VSCodium/vscodium |
| CherryTree (`cherrytree`) | GPL-3.0 | https://github.com/giuspen/cherrytree |
| Azure CLI (`azure-cli`) | MIT | https://github.com/Azure/azure-cli |
| Google Cloud CLI (`google-cloud-cli`) | Apache-2.0 (Cloud SDK Terms of Service) | https://cloud.google.com/sdk |
| Firefox ESR (`firefox-esr`) | MPL-2.0 | https://www.mozilla.org/firefox/ |
| LibreOffice (`libreoffice-*`) | MPL-2.0 / LGPL-3.0+ | https://www.libreoffice.org |

VSCodium is the MIT-licensed (Code-OSS) build of VS Code — Microsoft's branded
`code` build is proprietary and is **not** shipped (see §6). OpenTofu is the
MPL-2.0 open fork that replaces HashiCorp Terraform (BUSL 1.1, not shipped).

## 4. Fonts

| Font | License | Source |
|------|---------|--------|
| Sora (UI / brand type) | SIL Open Font License 1.1 (OFL-1.1) | https://github.com/soratype/Sora |

## 5. Sysible's own code and artwork

| Component | Terms |
|-----------|-------|
| `sysible-*` packages (meta, release, cli, desktop, branding, artwork), the live-build definition, SysTerm, and the Sysible Controller CE installer | See each component's `debian/copyright` / repository `LICENSE` under https://github.com/sysiblesoftware |
| Sysible branding, logos, name, GRUB/Plymouth themes, wallpapers | Sysible trademarks & artwork. Redistributing the OS is permitted; the Sysible marks may not be reused to brand other products. |

## 6. Software deliberately NOT shipped (and why)

To keep the ISO cleanly redistributable, the following are **not** bundled. Open
equivalents ship in their place, and the installer's **Optional apps** page (or
a helper command) can pull the originals from the vendor on request — Sysible
never re-hosts these binaries, so the license grant is between you and the
vendor, initiated by you.

| Not shipped | Reason | Shipped instead | How to get the original |
|-------------|--------|-----------------|-------------------------|
| Visual Studio Code (Microsoft build) | Proprietary Microsoft license on the branded build | **VSCodium** (MIT) | Tick it on the installer's Optional apps page → installs `code` from packages.microsoft.com |
| Terraform | BUSL 1.1 (source-available, not FOSS) | **OpenTofu** (MPL-2.0) | Optional apps page → installs `terraform` from apt.releases.hashicorp.com |
| Packer | BUSL 1.1 | _none (no mainstream open fork)_ | Optional apps page → installs `packer` from apt.releases.hashicorp.com |
| Obsidian | Proprietary; no apt repo; amd64-only | **CherryTree** (GPL-3.0, incl. arm64) | Run `sysible-install-obsidian` (fetches the official vendor `.deb`) |

---

_Questions about licensing or source: **source@sysible.com**._
