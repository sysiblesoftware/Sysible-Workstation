# Sysible Calamares partition icons

Sysible-styled replacements for Calamares' partition-choice and status icons.

**These are staged, not yet wired in.** Calamares loads these glyphs from
compiled-in Qt resources (`ImageRegistry` → `QIcon`/`QSvgRenderer` on `:/data/…`
paths), with **no** filesystem or branding override. So unlike the product logo,
welcome image, and slideshow (all already branded), swapping these requires
**rebuilding Calamares from patched source** and shipping that `.deb` in the ISO.

Filenames match the resource names Calamares expects, so wiring is a
drop-in replacement of the source resources before `dpkg-buildpackage`:

| File | Calamares resource | Choice button |
|------|--------------------|---------------|
| `partition-disk.svg`       | `:/data/images/partition-disk.svg`       | disk glyph |
| `partition-erase-auto.svg` | `:/data/images/partition-erase-auto.svg` | **Erase disk** |
| `partition-alongside.svg`  | `:/data/images/partition-alongside.svg`  | Install alongside |
| `partition-replace-os.svg` | `:/data/images/partition-replace-os.svg` | Replace a partition |
| `partition-manual.svg`     | `:/data/images/partition-manual.svg`     | **Manual partitioning** |
| `state-ok.svg`             | `:/data/images/state-ok.svg`             | status OK |
| `state-warning.svg`        | `:/data/images/state-warning.svg`        | status warning |
| `state-error.svg`          | `:/data/images/state-error.svg`          | status error |

## To wire in (if the Calamares rebuild is approved)

In the ISO build, before building Calamares:
1. `apt-get source calamares` (matches the Debian version the ISO installs).
2. Copy these SVGs over the matching files in the Calamares source resource
   dir (the `.qrc` that registers `data/images/…`).
3. `dpkg-buildpackage -us -uc -b` and drop the resulting `calamares_*.deb` into
   `live-build/config/packages.chroot/`.

Risk: this adds a heavy (~15–20 min) source build to CI and, if it breaks,
breaks the installer — so it's deliberately left as an opt-in step.
