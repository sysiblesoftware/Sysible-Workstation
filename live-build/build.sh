#!/bin/sh
# Build the Sysible Linux ISO. Run on a Debian host, or in a debian:bookworm
# container, with network access:  sudo ./build.sh
#
# Everything is baked in — nothing to install after first boot:
#   * Debian-native tools come from the package list (below).
#   * The Sysible packages are built here and included directly.
#   * The non-Debian vendor tools (Docker, Kubernetes, Terraform, cloud CLIs,
#     VS Code, k9s/sops/eza) are installed by a chroot hook that controls apt
#     directly — reliable, unlike live-build's archive-key handling.
set -e
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)
if [ "$(id -u)" = 0 ]; then SUDO=; else SUDO="sudo"; fi
CODENAME="${SYSIBLE_CODENAME:-bookworm}"; export SYSIBLE_CODENAME="$CODENAME"
ARCH="${SYSIBLE_ARCH:-amd64}"; export SYSIBLE_ARCH="$ARCH"
echo "Building for architecture: $ARCH"

# --- host tooling + trust store -------------------------------------------
$SUDO apt-get update -qq || true
$SUDO apt-get install -y --no-install-recommends \
    live-build ca-certificates curl gnupg sudo openssl xorriso || true
$SUDO update-ca-certificates || true
if ls config/extra-ca/*.crt >/dev/null 2>&1; then
    $SUDO cp config/extra-ca/*.crt /usr/local/share/ca-certificates/ || true
    $SUDO update-ca-certificates || true
    # Also trust it INSIDE the chroot so the vendor hook's HTTPS verifies on an
    # inspected network (includes.chroot is copied in before hooks run).
    mkdir -p config/includes.chroot/usr/local/share/ca-certificates
    cp config/extra-ca/*.crt config/includes.chroot/usr/local/share/ca-certificates/ || true
fi

# --- build the Sysible packages and include them directly ------------------
if ! ls "$ROOT"/dist/*.deb >/dev/null 2>&1; then
    echo "== building Sysible packages =="
    "$ROOT/scripts/build-all.sh"
fi
mkdir -p config/packages.chroot
cp "$ROOT"/dist/*.deb config/packages.chroot/ 2>/dev/null || true
echo "Included $(ls config/packages.chroot/*.deb 2>/dev/null | wc -l) Sysible package(s) directly."

# --- build SysTerm fresh from its own public repo and include the .deb ------
# SysTerm ships full debian/ packaging; build it here (needs a real Debian
# toolchain, which CI provides) so the terminal is installed on the ISO.
# ALWAYS rebuild from the `dev` branch (pinned explicitly, not relying on the
# remote default) and drop any stale copy first, so the ISO can never ship an
# old terminal. Fail the build outright if the result is pre-0.1.9 (which would
# be missing the -e/Open-in-terminal fix and the Run Command menu).
echo "== building SysTerm (dev) =="
rm -f config/packages.chroot/systerm_*.deb
$SUDO apt-get install -y --no-install-recommends \
    git build-essential debhelper dh-python pybuild-plugin-pyproject \
    python3-all python3-setuptools dpkg-dev || true
rm -rf /tmp/systerm-src
git clone --depth 1 --branch dev https://github.com/sysiblesoftware/SysTerm /tmp/systerm-src
( cd /tmp/systerm-src && dpkg-buildpackage -us -uc -b )
cp /tmp/systerm_*.deb config/packages.chroot/
STVER=$(dpkg-deb -f config/packages.chroot/systerm_*.deb Version 2>/dev/null || echo '?')
echo "Included SysTerm: $(ls config/packages.chroot/systerm_*.deb) (version $STVER)"
case "$STVER" in
    0.1.[0-8]|0.0.*|'?')
        echo "ERROR: built a stale SysTerm ($STVER); expected >= 0.1.9. Aborting." >&2
        exit 1 ;;
esac

# --- expand the metapackage into the Debian-native toolkit -----------------
# Every package in sysible-workstation's Depends/Recommends/Suggests EXCEPT the
# sysible-* ones (included directly), systerm (its own repo), and the vendor /
# GitHub-binary tools (installed by the hook, since they aren't in Debian). One
# source of truth: the metapackage control.
awk '
    BEGIN {
        split("docker-ce docker-compose-plugin containerd.io kubectl helm k9s terraform opentofu packer azure-cli google-cloud-cli code sops eza", v, " ")
        for (i in v) VEND[v[i]] = 1
    }
    /^Description:/ { f=0 }
    /^(Depends|Recommends|Suggests):/ { f=1 }
    f {
        line=$0; sub(/^(Depends|Recommends|Suggests):/,"",line)
        if (line ~ /^[[:space:]]*#/) next
        n=split(line, a, ",")
        for (i=1;i<=n;i++) {
            gsub(/^[[:space:]]+|[[:space:]]+$/,"",a[i])
            split(a[i], b, /[[:space:]]/); name=b[1]
            if (name ~ /^[a-z0-9][a-z0-9.+-]+$/ && name !~ /^sysible-/ && name != "systerm" && !(name in VEND))
                print name
        }
    }
' "$ROOT/packages/sysible-meta/debian/control" | sort -u \
    > config/package-lists/sysible-toolkit.list.chroot
echo "Debian toolkit: $(grep -c . config/package-lists/sysible-toolkit.list.chroot) packages (vendor tools via hook)."

# --- make the TARGET bootloader installable (fixes "Installation Failed") ---
# Calamares installs GRUB into the freshly-partitioned target with apt. On an
# offline install it can only pull .debs from the ISO's own pool, and that pool
# contains ONLY packages that are installed in the live chroot. live-build's
# `--bootloaders grub-efi` sets up the ISO's *own* EFI boot but does NOT install
# the grub-efi-<arch> package in the filesystem — so neither the unpacked target
# nor the pool has it. The result is exactly the failure users hit:
#   E: Package 'grub-efi-amd64' has no installation candidate
#   chroot: failed to run command '/usr/sbin/update-grub': No such file or dir
# Install the correct grub flavour into the live system so it is (a) already
# present in the target after unpackfs and (b) available in the offline pool for
# Calamares' apt step. Arch-selected here (the list is shared across arches, and
# grub-efi-amd64 has no arm64 candidate / vice-versa, which would abort the build).
if [ "$ARCH" = "arm64" ]; then
    printf '%s\n' grub-efi-arm64 grub-efi-arm64-bin grub-common \
        > config/package-lists/sysible-grub.list.chroot
else
    # amd64: grub-efi-amd64 covers UEFI targets (the common case, incl. VMs and
    # Apple-silicon guests). grub-pc-bin coexists with grub-efi (only the grub-pc
    # metapackage conflicts) so BIOS grub-install has its modules in the pool too.
    printf '%s\n' grub-efi-amd64 grub-efi-amd64-bin grub-pc-bin grub-common \
        > config/package-lists/sysible-grub.list.chroot
fi
echo "Target bootloader packages: $(tr '\n' ' ' < config/package-lists/sysible-grub.list.chroot)"

# --- assemble -------------------------------------------------------------
# Boot branding is done with source-level bootloader overrides that live-build
# consumes while building the ISO: config/bootloaders/isolinux/ (BIOS menu title
# + Sysible splash) and config/binary_grub/ (UEFI background). These are checked
# in, not generated, so they don't depend on where a given live-build keeps its
# templates.
lb clean --purge || true
lb config
$SUDO lb build

# --- brand GRUB (UEFI, incl. arm64) in the finished ISO --------------------
# Unlike isolinux, GRUB's grub.cfg is generated during binary_iso and is not
# override-able via config here, so edit it in the finished ISO with xorriso,
# which rewrites data files while KEEPING the El Torito + isohybrid/GPT boot
# structures (-boot_image any keep). Rebrand the entry titles and add a Sysible
# background. The release checksums are computed after this, so they match.
echo "GRUB-DEBUG: pwd=$(pwd)"
echo "GRUB-DEBUG: isos here: $(ls -1 ./*.iso 2>/dev/null | tr '\n' ' ')"
echo "GRUB-DEBUG: xorriso=$(command -v xorriso 2>/dev/null || echo NONE)"
ISO=$(find . -maxdepth 1 -name '*.hybrid.iso' 2>/dev/null | head -1)
echo "GRUB-DEBUG: selected ISO=[$ISO]"
if [ -n "$ISO" ]; then
    echo "===== branding GRUB + isolinux, adding installer entry in $ISO ====="
    WORK=$(mktemp -d)
    $SUDO xorriso -osirrox on -indev "$ISO" -extract /boot/grub/grub.cfg "$WORK/grub.cfg" 2>/dev/null || true
    $SUDO xorriso -osirrox on -indev "$ISO" -extract /isolinux/live.cfg "$WORK/live.cfg" 2>/dev/null || true
    if [ -s "$WORK/grub.cfg" ]; then
        echo "-- grub.cfg BEFORE --"; grep -iE 'menuentry|background_image|Live system|Debian' "$WORK/grub.cfg" | head
        cp config/branding/splash.png "$WORK/sysible-splash.png"
        # GRUB: rebrand titles, add a Sysible background, and clone the live entry
        # into an "Install Sysible Linux" entry (adds sysible.install to the
        # cmdline, which the live session's autostart uses to launch Calamares).
        python3 - "$WORK/grub.cfg" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = re.sub(r'Live system \((.*?) fail-safe mode\)', r'Sysible Linux (Live, safe graphics) [\1]', s)
s = re.sub(r'Live system \((.*?)\)', r'Sysible Linux (Live) [\1]', s)
s = s.replace('Debian GNU/Linux', 'Sysible Linux')
m = re.search(r'menuentry\s+"[^"]*Live[^"]*"\s*\{.*?\n\}', s, re.S)
if m:
    inst = re.sub(r'menuentry\s+"[^"]*"', 'menuentry "Install Sysible Linux"', m.group(0), count=1)
    inst = re.sub(r'(\n\s*linux\s+\S+[^\n]*)', r'\1 sysible.install', inst, count=1)
    s = s + "\n" + inst + "\n"
# Brand the live GRUB menu with the Sysible THEME (dark hex background, centered
# mark, GREEN TEXT highlight — not a solid bar — and the "GNU GRUB version" line
# hidden). This MUST be APPENDED, not prepended: live-build's generated grub.cfg
# sets its own background/colours/theme as it is sourced, and GRUB honours the
# LAST directive when it renders the menu, so a prepended block is silently
# overridden (why arm64 kept the stock blue menu). Appended, ours win. gfxterm +
# a font are already up by this point (the stock menu renders text), so the theme
# has what it needs; we re-assert them for safety. The colour lines are only a
# fallback if the theme file can't load — light-green/black is green text on a
# transparent background (no garish highlight bar), never stock blue.
vis = ('\n\n# --- Sysible branding (appended last so it wins) ---\n'
       'insmod all_video\ninsmod efi_gop\ninsmod efi_uga\ninsmod gfxterm\ninsmod png\n'
       'set gfxmode=auto\nterminal_output gfxterm\n'
       'loadfont ($root)/boot/grub/fonts/unicode.pf2\n'
       'set color_normal=light-gray/black\n'
       'set menu_color_normal=light-gray/black\n'
       'set menu_color_highlight=light-green/black\n'
       'set theme=($root)/boot/grub/themes/sysible/theme.txt\n'
       'export theme\n')
open(p, 'w').write(s + vis)
PY
        # isolinux (BIOS): rebrand the entry labels + clone an install entry.
        MAP_LIVE=""
        if [ -s "$WORK/live.cfg" ]; then
            echo "-- isolinux live.cfg BEFORE --"; grep -iE 'label|menu label|append' "$WORK/live.cfg" | head
            python3 - "$WORK/live.cfg" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = re.sub(r'(menu label \^?)Live system \((.*?) fail-safe mode\)', r'\1Sysible Linux (Live, safe) [\2]', s)
s = re.sub(r'(menu label \^?)Live system \((.*?)\)', r'\1Sysible Linux (Live) [\2]', s)
m = re.search(r'(^label[^\n]*\n(?:[ \t]+[^\n]*\n)+)', s, re.M)
if m:
    b = m.group(1)
    b = re.sub(r'^label[^\n]*', 'label install-sysible', b, count=1, flags=re.M)
    b = re.sub(r'menu label [^\n]*', 'menu label ^Install Sysible Linux', b, count=1)
    b = re.sub(r'[ \t]*menu default[ \t]*\n', '', b)
    b = re.sub(r'(append[^\n]*)', r'\1 sysible.install', b, count=1)
    s = s + "\n" + b + "\n"
open(p, 'w').write(s)
PY
            MAP_LIVE="-map $WORK/live.cfg /isolinux/live.cfg"
        fi
        # Ship the Sysible GRUB theme onto the ISO's own boot filesystem so the
        # live menu (set theme=... above) can load it. The same theme dir is also
        # in the installed system via includes.chroot, so live + installed match.
        THEME_SRC="$PWD/config/includes.chroot/boot/grub/themes/sysible"
        MAP_THEME=""
        [ -d "$THEME_SRC" ] && MAP_THEME="-map $THEME_SRC /boot/grub/themes/sysible"
        $SUDO xorriso -boot_image any keep -dev "$ISO" \
            -map "$WORK/grub.cfg" /boot/grub/grub.cfg \
            -map "$WORK/sysible-splash.png" /boot/grub/sysible-splash.png \
            $MAP_THEME \
            $MAP_LIVE \
            -commit 2>&1 | tail -4
        # Post-commit verification is debug-only and MUST NOT fail the build.
        # On arm64 there is no isolinux, so extracting /isolinux/live.cfg errors;
        # guard every check with `|| true` so the (already-committed) branding
        # isn't undone by a failing diagnostic under `set -e`.
        echo "-- isolinux live.cfg AFTER --"
        $SUDO xorriso -osirrox on -indev "$ISO" -extract /isolinux/live.cfg "$WORK/live-after.cfg" 2>/dev/null || true
        grep -iE 'menu label|label install' "$WORK/live-after.cfg" 2>/dev/null | head || true
        echo "-- grub.cfg AFTER (re-extracted from ISO) --"
        $SUDO xorriso -osirrox on -indev "$ISO" -extract /boot/grub/grub.cfg "$WORK/after.cfg" 2>/dev/null || true
        grep -iE 'menuentry|background_image|Sysible|Live system' "$WORK/after.cfg" 2>/dev/null | head -20 || true
        echo "-- boot structures still present? --"
        $SUDO xorriso -indev "$ISO" -report_el_torito plain 2>&1 | grep -iE 'El Torito|Boot|Platform|catalog' | head || true
        $SUDO xorriso -indev "$ISO" -report_system_area plain 2>&1 | grep -iE 'ISO|MBR|GPT|isohybrid|System area type' | head || true
    else
        echo "!! could not extract /boot/grub/grub.cfg from $ISO"
    fi
    rm -rf "$WORK"
    echo "===== end GRUB branding ====="
fi

# --- verify boot branding landed in the built tree -------------------------
# binary/ persists after lb build, so we can prove the overrides were consumed
# without downloading the ISO. Look for our title + splash in the assembled tree.
echo "===== POST-BUILD boot-branding verification ====="
for f in $(find binary -maxdepth 4 -name 'menu.cfg' -o -maxdepth 4 -name 'grub.cfg' 2>/dev/null); do
    echo "----- $f -----"
    grep -iE 'menu title|menuentry|background_image|set (menu_)?color|Sysible|Debian' "$f" 2>/dev/null | head -20
done
echo "----- splash images in built tree -----"
find binary -maxdepth 4 -name 'splash.*' -exec ls -la {} \; 2>/dev/null
for sp in $(find binary -maxdepth 4 -name 'splash.png' 2>/dev/null); do
    echo "md5 $sp vs our override:"; md5sum "$sp" config/bootloaders/isolinux/splash.png 2>/dev/null
done
echo "===== end verification ====="
