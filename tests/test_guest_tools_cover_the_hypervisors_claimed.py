"""Guest tools must reach BOTH the ISO and an already-installed machine.

Reported twice as "mouse clicks aren't working in a VM".

The mechanism: on KVM/QEMU with SPICE and no spice-vdagent the guest pointer is
RELATIVE, so the cursor the guest draws drifts away from the host's — you click
where you see the arrow and the press lands somewhere else. The operator reads
that as "clicks don't work", not as a pointer alignment problem, which is how it
goes unexplained. open-vm-tools is VMware's and does nothing about it.

The first report was fixed in 1.0.3 by adding spice-vdagent and qemu-guest-agent
to the live-build package list. That shipped the fix to the ISO and to nobody
else: Sysible Workstation reaches installed machines through the apt repository,
and on that path the ONLY thing that pulls packages in is the sysible-workstation
metapackage, whose Recommends still listed VMware's two alone. So every machine
installed from an earlier image kept the broken pointer no matter how many times
it ran apt upgrade, while the release notes said it was fixed.

The original version of this file asserted the live-build list and nothing else,
so it went green on that half-fix. Every assertion below is now parametrized
over both delivery paths. A fix to one and not the other fails here.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISO_LIST = ROOT / "live-build/config/package-lists/sysible.list.chroot"
METAPACKAGE = ROOT / "packages/sysible-meta/debian/control"


def _iso_packages():
    """live-build reads this file literally: one package per line, # comments."""
    return {l.strip() for l in ISO_LIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


def _metapackage_packages():
    """Depends + Recommends of sysible-workstation, which is what apt delivers.

    debian/control comments are whole lines starting with '#' (dpkg strips them
    before parsing); field continuations start with a space.
    """
    text = METAPACKAGE.read_text(encoding="utf-8")
    clean = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    para = next(p for p in clean.split("\n\n")
                if re.match(r"Package:\s*sysible-workstation\s*$", p, re.M))
    names = set()
    for field in ("Depends", "Recommends", "Suggests"):
        m = re.search(rf"^{field}:(.*?)(?=^\S[^\n]*:|\Z)", para, re.M | re.S)
        if not m:
            continue
        for entry in m.group(1).replace("\n", " ").split(","):
            entry = entry.strip()
            if entry and not entry.startswith("${"):
                # drop any version relation: "foo (>= 1.2)" -> "foo"
                names.add(entry.split()[0])
    return names


# Both paths a package can travel to a user's machine. The ISO covers a fresh
# install; the metapackage covers `apt upgrade` on a machine already out there,
# which is the larger and more easily forgotten population.
PATHS = [
    pytest.param(_iso_packages, "the ISO package list", id="iso"),
    pytest.param(_metapackage_packages, "the sysible-workstation metapackage",
                 id="metapackage"),
]


@pytest.mark.parametrize("packages,where", PATHS)
def test_vmware_guests_are_covered(packages, where):
    for pkg in ("open-vm-tools", "open-vm-tools-desktop"):
        assert pkg in packages(), f"{pkg} is missing from {where}"


@pytest.mark.parametrize("packages,where", PATHS)
def test_kvm_guests_are_covered_too(packages, where):
    """The half that was missing, in the place it was missing from."""
    assert "spice-vdagent" in packages(), (
        f"a KVM/SPICE guest installed via {where} has no agent: its pointer "
        f"will not track the host's and clicks will land away from the cursor"
    )


@pytest.mark.parametrize("packages,where", PATHS)
def test_the_host_side_kvm_agent_is_there(packages, where):
    """open-vm-tools' counterpart: clean shutdown, virsh domifaddr, fsfreeze."""
    assert "qemu-guest-agent" in packages(), f"qemu-guest-agent missing from {where}"


@pytest.mark.parametrize("packages,where", PATHS)
@pytest.mark.parametrize("hypervisor,package", [
    ("VMware", "open-vm-tools"),
    ("KVM", "spice-vdagent"),
])
def test_every_hypervisor_we_claim_has_a_package_on_every_path(
        hypervisor, package, packages, where):
    """The defect was a comment claiming coverage the delivery did not have."""
    assert package in packages(), (
        f"{hypervisor} is named as supported but {package} is not in {where}"
    )


def test_the_two_paths_agree_on_guest_tools():
    """The actual regression: a guest-tool fix applied to one path only.

    Kept separate from the per-path assertions above because this is the shape
    of the bug — not "a package is missing" but "the two lists disagree".
    """
    guest_tools = {"open-vm-tools", "open-vm-tools-desktop",
                   "spice-vdagent", "qemu-guest-agent"}
    iso = guest_tools & _iso_packages()
    meta = guest_tools & _metapackage_packages()
    assert iso == meta, (
        "the ISO and the metapackage disagree on guest tools, so a fresh "
        "install and an upgraded machine will not behave the same.\n"
        f"  ISO only:          {sorted(iso - meta)}\n"
        f"  metapackage only:  {sorted(meta - iso)}"
    )


def test_the_comment_no_longer_claims_vmware_tools_cover_kvm():
    """The original wording lumped three hypervisors onto two VMware packages."""
    text = ISO_LIST.read_text(encoding="utf-8")
    guest = text[text.index("# Guest integration"):]
    guest = guest[:guest.index("# Right-click")]
    assert "Guest integration for VMware/VirtualBox/KVM" not in guest, \
        "the comment still promises KVM coverage from VMware's tools"


def test_the_metapackage_explains_why_both_families_ship():
    """These four look redundant on any single hypervisor, so the next reader
    needs the reason in front of them or one gets pruned as dead weight."""
    text = METAPACKAGE.read_text(encoding="utf-8")
    assert "spice-vdagent" in text
    assert "RELATIVE" in text, \
        "nothing here says why a SPICE guest needs its own agent"


def test_the_package_list_stays_parseable():
    """One package per line, no stray continuations — live-build reads this
    literally, and a malformed line fails the build rather than being skipped."""
    for i, line in enumerate(ISO_LIST.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", s), f"line {i}: {s!r}"


def test_the_metapackage_control_file_stays_parseable():
    """If the paragraph or the field continuations break, _metapackage_packages
    silently returns a short set and every assertion above goes green on it."""
    names = _metapackage_packages()
    assert len(names) > 50, f"only parsed {len(names)} deps — control file broke?"
    for n in names:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", n), f"bad dep name: {n!r}"
