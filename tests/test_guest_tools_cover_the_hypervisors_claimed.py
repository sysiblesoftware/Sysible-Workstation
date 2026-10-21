"""The image must carry guest tools for every hypervisor it says it supports.

Reported as mouse clicks not working in a VM. The package list said:

    # Guest integration for VMware/VirtualBox/KVM (clipboard, auto-resize, folder
    # sharing) — Sysible Workstation commonly runs in a VM

and then listed open-vm-tools and open-vm-tools-desktop, which are VMware's and
do nothing on a KVM host. The KVM half was never there.

That gap is not cosmetic. On KVM/QEMU with SPICE and no spice-vdagent the guest
pointer is RELATIVE, so the cursor the guest draws drifts away from the host's:
you click where you see the arrow and the press lands somewhere else. The
operator reads that as "clicks don't work", not as a pointer alignment problem,
which is how it goes unexplained.

These assert the list against what it claims, because a comment promising
coverage is the thing that stopped anyone looking.
"""
import re
from pathlib import Path

import pytest

LIST = Path(__file__).resolve().parents[1] / "live-build/config/package-lists/sysible.list.chroot"
TEXT = LIST.read_text(encoding="utf-8")
PACKAGES = {l.strip() for l in TEXT.splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


def test_vmware_guests_are_covered():
    assert "open-vm-tools" in PACKAGES
    assert "open-vm-tools-desktop" in PACKAGES


def test_kvm_guests_are_covered_too():
    """The half that was missing. Without it a SPICE guest's pointer is relative
    and the clicks land away from the cursor."""
    assert "spice-vdagent" in PACKAGES, \
        "a KVM/SPICE guest has no agent: its pointer will not track the host's"


def test_the_host_side_kvm_agent_is_there():
    """open-vm-tools' counterpart: clean shutdown, virsh domifaddr, fsfreeze."""
    assert "qemu-guest-agent" in PACKAGES


@pytest.mark.parametrize("hypervisor,package", [
    ("VMware", "open-vm-tools"),
    ("KVM", "spice-vdagent"),
])
def test_every_hypervisor_named_in_the_comment_has_a_package(hypervisor, package):
    """The defect was a comment claiming coverage the list did not have. If a
    hypervisor is named, something in here must actually serve it."""
    guest = TEXT[TEXT.index("# Guest integration"):]
    guest = guest[:guest.index("# Right-click")]
    assert hypervisor in guest or hypervisor.lower() in guest.lower(), \
        f"{hypervisor} is no longer named — update this test with the comment"
    assert package in guest, f"{hypervisor} is named but {package} is not listed"


def test_the_comment_no_longer_claims_vmware_tools_cover_kvm():
    """The original wording lumped three hypervisors onto two VMware packages."""
    guest = TEXT[TEXT.index("# Guest integration"):]
    guest = guest[:guest.index("# Right-click")]
    assert "Guest integration for VMware/VirtualBox/KVM" not in guest, \
        "the comment still promises KVM coverage from VMware's tools"


def test_the_package_list_stays_parseable():
    """One package per line, no stray continuations — live-build reads this
    literally, and a malformed line fails the build rather than being skipped."""
    for i, line in enumerate(TEXT.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", s), f"line {i}: {s!r}"
