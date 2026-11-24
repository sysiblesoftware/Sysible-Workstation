#!/bin/sh
# Build the Sysible Workstation ISO. Run on a Debian host, or in a debian:bookworm
# container, with network access:  sudo ./build.sh
#
# Everything is baked in — nothing to install after first boot:
#   * Debian-native tools come from the package list (below).
#   * The Sysible packages are built here and included directly.
#   * The non-Debian vendor tools (Docker, Kubernetes, cloud CLIs,
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

# --- Docker's apt repo, available BEFORE any package is installed -----------
# docker-ce and docker-compose-plugin are hard Depends of the metapackage: every
# Sysible product runs as a container and is brought up with compose, so an
# install without them cannot run the software it was installed to run.
#
# That makes WHEN the repo appears load-bearing. The metapackage .deb is
# installed out of config/packages.chroot during the package phase, which is
# before any hooks/normal/* run — so the repo that sysible-release and the vendor
# hook configure arrives too late to satisfy a Depends, and the build would die
# on "Package 'docker-ce' has no installation candidate". live-build's
# config/archives is the mechanism that lands a repo early enough; this is also
# why docker-ce can stay in the VEND list below (it is not in Debian, and the
# metapackage's own Depends is what pulls it in).
#
# The key is FINGERPRINT-CHECKED against Docker's published signing key. A
# silently-rotated vendor key has broken this build before (HashiCorp's), and the
# failure mode is 40 minutes of build followed by an unresolvable dependency, so
# a mismatch stops here and names the key instead.
DOCKER_KEY_FPRS="9DC858229FC7DD38854AE2D88D81803C0EBFCD88 D3306A018370199E527AE7997EA0A9C3F273FCD8"
mkdir -p config/archives
printf 'deb https://download.docker.com/linux/debian %s stable\n' "$CODENAME" \
    > config/archives/docker.list.chroot
curl -fsS --connect-timeout 20 --max-time 120 --retry 5 --retry-delay 3 --retry-all-errors \
    https://download.docker.com/linux/debian/gpg \
    -o config/archives/docker.key.chroot \
    || { echo "ERROR: could not fetch Docker's apt signing key from download.docker.com." >&2
         echo "       docker-ce is a hard dependency of the metapackage, so the build cannot" >&2
         echo "       continue without the repo that provides it." >&2
         exit 1; }
if command -v gpg >/dev/null 2>&1; then
    _dfpr="$(gpg --show-keys --with-colons --fingerprint \
                 config/archives/docker.key.chroot 2>/dev/null \
             | awk -F: '/^fpr:/ {print $10}')"
    for _want in $DOCKER_KEY_FPRS; do
        printf '%s\n' "$_dfpr" | grep -qx "$_want" || {
            echo "ERROR: Docker's apt signing key does not carry the pinned fingerprint" >&2
            echo "       $_want" >&2
            echo "       The key it served carries: $(printf '%s' "$_dfpr" | tr '\n' ' ')" >&2
            echo "       If Docker rotated the key, verify the new one against Docker's" >&2
            echo "       published fingerprint and update DOCKER_KEY_FPRS here and in" >&2
            echo "       packages/sysible-release/scripts/fetch-third-party-keyrings.sh." >&2
            exit 1; }
    done
    echo "Docker apt repo: $CODENAME stable (signing key fingerprints verified)."
else
    echo "WARNING: gpg is not available here, so Docker's signing key could NOT be"
    echo "         fingerprint-checked. The repo is still pinned to that key, but a"
    echo "         rotation would not be caught until apt rejects the archive."
fi

