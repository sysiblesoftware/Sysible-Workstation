<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/sysible-logo-dark.png">
    <img alt="Sysible" src=".github/sysible-logo-light.png" width="340">
  </picture>
</p>

# Sysible Linux

A Debian-stable–based **engineering workstation**. Install it and start working —
the Linux/DevOps/SRE/platform toolkit is there on first boot, no half-hour of `apt`
after every fresh install.

We inherit kernel, systemd, OpenSSH, Python, and package maintenance from Debian,
and maintain only Sysible-specific packages plus an opinionated toolkit.

## Layout

```
packages/
  sysible-meta/     # sysible-workstation — the metapackage that *is* the distro
  sysible-cli/      # the `sysible` command (ships `sysible verify`)
branding/           # finalized wallpapers + theme assets → sysible-artwork
live-build/         # the ISO config (GNOME + sysible-workstation + Calamares)
scripts/            # apt-repo publish + build helpers
roadmap.md          # the build plan
```

## Try the CLI now (no install)

```
cd packages/sysible-cli
python3 -m sysible_cli verify            # readiness report
python3 -m sysible_cli verify --json     # machine-readable
python3 -m sysible_cli verify --security # one area only
```

## Build a package

```
cd packages/sysible-meta   # or sysible-cli
dpkg-buildpackage -us -uc -b
```

See `roadmap.md` for the phased plan and the known package traps we design around.
