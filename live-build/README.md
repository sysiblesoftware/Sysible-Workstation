# Sysible Workstation — ISO (live-build)

Builds a bootable GNOME workstation ISO with `sysible-workstation` preinstalled
and a Calamares graphical installer.

## Build

On a Debian host (matching the target release), with the Sysible packages
available (published to the Sysible repo, or dropped into `config/packages.chroot/`):

```
sudo apt install live-build
./build.sh
```

`build.sh` wires the Sysible + upstream vendor repos (and their keys) into the
build chroot, then runs live-build. Output: `live-image-amd64.hybrid.iso`.

## What it produces

- GNOME on Adwaita-dark, Mesh (Dark) wallpaper, blue accent, SysTerm as the
  default terminal (from `sysible-desktop-gnome`).
- The full engineering toolkit from `sysible-workstation`.
- os-release branded `ID=sysible` / `ID_LIKE=debian`.
- Calamares installer for install-to-disk.

## Notes

- Until the Sysible repo is live, drop the locally-built `sysible-*.deb` into
  `config/packages.chroot/` and live-build will include them.
- When rebasing to a newer Debian release, bump `CODENAME` in `build.sh` and the
  distribution in `auto/config`, plus the Kubernetes minor version.
- The ISO cannot be boot-tested from `dpkg`/CI without KVM; use Sysible Controller
  + provision-lab-vms to boot it in a VM and run `sysible verify` as the gate.