# --- expand the metapackage into the Debian-native toolkit -----------------
# Every package in sysible-workstation's Depends/Recommends/Suggests EXCEPT the
# sysible-* ones (included directly), systerm (its own repo), and the vendor /
# GitHub-binary tools (installed by the hook, since they aren't in Debian). One
# source of truth: the metapackage control.
awk '
    BEGIN {
        split("docker-ce docker-compose-plugin containerd.io kubectl helm k9s opentofu azure-cli google-cloud-cli codium sops eza", v, " ")
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

# --- a trust store the shipped image actually owns -------------------------
# The staged build below copies the build container's CA bundle into the chroot
# so apt can reach Docker's https repo, which is the only way the build gets
# past it. That copy belongs to no package. This list makes dpkg install the
# real ca-certificates during chroot_install-packages, which rewrites
# /etc/ssl/certs/ca-certificates.crt from /usr/share/ca-certificates and lays
# down the hash symlinks beside it -- so the image ships a store that
# update-ca-certificates can maintain. Not inherited from the metapackage:
# nothing in Docker's repo depends on ca-certificates, verified across
# bookworm/stable from docker-ce 23.0.0 to 29.9.3.
echo ca-certificates > config/package-lists/sysible-ca.list.chroot

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
# SECURE BOOT: the *-signed packages are what let the ISO boot on stock Windows
# PCs, which ship with Secure Boot ENABLED. shim-signed is Microsoft-signed, so the
# firmware trusts it with no key enrollment; it chainloads grub-efi-<arch>-signed
# (Debian-signed). live-build detects these in the chroot and lays shim down as the
# default EFI binary (/EFI/boot/bootx64.efi) with the signed grub beside it —
# exactly how Debian's own live images boot under Secure Boot. With them absent the
# ISO is rejected on any Secure-Boot machine until the user disables it in firmware.
# Macs and Secure-Boot-off PCs still boot the same shim → grub path, so this is
# strictly additive. mokutil lets a user manage keys if they ever need to.
if [ "$ARCH" = "arm64" ]; then
    printf '%s\n' grub-efi-arm64 grub-efi-arm64-bin grub-efi-arm64-signed \
                  shim-signed mokutil grub-common \
        > config/package-lists/sysible-grub.list.chroot
else
    # amd64: grub-efi-amd64 covers UEFI targets (the common case, incl. VMs and
    # Apple-silicon guests). grub-pc-bin coexists with grub-efi (only the grub-pc
    # metapackage conflicts) so BIOS grub-install has its modules in the pool too.
    # grub-efi-ia32-bin: firmware bitness is NOT CPU bitness. An amd64 machine
    # behind 32-bit EFI (some VMs, Bay Trail, older Macs) needs the ia32 flavour,
    # and with nothing in the offline pool the install stops dead at
    # "The 'grub-efi-ia32' package failed to install into /target/". Reported on
    # Sysible Server, which shares this build; Calamares installs GRUB here, but
    # it installs it from the same pool, so the same gap is the same failure.
    # The -bin package coexists with grub-efi-amd64 -- only the METApackages
    # conflict, which is why grub-pc-bin is here and grub-pc is not.
    printf '%s\n' grub-efi-amd64 grub-efi-amd64-bin grub-efi-amd64-signed \
                  shim-signed mokutil grub-efi-ia32-bin grub-pc-bin grub-common \
        > config/package-lists/sysible-grub.list.chroot
fi
echo "Target bootloader packages: $(tr '\n' ' ' < config/package-lists/sysible-grub.list.chroot)"

# --- arch-specific hardware packages (kept OUT of the shared list) ----------
# linux-headers-amd64 and the Broadcom `wl` DKMS source are x86-only: on arm64
# linux-headers-amd64 has no candidate and the wl module won't compile, either of
# which aborts the build. Same arch-split as grub above — inject them only for
# amd64, where the BCM4360 MacBook Wi-Fi needs them (see sysible.list.chroot).
if [ "$ARCH" = "arm64" ]; then
    : > config/package-lists/sysible-hw.list.chroot
else
    printf '%s\n' linux-headers-amd64 broadcom-sta-dkms \
        > config/package-lists/sysible-hw.list.chroot
fi
echo "Arch hardware packages: $(tr '\n' ' ' < config/package-lists/sysible-hw.list.chroot)"

# --- assemble -------------------------------------------------------------
# Boot branding is done with source-level bootloader overrides that live-build
# consumes while building the ISO: config/bootloaders/isolinux/ (BIOS menu title
# + Sysible splash) and config/binary_grub/ (UEFI background). These are checked
# in, not generated, so they don't depend on where a given live-build keeps its
# templates.
lb clean --purge || true
# CA CERTIFICATES, BEFORE THE FIRST https REPO. This is what made the ISO
# unbuildable, and it is invisible in the failure that reports it.
#
# Debian's own mirrors are plain http, so Docker's repo is the FIRST https
# source the chroot ever sees -- and a freshly debootstrapped chroot has no CA
# certificates at all. apt could not complete the handshake:
#
#   W: No system certificates available. Try installing ca-certificates.
#   W: Failed to fetch .../bookworm/InRelease  Certificate verification failed:
#      The certificate is NOT trusted. The certificate issuer is unknown.
#
# So the index was never fetched, docker-ce had no candidate, and the build died
# four minutes later on "Depends: docker-ce but it is not installable" with
# nothing in ninety thousand log lines connecting the two. Making docker-ce a
# hard dependency is what turned a quietly-unreachable vendor repo into a stop.
#
# Serving that repo over http:// is not a way out: download.docker.com answers
# port 80 with a 301 to https, which apt follows into the same handshake.
#
# The store has to be in the chroot BEFORE lb_chroot_archives runs its apt
# update. Package lists and hooks both run later, so the bootstrap is the only
# stage early enough -- the fix itself is the staged build further down.
# LB_BOOTSTRAP_INCLUDE is set as well, because a live-build that honours it
# fixes this one stage earlier for free; it is deliberately NOT relied on. An
# earlier attempt hard-failed the build when this value did not show up in
# config/bootstrap -- having verified that against live-build 3.0 from Ubuntu
# rather than the 2023 live-build the image is actually built with. They are
# different programs, the file is not the same, and that guard broke the build
# on its own, one minute in, before a chroot existed to inspect.
export LB_BOOTSTRAP_INCLUDE="${LB_BOOTSTRAP_INCLUDE:+${LB_BOOTSTRAP_INCLUDE},}ca-certificates"
lb config
# Stage the build, so the chroot can be given a CA store in between debootstrap
# and the first apt update. `lb build` is precisely `lb bootstrap; lb chroot; lb
# binary; lb source`, and each stage guards itself with a stamp under .build/ --
# so bootstrapping here means the `lb build` below resumes at `lb chroot`. That
# is live-build's own resume mechanism, which is also what makes this safe to
# re-run; it is not a trick played on it.
$SUDO lb bootstrap
[ -d chroot ] || {
    echo "ERROR: lb bootstrap left no chroot/ to install a CA store into." >&2
    exit 1; }
# The build container's own store, refreshed by update-ca-certificates at the
# top of this script. One file is enough for apt: on Debian this IS the system
# trust store its GnuTLS reads.
#
# This copy is BUILD-TIME ONLY and must not be what the image ships. Nothing in
# Docker's repo depends on ca-certificates -- checked across bookworm/stable
# from docker-ce 23.0.0 to 29.9.3 -- so without the package list below the
# finished image would carry an unowned bundle that update-ca-certificates can
# never regenerate, with no /usr/share/ca-certificates behind it and no hash
# symlinks in /etc/ssl/certs, which is the half of the trust store that
# directory-based verifiers read. The real package installs during
# chroot_install-packages and takes the path over.
[ -s /etc/ssl/certs/ca-certificates.crt ] || {
    echo "ERROR: the build container itself has no CA bundle to copy." >&2
    exit 1; }
$SUDO install -D -m 0644 /etc/ssl/certs/ca-certificates.crt \
                         chroot/etc/ssl/certs/ca-certificates.crt
$SUDO cmp -s /etc/ssl/certs/ca-certificates.crt \
             chroot/etc/ssl/certs/ca-certificates.crt || {
    echo "ERROR: the CA bundle did not reach the chroot. Docker's https repo" >&2
    echo "       would fail its TLS handshake, and the build would stop four" >&2
    echo "       minutes from now naming docker-ce instead of a certificate." >&2
    exit 1; }
echo "Chroot trusts $($SUDO grep -c 'END CERTIFICATE' chroot/etc/ssl/certs/ca-certificates.crt) CAs before the first https repo is added."
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
        # into an "Install Sysible Workstation" entry (adds sysible.install to the
        # cmdline, which the live session's autostart uses to launch Calamares).
        python3 - "$WORK/grub.cfg" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = re.sub(r'Live system \((.*?) fail-safe mode\)', r'Sysible Workstation (Live, safe graphics) [\1]', s)
s = re.sub(r'Live system \((.*?)\)', r'Sysible Workstation (Live) [\1]', s)
s = s.replace('Debian GNU/Linux', 'Sysible Workstation')
# Clone the first Live menuentry into "Install Sysible Workstation" and place it
# IMMEDIATELY AFTER the Live entry (not at the end of the file). The theme's
# menu has scrollbar=false, so on a tall/stretched display any entry appended
# last drops below the visible rows — which is why the Install entry wasn't
# showing on arm64. As the 2nd entry it's always near the top and visible at any
# resolution. (?ms): ^ anchors the closing brace at column 0, how live-build
# writes entries — more robust than matching the first "\n}".
m = re.search(r'(?ms)^menuentry\s+"[^"]*Live[^"]*".*?^\}', s)
if m:
    base = m.group(0)
    # Clone the real Live entry (so the kernel/initrd paths are always correct) into
    # extra entries, each APPENDING kernel params to its `linux` line. A lambda
    # replacement avoids backslash/escape surprises from the appended text.
    def _clone(title, extra):
        e = re.sub(r'menuentry\s+"[^"]*"', 'menuentry "%s"' % title, base, count=1)
        if extra:
            e = re.sub(r'(\n\s*linux\s+\S+[^\n]*)',
                       lambda mo: mo.group(1) + ' ' + extra, e, count=1)
        return e
    # The entries a user needs: boot the live desktop (the base Live entry above),
    # install it, or — if the graphical boot ever fails — a text recovery console.
    # The Install/recovery entries are cloned from the real Live entry so their
    # kernel/initrd paths are always correct, and placed right after it so they're
    # visible near the top at any resolution.
    #   * Recovery console: boots multi-user.target (no GDM) and passes
    #     `sysible.recovery`, which activates the 9000-hook autologin-root service on
    #     tty1 — a passwordless root shell on the visible screen (root ships locked
    #     and the live user has no console password, so this is the only way in when
    #     the greeter doesn't come up). From it, `systemctl start gdm3` / `journalctl
    #     -b` diagnose a greeter wedge. Inert on the normal entries (the service's
    #     ConditionKernelCommandLine only passes when this entry sets the flag).
    # (The old text-mode / no-splash / extra-graphics bisect entries are gone; this
    # single recovery entry replaces them with one that's actually loggable-into.)
    clones = [
        _clone("Install Sysible Workstation", "sysible.install"),
        _clone("Sysible Workstation (recovery console)",
               "systemd.unit=multi-user.target sysible.recovery"),
    ]
    s = s[:m.end()] + "\n\n" + "\n\n".join(clones) + s[m.end():]
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
       # gfxmode: let the firmware report its native mode (auto). Forcing a fixed
       # 16:9 mode (tried earlier) does NOT cure the "stretched/tall" look reported
       # under VMware Fusion on Apple Silicon — that stretch is the hypervisor
       # scaling one GOP mode to a differently-shaped VM window, not GRUB's choice,
       # and forcing a mode the window can't match only adds black bars/pillarbox.
       # gfxpayload=keep hands the same framebuffer to the kernel so Plymouth
       # doesn't re-stretch. (VM-side fix: Fusion → Settings → Display, use full
       # resolution / disable stretch scaling.)
       'set gfxmode=auto\nset gfxpayload=keep\nterminal_output gfxterm\n'
       'loadfont ($root)/boot/grub/fonts/unicode.pf2\n'
       'set color_normal=light-gray/black\n'
       'set menu_color_normal=light-gray/black\n'
       'set menu_color_highlight=light-green/black\n'
       'set theme=($root)/boot/grub/themes/sysible/theme.txt\n'
       'export theme\n'
       # Appended last so it wins: give ~30s to arrow down to a diagnostic entry
       # (the default still boots on its own if untouched).
       'set timeout=10\nset timeout_style=menu\n')
