# Sysible Linux — third-party licenses & source offer

Sysible Linux is a Debian-based live/installable system. It is an aggregate of
independent programs, each under its own license. This document explains how
those licenses are satisfied and how to obtain corresponding source code.

_A copy of this file also ships on every installed system at
`/usr/share/doc/sysible-linux/THIRD-PARTY-LICENSES.md`._

## The base system (Debian)

The overwhelming majority of packages come unmodified from Debian. Each package
carries its own license in `/usr/share/doc/<package>/copyright` on the running
system. Debian's Free Software Guidelines (DFSG) govern what is in `main`.

## Written offer for source code (GPL/LGPL §3)

For any GPL-, LGPL-, or other copyleft-licensed binary distributed as part of a
Sysible Linux ISO, we make the following offer, valid for three years from the
date you received the image:

> You may obtain the complete corresponding source code for any copyleft
> component in this release. For Debian-origin packages, the source is available
> from Debian's archive — for a package installed on your system, run
> `apt-get source <package>` (the ISO configures Debian's source mirrors), or
> fetch it from <https://snapshot.debian.org> pinned to the version in the
> image. For Sysible's own components, see the repositories under
> <https://github.com/sysiblesoftware>. If you cannot retrieve a specific
> component's source this way, email **source@sysible.com** with the release tag
> (e.g. `v1.0.2`), architecture, and package name, and we will provide the
> corresponding source at no charge beyond the cost of physical distribution.

## What Sysible added, and under what terms

| Component | Origin | License | Notes |
|-----------|--------|---------|-------|
| Sysible branding, artwork, GRUB/Plymouth themes, wallpapers | Sysible | Proprietary (Sysible trademarks/artwork) — redistribution of the OS is permitted; the marks may not be reused to brand other products | Logos and the "Sysible" name are trademarks |
| `sysible-*` packages (meta, release, cli, desktop, branding, artwork) | Sysible | See each package's `debian/copyright` | Packaging and glue scripts |
| Sysible Controller CE installer | Sysible | See the Controller repository | Bundled installer, not auto-started |
| SysTerm terminal | Sysible | See the SysTerm repository | |

## Software deliberately NOT shipped (and why)

To keep the ISO cleanly redistributable, the following are **not** bundled. Open
equivalents are installed in their place, and the installer's **Optional apps**
page (or a helper command) can pull the originals from the vendor on request —
Sysible never re-hosts these binaries.

| Not shipped | Reason | Shipped instead | How to get the original |
|-------------|--------|-----------------|-------------------------|
| Visual Studio Code (Microsoft build) | Proprietary Microsoft license on the branded build | **VSCodium** (MIT, Code-OSS) | Tick it on the installer's Optional apps page → installs `code` from packages.microsoft.com |
| Terraform | BUSL 1.1 (source-available, not FOSS) | **OpenTofu** (MPL-2.0, the open fork) | Optional apps page → installs `terraform` from apt.releases.hashicorp.com |
| Packer | BUSL 1.1 | _none — no mainstream open fork_ | Optional apps page → installs `packer` from apt.releases.hashicorp.com |
| Obsidian | Proprietary; no apt repository; amd64-only | **CherryTree** (GPLv3, incl. arm64) | Run `sysible-install-obsidian` (fetches the official .deb from the vendor) |

Nothing on the Optional apps page or in the helper re-distributes a vendor
binary: each item installs from the vendor's own repository or release, so the
license grant is between you and that vendor, initiated by you.
