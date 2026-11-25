"""The Workstation install must offer to set up the platform apps.

Reported as "I got fairly far in the install process and did not see a menu to
install slop, slep or controller". There was none. The Optional-apps page
offered Obsidian, VS Code and the HashiCorp tools and nothing of Sysible's own;
the apps were reachable only through a desktop launcher that the slideshow
mentions once, in passing, while the install is still running. The Server
install has asked since its sysible/apps debconf question went in, so the two
products disagreed about whether this is part of installing at all.

The feature is a chain across six files -- a YAML page, a control file, four
.install files, a unit, a postinst and a shell script -- and none of it can be
exercised without building an ISO and running an install. So the chain is
pinned here instead: every link that could drift silently is asserted against
the file on the other side of it.
"""
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "live-build/config/includes.chroot/etc/calamares/netinstall-optional-apps.yaml"
PKG = ROOT / "packages/sysible-platform-apps"
SCRIPT = PKG / "usr/bin/sysible-install-platform-apps"
UNIT = PKG / "debian/sysible-platform-installer.service"

# What install-sysible itself accepts; the markers may not invent names.
INSTALL_SYSIBLE = ROOT / "packages/sysible-cli/install-sysible"


def _page():
    return yaml.safe_load(PAGE.read_text())


def _packages_offered():
    out = []
    for group in _page():
        out += group.get("packages", []) or []
        for sub in group.get("subgroups", []) or []:
            out += sub.get("packages", []) or []
    return out


def _binaries_declared():
    stanzas = (PKG / "debian/control").read_text().split("\n\n")
    return [l.split(":", 1)[1].strip()
            for s in stanzas for l in s.splitlines() if l.startswith("Package:")]


def test_the_page_offers_every_platform_app():
    """The regression itself: slop, controller, slep and connect must each be
    tickable. This is the assertion that was missing."""
    offered = _packages_offered()
    for app in ("slop", "controller", "slep", "connect"):
        assert f"sysible-app-{app}" in offered, (
            f"the installer offers no way to set up {app}; page offers {offered}")


def test_the_platform_comes_before_the_third_party_tools():
    """It is what the operator came for. Buried under eight vendor tools it is
    the same miss again, with the menu technically present."""
    names = [g["name"] for g in _page()]
    assert len(names) >= 2, names
    assert "Sysible" in names[0], names


def test_every_package_the_page_offers_is_one_this_repo_builds_or_a_vendor_one():
    """A typo here is invisible: Calamares' netinstall group is non-critical, so
    an unresolvable package name means the box does nothing and the install
    carries on reporting success."""
    built = set()
    for control in (ROOT / "packages").glob("*/debian/control"):
        for line in control.read_text().splitlines():
            if line.startswith("Package:"):
                built.add(line.split(":", 1)[1].strip())
    # Third-party names resolve against vendor repositories sysible-release adds.
    vendor = {"code", "terraform", "packer", "vault", "consul", "nomad", "boundary"}
    for p in _packages_offered():
        assert p in built or p in vendor, f"{p} is neither built here nor a known vendor package"


def test_every_app_package_declared_is_actually_offered():
    """The other direction: a binary nobody can tick is dead weight, and means
    the page was edited without the control file or the reverse."""
    declared = {b for b in _binaries_declared() if b.startswith("sysible-app-")}
    offered = set(_packages_offered())
    assert declared, "no sysible-app-* binaries declared"
    assert declared <= offered, f"declared but not offered: {sorted(declared - offered)}"


def test_each_app_package_ships_exactly_the_marker_its_name_promises():
    """The marker filename IS the argument passed to install-sysible. A package
    shipping the wrong marker installs the wrong product."""
    for app in ("slop", "controller", "slep", "connect"):
        inst = PKG / f"debian/sysible-app-{app}.install"
        assert inst.is_file(), f"missing {inst.name}"
        lines = [l.split() for l in inst.read_text().splitlines() if l.strip()]
        assert len(lines) == 1, f"{inst.name} should ship one marker, got {lines}"
        src, dest = lines[0][0], lines[0][1]
        assert pathlib.Path(src).name == app, f"{inst.name} ships marker {src!r}, not {app!r}"
        assert (PKG / src).is_file(), f"{inst.name} points at a missing file: {src}"
        assert dest.rstrip("/").endswith("platform-apps.wanted.d"), dest