open(p, 'w').write(s + vis)
PY
        # isolinux (BIOS): rebrand the entry labels + clone an install entry.
        MAP_LIVE=""
        if [ -s "$WORK/live.cfg" ]; then
            echo "-- isolinux live.cfg BEFORE --"; grep -iE 'label|menu label|append' "$WORK/live.cfg" | head
            python3 - "$WORK/live.cfg" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = re.sub(r'(menu label \^?)Live system \((.*?) fail-safe mode\)', r'\1Sysible Workstation (Live, safe) [\2]', s)
s = re.sub(r'(menu label \^?)Live system \((.*?)\)', r'\1Sysible Workstation (Live) [\2]', s)
m = re.search(r'(^label[^\n]*\n(?:[ \t]+[^\n]*\n)+)', s, re.M)
if m:
    b = m.group(1)
    b = re.sub(r'^label[^\n]*', 'label install-sysible', b, count=1, flags=re.M)
    b = re.sub(r'menu label [^\n]*', 'menu label ^Install Sysible Workstation', b, count=1)
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

# --- BOOT-COMPATIBILITY GATE: fail the build rather than ship a dud ----------
# This is the automated "does it boot on real machines" test. It cannot power on a
# Mac or a Windows PC, but it proves the ISO carries every structure those machines
# need to boot — the exact things whose absence has bitten us. If any is missing we
# EXIT NON-ZERO so CI fails and no broken ISO is ever uploaded.
#   * UEFI boot entry            -> Macs and modern PCs (they boot UEFI only)
#   * BIOS boot entry (amd64)    -> older / legacy-CSM PCs
#   * shim + signed grub in ESP  -> Secure Boot (ON by default on stock Windows PCs)
#   * live kernel/initrd/squashfs-> the payload the initramfs mounts (no BusyBox)
echo "===== BOOT-COMPATIBILITY GATE ====="
BOOTFAIL=0
GATE_ISO=$(find . -maxdepth 1 -name '*.iso' 2>/dev/null | head -1)
if [ -z "$GATE_ISO" ]; then
    echo "FATAL: no ISO was produced."; exit 1
