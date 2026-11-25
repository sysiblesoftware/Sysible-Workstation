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


# ---------------------------------------------------------------------------
# An opt-in package must not be baked into the image
# ---------------------------------------------------------------------------

BUILD = ROOT / "live-build" / "build.sh"


def _repo_built_packages():
    out = set()
    for control in (ROOT / "packages").glob("*/debian/control"):
        for line in control.read_text().splitlines():
            if line.startswith("Package:"):
                out.add(line.split(":", 1)[1].strip())
    return out


def test_nothing_the_page_offers_is_already_installed_by_the_image():
    """Everything left in config/packages.chroot is INSTALLED during the package
    phase -- build.sh's own metapackage note depends on exactly that. So a
    package whose point is "only if the operator ticks the box" is installed on
    every machine if it ships there, and the page becomes a decoration while its
    own text promises that "leaving them unticked installs nothing".

    This was already happening to sysible-obsidian-installer: its first-boot
    service downloaded and installed a proprietary application on every
    Workstation, unasked. The platform markers would have installed the entire
    Sysible platform the same way."""
    build = BUILD.read_text()
    offered = set(_packages_offered()) & _repo_built_packages()
    assert offered, "no repo-built package is offered -- this guard would be vacuous"
    # Comments stripped: a name in a comment is not an exclusion.
    code = "\n".join(l for l in build.splitlines() if not l.lstrip().startswith("#"))
    missing = [p for p in sorted(offered) if p not in code]
    assert not missing, (
        "opt-in package(s) would be installed on every machine because build.sh "
        f"never removes them from config/packages.chroot: {missing}")


def test_the_exclusion_actually_removes_them(tmp_path):
    """Run the loop rather than read it. A glob that matches nothing removes
    nothing, in silence -- and build-all.sh stamps a CI version suffix onto
    every filename, so the pattern has to survive that too."""
    import re
    import subprocess
    build = BUILD.read_text()
    m = re.search(r'for _optin in (.*?)\bdone\b', build, re.S)
    assert m, "could not find the opt-in exclusion loop in build.sh"
    loop = m.group(0)

    offered = sorted(set(_packages_offered()) & _repo_built_packages())
    keep = ["sysible-cli_0.4.2_all", "sysible-meta_0.3.0+ci77_all", "systerm_0.1.9_amd64"]
    drop = [f"{p}_0.1.0+ci77_all" for p in offered]
    pc = tmp_path / "config" / "packages.chroot"
    pc.mkdir(parents=True)
    for f in keep + drop:
        (pc / f"{f}.deb").touch()

    r = subprocess.run(["sh", "-eu", "-c", loop], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    left = sorted(p.name for p in pc.iterdir())
    for f in keep:
        assert f"{f}.deb" in left, f"the loop removed a package the image needs: {f}"
    for f in drop:
        assert f"{f}.deb" not in left, f"still baked into the image: {f}"


# ---------------------------------------------------------------------------
# Ticking a group's own box must select something installable
# ---------------------------------------------------------------------------

def test_no_group_selects_the_gateway_and_a_standalone_together():
    """Calamares' parent checkbox selects every child. These were four ticks
    under one "Sysible platform apps" parent, so ticking it chose the gateway
    stack AND three standalone copies of the same apps -- reported as "if I
    click the top it checks everything but it doesn't make sense to install
    everything".

    It is not merely odd, it cannot be installed: the gateway runs those three
    under container_name sysible-controller / sysible-slep / sysible-connect,
    the same names a standalone install uses, so the second one collides on the
    name and on the port. A parent checkbox has to produce a set that works."""
    standalone = {"sysible-app-controller", "sysible-app-slep", "sysible-app-connect"}
    for group in _page():
        picked = set(group.get("packages", []) or [])
        for sub in group.get("subgroups", []) or []:
            picked |= set(sub.get("packages", []) or [])
        if "sysible-app-slop" in picked and picked & standalone:
            raise AssertionError(
                f"group {group['name']!r} selects the gateway and "
                f"{sorted(picked & standalone)} together, which cannot run on one host")


def test_the_gateway_is_one_tick_on_its_own():
    """"it should be a separate box to just select SLOP". If you want the
    platform, that is the whole decision."""
    groups = [g for g in _page()
              if "sysible-app-slop" in {p for sg in (g.get("subgroups") or [])
                                        for p in (sg.get("packages") or [])}
              | set(g.get("packages") or [])]
    assert len(groups) == 1, f"slop appears in {len(groups)} groups"
    picked = set(groups[0].get("packages") or [])
    for sub in groups[0].get("subgroups") or []:
        picked |= set(sub.get("packages") or [])
    assert picked == {"sysible-app-slop"}, (
        f"the gateway's group also drags in {sorted(picked - {'sysible-app-slop'})}")


def test_the_standalones_can_be_taken_together_or_a_few():
    """"a box to select all of the stand alones or just a few of them" -- so
    they share one group, and each is its own child inside it."""
    standalone = {"sysible-app-controller", "sysible-app-slep", "sysible-app-connect"}
    groups = []
    for g in _page():
        picked = set(g.get("packages") or [])
        for sub in g.get("subgroups") or []:
            picked |= set(sub.get("packages") or [])
        if picked & standalone:
            groups.append((g, picked))
    assert len(groups) == 1, f"the standalone apps are spread over {len(groups)} groups"
    g, picked = groups[0]
    assert picked == standalone, f"that group also contains {sorted(picked - standalone)}"
    children = [sub for sub in (g.get("subgroups") or []) if sub.get("packages")]
    assert len(children) == 3, (
        f"they must be three separate ticks to take 'just a few': {len(children)}")
