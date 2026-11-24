"""Three firmware modes, three grub flavours, one offline pool.

    "The 'grub-efi-ia32' package failed to install into /target/. Without the
     GRUB boot loader, the installed system will not boot."

d-i's grub-installer apt-installs a flavour METApackage chosen by the firmware:
grub-pc for BIOS, grub-efi-ia32 for 32-bit UEFI, grub-efi-amd64 for 64-bit. The
pool held only the last of the three, so 64-bit UEFI was the only firmware this
image could actually finish an install on -- which is also why the earlier
BIOS attempt died at the same step with a different package name.

Workstation installs with Calamares rather than the Debian Installer, so it has
no preseed and no late_command to get wrong -- but Calamares installs GRUB from
THE SAME OFFLINE POOL, so the missing flavour is the same missing flavour. Only
the pool half of the Server guard applies here; the rest lives there.

Secure Boot was already right here; Server is what had to catch up.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD = (REPO / "live-build" / "build.sh").read_text(encoding="utf-8")
SH = shutil.which("sh")


def _amd64_pool():
    """The package list this build writes for amd64.

    COMMENTS ARE STRIPPED FIRST. The first version of this did not, and the
    comments above the list name grub-efi-ia32-bin several times explaining why
    it is there -- so deleting it from the actual printf still "passed". A guard
    satisfied by its own explanation, which is the same trap as one tripped by
    it. Found by mutation.
    """
    blk = BUILD[BUILD.index('if [ "$ARCH" = "arm64" ]'):]
    blk = blk[blk.index("else"):blk.index("> config/package-lists/sysible-grub.list.chroot", blk.index("else"))]
    code = "\n".join(l for l in blk.split("\n") if not l.strip().startswith("#"))
    return set(re.findall(r"[a-z0-9][a-z0-9.+-]*", code.replace("printf", " ").replace("%s", " ")))


# ---- the pool has a flavour for every firmware ------------------------------
@pytest.mark.parametrize("pkg,why", [
    ("grub-efi-amd64-bin", "64-bit UEFI"),
    ("grub-efi-ia32-bin", "32-bit UEFI — the reported failure"),
    ("grub-pc-bin", "legacy BIOS"),
])
def test_the_offline_pool_can_boot_each_firmware(pkg, why):
    assert pkg in _amd64_pool(), f"nothing in the pool can install GRUB for {why}"


def test_the_metapackages_are_still_kept_out():
    """grub-pc and grub-efi-ia32 CONFLICT with grub-efi-amd64; only one can be
    installed in the chroot, which is why the -bin packages are used."""
    pool = _amd64_pool()
    for meta in ("grub-pc", "grub-efi-ia32"):
        assert meta not in pool, \
            f"{meta} conflicts with grub-efi-amd64 and would break the build"


def test_the_image_can_boot_a_secure_boot_machine():
    """Workstation has shipped this for some time; Server had neither package,
    so its ISO was rejected until someone turned Secure Boot off."""
    pool = _amd64_pool()
    assert "shim-signed" in pool, \
        "no Microsoft-signed shim: Secure Boot firmware rejects the ISO outright"
    assert "grub-efi-amd64-signed" in pool, \
        "shim has no Debian-signed grub to chainload"
