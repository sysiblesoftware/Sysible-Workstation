"""The platform must install on a network with no way out.

Reported twice from a fresh Server whose resolver could not answer for
auth.docker.io, then stated as a requirement: SLOP should install on an
airgapped network and work out of the box.

Building on the host could never satisfy that. Every service's Dockerfile
fetches from PyPI, npm, Debian or Alpine, so no amount of base images shipped
in the ISO gets past the first `pip install`. The only thing that works is
shipping the FINISHED images, built where there is a builder and a network --
in CI -- and loading them at boot.

Three things have to be true together, and each is worthless alone:

  * the images are built and put in the ISO;
  * the SOURCE is too, because compose needs its file and `install-sysible`
    otherwise git-clones it from GitHub;
  * nothing rebuilds them afterwards, or compose goes back to PyPI with the
    images sitting right there.
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/iso.yml"
LOADER = ROOT / "live-build/config/includes.chroot/usr/lib/sysible/load-platform-images"
UNIT = ROOT / "live-build/config/includes.chroot/usr/lib/systemd/system/sysible-platform-images.service"
ENABLE = ROOT / "live-build/config/hooks/normal/9600-sysible-firstboot.hook.chroot"
VERIFY = ROOT / "live-build/config/hooks/normal/9500-sysible-verify.hook.chroot"

WORKFLOW = yaml.safe_load(WF.read_text())
JOBS = WORKFLOW["jobs"]


def _code(p):
    return "\n".join(l for l in p.read_text().splitlines() if not l.lstrip().startswith("#"))


def _steps_text(job):
    return yaml.dump(JOBS[job]["steps"])


# ---- CI builds them --------------------------------------------------------
def test_there_is_a_job_that_builds_the_images():
    assert "app-images" in JOBS, (
        "nothing builds the platform's images, so the ISO can only ship a "
        "recipe that needs the internet to follow")


def test_it_builds_outside_the_iso_container():
    """The iso job runs inside debian:bookworm and has no Docker daemon, so it
    cannot build images. This one must not inherit that container."""
    assert "container" not in JOBS["app-images"], \
        "the image build runs in a container with no Docker daemon"


def test_the_iso_waits_for_them():
    assert JOBS["iso"].get("needs") in ("app-images", ["app-images"]), \
        "the ISO can be built before its images exist"


def test_every_image_is_saved_into_one_archive():
    """One archive, not one per image: a single `docker save` stores shared
    layers once, and every Python service shares the whole python base."""
    t = _steps_text("app-images")
    assert "docker save -o" in t
    assert t.count("docker save") == 1, "saved piecemeal — the base ships many times"


@pytest.mark.parametrize("image", [
    "sysible-slop-idp", "sysible-flashback", "sysible-baseline",
    "sysible-visualizer", "sysible-slop-updater",
    "sysible-controller", "sysible-slep", "sysible-connect",
    "caddy:2-alpine",
])
def test_the_archive_contains_every_service(image):
    assert image in _steps_text("app-images"), (
        f"{image} is not saved — the platform would come up missing a service, "
        f"and on an airgapped host there is no way to fetch it")


def test_the_gateway_image_is_pulled_not_built():
    """caddy is a plain `image:` in SLOP's compose with no build of its own, so
    `compose build` never produces it."""
    assert "docker pull caddy" in _steps_text("app-images")


# ---- the ISO carries them, and the source ----------------------------------
def test_the_iso_collects_the_images():
    assert "download-artifact" in _steps_text("iso")


def test_the_iso_ships_the_source_too():
    """compose needs its own file, and install-sysible git-clones otherwise."""
    t = _steps_text("iso")
    assert "opt/sysible-src" in t, "the platform source does not ship"


def test_the_build_fails_if_either_is_missing():
    """An ISO missing one still builds, boots and installs, then fails at the
    last step -- the worst place to find out."""
    t = _steps_text("iso")
    assert "exit 1" in t and "sysible-images.tar" in t


# ---- the installed system loads them ---------------------------------------
def test_the_loader_reads_the_shipped_archive():
    assert "/usr/share/sysible/app-images" in _code(LOADER)


def test_the_unit_needs_no_network():
    """The whole point is a host that cannot reach anything."""
    assert "network-online" not in UNIT.read_text(), \
        "an offline load must not wait on a network that is not there"


def test_the_unit_is_enabled():
    assert "systemctl enable sysible-platform-images.service" in ENABLE.read_text()


def test_the_build_verifies_both_shipped():
    v = _code(VERIFY)
    assert "sysible-images.tar" in v and "sysible-src" in v
    assert "fail " in v, "the check cannot stop the build"