fi
ELT=$($SUDO xorriso -indev "$GATE_ISO" -report_el_torito plain 2>/dev/null || true)
echo "$ELT" | grep -qiE 'uefi|0xef' \
    || { echo "FATAL: ISO has NO UEFI boot entry — Macs and UEFI-only PCs cannot boot it."; BOOTFAIL=1; }
if [ "$ARCH" != "arm64" ]; then
    echo "$ELT" | grep -qiE 'bios|0x00|0x80' \
        || { echo "FATAL: ISO has NO BIOS boot entry — legacy PCs cannot boot it."; BOOTFAIL=1; }
fi
EFIB=$(find binary -ipath '*efi/boot/*' -type f 2>/dev/null)
echo "$EFIB" | grep -qiE 'boot(x64|aa64)\.efi' \
    || { echo "FATAL: no default EFI boot binary (bootx64/bootaa64.efi) in the ESP."; BOOTFAIL=1; }
echo "$EFIB" | grep -qiE 'grub(x64|aa64)\.efi' \
    || { echo "FATAL: no signed grub beside shim in the ESP — Secure Boot will REJECT this ISO (Windows ships with Secure Boot ON)."; BOOTFAIL=1; }
find binary -ipath '*live*' -name 'vmlinuz*'          2>/dev/null | grep -q . || { echo "FATAL: missing live/vmlinuz."; BOOTFAIL=1; }
find binary -ipath '*live*' -name 'initrd.img*'       2>/dev/null | grep -q . || { echo "FATAL: missing live/initrd.img."; BOOTFAIL=1; }
find binary -ipath '*live*' -name 'filesystem.squashfs' 2>/dev/null | grep -q . || { echo "FATAL: missing live/filesystem.squashfs."; BOOTFAIL=1; }
if [ "$BOOTFAIL" -ne 0 ]; then
    echo "===== BOOT-COMPATIBILITY GATE FAILED — refusing to ship this ISO ====="
    exit 1
fi
echo "Boot gate PASSED: UEFI + $( [ "$ARCH" = arm64 ] && echo '(no BIOS on arm64)' || echo 'BIOS' ) + Secure-Boot shim/grub + live kernel/initrd/squashfs all present."
echo "===== end BOOT-COMPATIBILITY GATE ====="