def test_the_marker_names_are_names_install_sysible_accepts():
    """`install-sysible slopp` exits with usage and the service records a
    failure nobody will read. The product list lives in that script."""
    if not INSTALL_SYSIBLE.is_file():
        pytest.skip("install-sysible not in this repo")
    m = re.search(r'^PRODUCTS_ALL="([^"]+)"', INSTALL_SYSIBLE.read_text(), re.M)
    assert m, "could not find PRODUCTS_ALL in install-sysible"
    accepted = set(m.group(1).split())
    markers = {p.name for p in (PKG / "markers").iterdir() if p.is_file()}
    assert markers, "no markers shipped"
    assert markers <= accepted, (
        f"markers install-sysible would reject: {sorted(markers - accepted)}; "
        f"it accepts {sorted(accepted)}")


def test_the_script_disables_the_unit_that_is_actually_shipped():
    """debhelper names the unit after the .service FILE. The script first said
    sysible-platform-apps.service, which does not exist -- and `|| true` on the
    disable meant it would have failed in silence, re-running every boot."""
    shipped = {p.name for p in (PKG / "debian").glob("*.service")}
    m = re.search(r'^UNIT=(\S+)', SCRIPT.read_text(), re.M)
    assert m, "the script names no unit"
    assert m.group(1) in shipped, f"script disables {m.group(1)}, package ships {shipped}"


def test_the_script_and_the_unit_agree_on_where_state_lives():
    """The unit refuses to run once the state file exists. If the script writes
    somewhere else, the install repeats on every boot, rebuilding containers."""
    state = re.search(r'^STATE=(\S+)', SCRIPT.read_text(), re.M)
    assert state, "the script names no state file"
    cond = re.search(r'ConditionPathExists=!(\S+)', UNIT.read_text())
    assert cond, "the unit has no ConditionPathExists guard"
    assert state.group(1) == cond.group(1), (
        f"script writes {state.group(1)}, unit watches {cond.group(1)}")


def test_the_script_and_the_unit_agree_on_where_the_markers_live():
    wanted = re.search(r'^WANTED_DIR=(\S+)', SCRIPT.read_text(), re.M)
    assert wanted, "the script names no marker directory"
    cond = re.search(r'ConditionDirectoryNotEmpty=(\S+)', UNIT.read_text())
    assert cond, "the unit does not skip itself when nothing was ticked"
    assert wanted.group(1) == cond.group(1), (
        f"script reads {wanted.group(1)}, unit checks {cond.group(1)}")
    # ...and that is where the .install files actually put them.
    dest = (PKG / "debian/sysible-app-slop.install").read_text().split()[1].rstrip("/")
    assert wanted.group(1).lstrip("/") == dest.lstrip("/"), (
        f"markers are installed to /{dest}, the script reads {wanted.group(1)}")


def test_the_install_does_not_happen_from_a_maintainer_script():
    """The lesson the Obsidian installer's postinst records: install-sysible
    shells out to apt and docker, and a nested dpkg call from inside a running
    transaction aborts the parent -- during the ISO chroot AND during
    Calamares' package step. It belongs in the first-boot unit, nowhere else."""
    post = (PKG / "debian/sysible-platform-installer.postinst").read_text()
    body = "\n".join(l for l in post.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("install-sysible", "apt-get", "apt ", "docker"):
        assert forbidden not in body, (
            f"postinst runs {forbidden!r}; that corrupts the enclosing dpkg run")
    assert "#DEBHELPER#" in post, "postinst never enables the unit"


def test_the_service_waits_for_a_real_network():
    """It clones from GitHub and builds containers. A configured interface is
    not the same as a reachable one."""
    u = UNIT.read_text()
    # Comments only, stripped: the unit's own commentary explains the `|| true`,
    # so a substring check over the whole file reads the prose and passes while
    # the directive says something else. (The same way a pool check once read
    # the comment naming grub-efi-ia32-bin instead of the entry.)
    directives = "\n".join(l for l in u.splitlines() if not l.lstrip().startswith("#"))
    assert "network-online.target" in directives, directives
    assert re.search(r'^Type=oneshot', directives, re.M), directives
    # A no-network boot must not leave a failed unit / degraded system.
    execs = re.findall(r'^ExecStart=(.*)$', directives, re.M)
    assert execs, directives
    assert all("|| true" in e for e in execs), (
        f"a failed attempt would mark the system degraded: {execs}")
