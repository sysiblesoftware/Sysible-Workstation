"""Nothing may drift into the ISO alone without someone saying why.

Sysible Workstation reaches a user two ways, and they are maintained in two
different files:

  * a fresh install, from live-build/config/package-lists/sysible.list.chroot
  * an existing machine, from `apt upgrade`, which pulls only what the
    sysible-workstation metapackage declares in packages/sysible-meta/debian/control

Two shipped bugs have now come from editing the first and forgetting the second:

  1.0.3  spice-vdagent and qemu-guest-agent were added to the ISO list to fix
         "clicks land in the wrong place on KVM". The metapackage was not
         touched, so every installed machine kept the broken pointer and the
         release notes claimed a fix those machines could never receive.
  1.0.4  the apt repository published only from release tags, which never fired,
         so installed machines sat on the 28 August packages for months while
         development published to sysible-dev on every commit.

Both were invisible because nothing compared the two paths. This file is the
ratchet: every package in the ISO list that is NOT reachable through the
metapackage has to be named below with a reason. Add one to the image alone and
this test fails until you either declare it in the metapackage or say here, in
writing, why an installed machine does not need it.

It deliberately does NOT demand the two lists be equal. Some packages must stay
out of the metapackage — live-boot on an installed system is wrong, not missing.
The point is that the decision is recorded rather than assumed.
"""
from pathlib import Path

import pytest

from test_guest_tools_cover_the_hypervisors_claimed import (
    _iso_packages, _metapackage_packages,
)

# Every package that is in the ISO image and not declared by the metapackage,
# with the reason an upgraded machine is still correct without it.
ISO_ONLY = {
    # --- live-image machinery: wrong on an installed system, not missing ---
    "live-boot": "boots the squashfs; an installed system boots its own root",
    "live-config": "configures the live session only",
    "live-config-systemd": "live-config's systemd half",
    "calamares-settings-debian": "the installer's branding; nothing to install from "
                                 "once installed (calamares itself is a Recommends)",

    # --- arrives with the desktop, so apt already tracks it ---
    "gdm3": "pulled in by gnome-core, which the metapackage recommends",
    "plymouth": "pulled in by the desktop; the sysible theme is package-owned",
    "plymouth-themes": "ditto — the boot splash theme set",

    # --- firmware: physically copied onto the installed system by Calamares ---
    # Named in the image so the live session can bring up Wi-Fi on the hardware
    # it is being installed from. Calamares copies the filesystem, so dpkg knows
    # them afterwards and apt upgrades them; the metapackage need not declare them.
    "firmware-linux": "copied onto the installed system by Calamares",
    "firmware-linux-nonfree": "copied onto the installed system by Calamares",
    "firmware-misc-nonfree": "copied onto the installed system by Calamares",
    "firmware-atheros": "copied onto the installed system by Calamares",
    "firmware-brcm80211": "copied onto the installed system by Calamares",
    "firmware-iwlwifi": "copied onto the installed system by Calamares",
    "firmware-libertas": "copied onto the installed system by Calamares",
    "firmware-realtek": "copied onto the installed system by Calamares",
    "firmware-ti-connectivity": "copied onto the installed system by Calamares",
    "firmware-zd1211": "copied onto the installed system by Calamares",

    # --- shipped in the image, deliberately not declared ---
    # An apt-only install (sysible-workstation onto a plain Debian box) does not
    # get these. Accepted: they are Debian's own defaults, not Sysible's, and a
    # user adding them is one apt install away.
    "firefox-esr": "Debian's default browser, not a Sysible component",
    "gnome-text-editor": "Debian's default editor, not a Sysible component",
    "xterm": "fallback terminal; SysTerm is the Sysible one and IS declared",

    # --- the Nautilus "Open in SysTerm" extension's runtime deps ---
    # KNOWN GAP, recorded rather than silently fixed: an apt-only install gets
    # the right-click entry without the python-gi stack behind it. Widening the
    # metapackage changes what every install pulls, so it is a deliberate
    # decision and not a drive-by edit on a pointer-alignment fix.
    "python3-nautilus": "KNOWN GAP: right-click 'Open in SysTerm' needs it",
    "python3-gi": "KNOWN GAP: the Nautilus extension's GObject bindings",
    "gir1.2-gtk-3.0": "KNOWN GAP: typelib for the Nautilus extension",
    "gir1.2-vte-2.91": "KNOWN GAP: typelib for the terminal widget",
    "libglib2.0-dev-bin": "KNOWN GAP: glib-compile-schemas for the extension",
}


def test_every_iso_only_package_has_a_recorded_reason():
    """The ratchet. A package added to the image alone lands here."""
    undeclared = (_iso_packages() - _metapackage_packages()) - set(ISO_ONLY)
    assert not undeclared, (
        "these are in the ISO but cannot reach an installed machine via apt, and "
        "no reason is recorded for that:\n"
        + "\n".join(f"  - {p}" for p in sorted(undeclared))
        + "\n\nEither declare them in packages/sysible-meta/debian/control so "
          "`apt upgrade` delivers them, or add them to ISO_ONLY with the reason "
          "an installed machine is still correct without them."
    )


def test_the_recorded_reasons_still_describe_reality():
    """Kept honest in the other direction: once a package IS declared in the
    metapackage, or leaves the image, its excuse here is stale and misleading."""
    iso, meta = _iso_packages(), _metapackage_packages()
    for pkg in sorted(ISO_ONLY):
        assert pkg in iso, f"{pkg} is no longer in the ISO list — drop it from ISO_ONLY"
        assert pkg not in meta, (
            f"{pkg} IS declared in the metapackage now — drop it from ISO_ONLY, "
            f"its recorded reason is stale"
        )


def test_no_reason_is_left_blank():
    for pkg, why in ISO_ONLY.items():
        assert why and len(why) > 15, f"{pkg} has no real reason recorded: {why!r}"


@pytest.mark.parametrize("pkg", [
    "spice-vdagent", "qemu-guest-agent", "open-vm-tools",
])
def test_guest_tools_are_never_an_acceptable_iso_only_package(pkg):
    """The 1.0.3 regression, pinned. A guest agent only does its job on the
    machine it is running on, so shipping it to the image alone is never the
    right answer — there is no reason that could go in ISO_ONLY for these."""
    assert pkg not in ISO_ONLY, (
        f"{pkg} must reach installed machines; it cannot be excused as ISO-only"
    )
    assert pkg in _metapackage_packages(), f"{pkg} is not declared in the metapackage"


def test_the_known_gaps_are_findable():
    """If someone decides to close them, they should be greppable as a set."""
    gaps = [p for p, why in ISO_ONLY.items() if why.startswith("KNOWN GAP")]
    assert gaps, "the KNOWN GAP marker disappeared — was it closed or just reworded?"
    for p in gaps:
        assert p not in _metapackage_packages()
