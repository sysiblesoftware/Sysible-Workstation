"""Docker Engine and Compose are part of the DEFAULT install, not a suggestion.

Reported as "just got told docker needed to be installed" — an operator handed a
finished Sysible machine, then told by the installer to go and fetch the one
thing every product on it runs on.

Three separate things each had to be true for that, and none of them was pinned:

  1. docker-ce was a *Recommends* of the metapackage, so nothing required it and
     `--no-install-recommends` dropped it outright. The metapackage is also the
     only thing that reaches an ALREADY-INSTALLED machine through apt, so an
     install that missed Docker could never acquire it by upgrading.
  2. docker-ce is excluded from the generated ISO toolkit list by the VEND filter
     in live-build/build.sh (it is not in Debian), leaving one network-dependent
     vendor hook as the sole thing installing it.
  3. No verify step in either repo so much as mentioned a container runtime, so
     an ISO built while download.docker.com was unreachable looked green.

The fix spans all three, and the three only work TOGETHER: making docker-ce a
hard Depends is safe solely because build.sh now configures Docker's apt repo
through live-build's config/archives, which lands BEFORE packages are installed
— the metapackage .deb is installed from config/packages.chroot in that same
phase, so without the archive the dependency is unresolvable and the whole ISO
build dies on "Package 'docker-ce' has no installation candidate".

So this file asserts them as one unit. Any one of them reverting on its own is
the bug coming back.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CONTROL = REPO / "packages" / "sysible-meta" / "debian" / "control"
BUILD = REPO / "live-build" / "build.sh"
VERIFY = (REPO / "live-build" / "config" / "hooks" / "normal"
          / "9500-sysible-verify.hook.chroot")

RUNTIME = ("docker-ce", "docker-compose-plugin")


def _field(name):
    """The named dependency field of the metapackage, comments stripped.

    debian/control continues a field across lines that start with whitespace, and
    this file carries full-line comments inside its fields — which dpkg tolerates
    and a naive read does not.
    """
    text = CONTROL.read_text()
    body = re.search(rf"^{name}:(.*?)^(?=[A-Z][A-Za-z-]*:)", text, re.S | re.M)
    assert body, f"the metapackage has no {name} field"
    return [l for l in body.group(1).splitlines() if not l.strip().startswith("#")]


def _names(field):
    out = []
    for line in _field(field):
        for dep in line.split(","):
            dep = dep.strip().split()[0] if dep.strip() else ""
            if dep:
                out.append(dep)
    return out


class TestTheMetapackageRequiresThem:
    @pytest.mark.parametrize("pkg", RUNTIME)
    def test_it_is_a_hard_dependency(self, pkg):
        assert pkg in _names("Depends"), (
            f"{pkg} is not in Depends — every Sysible product runs as a container "
            f"and is brought up with compose, so an install without it cannot run "
            f"the software it was installed to run"
        )

    @pytest.mark.parametrize("pkg", RUNTIME)
    def test_it_is_not_merely_recommended(self, pkg):
        """A Recommends is dropped by --no-install-recommends and is the state
        that produced the report."""
        assert pkg not in _names("Recommends"), (
            f"{pkg} is still in Recommends; a lean build drops it"
        )

    def test_podman_is_still_there_too(self):
        """Not redundant: podman is in Debian proper, so it is the runtime that
        survives an unreachable Docker repo, and install-sysible falls back to it.
        Removing it would make the fallback dead code."""
        assert "podman" in _names("Depends")


class TestTheIsoBuildCanActuallyResolveThem:
    """The hard Depends is only safe because the repo lands early enough."""

    def test_the_docker_archive_is_configured_before_packages(self):
        b = BUILD.read_text()
        assert "config/archives/docker.list.chroot" in b, (
            "build.sh does not write a config/archives entry for Docker. Without "
            "it the metapackage's docker-ce Depends cannot resolve during the "
            "package phase and the ISO build fails."
        )
        assert "config/archives/docker.key.chroot" in b, \
            "the Docker repo is configured with no signing key"

    def test_the_archive_is_written_before_the_package_lists(self):
        """config/archives has to be in place before the toolkit list is
        installed; ordering inside build.sh is what guarantees it."""
        b = BUILD.read_text()
        arch = b.index("config/archives/docker.list.chroot")
        lists = b.index("config/package-lists/sysible-toolkit.list.chroot")
        assert arch < lists, \
            "the Docker archive is set up after the package lists are generated"

    def test_the_signing_key_is_fingerprint_pinned(self):
        """A silently-rotated vendor key has broken this build before
        (HashiCorp's). The failure mode is a long build and then an unresolvable
        dependency, so the mismatch has to stop the build and name the key."""
        b = BUILD.read_text()
        assert "DOCKER_KEY_FPRS" in b, "Docker's signing key is not pinned"
        fprs = re.search(r'DOCKER_KEY_FPRS="([^"]+)"', b)
        assert fprs, "DOCKER_KEY_FPRS is not a plain pinned list"
        for f in fprs.group(1).split():
            assert re.fullmatch(r"[0-9A-F]{40}", f), f"not a full fingerprint: {f}"

    def test_the_pin_matches_the_one_the_keyring_script_uses(self):
        """Two places fetch Docker's key. They must agree, or a rotation fixes
        one and leaves the other failing."""
        script = (REPO / "packages" / "sysible-release" / "scripts"
                  / "fetch-third-party-keyrings.sh")
        if not script.exists():
            pytest.skip("this edition ships no keyring-fetch script")
        pinned = set(re.search(r'DOCKER_KEY_FPRS="([^"]+)"',
                               BUILD.read_text()).group(1).split())
        line = re.search(r"docker\.gpg\)\s*echo\s+\"([^\"]+)\"", script.read_text())
        assert line, "the keyring script no longer pins docker.gpg"
        assert pinned == set(line.group(1).split()), (
            "build.sh and fetch-third-party-keyrings.sh pin different Docker key "
            "fingerprints"
        )


class TestTheIsoCannotShipWithoutThem:
    """The guard that was missing entirely: an ISO built while Docker's repo was
    unreachable looked green and shipped."""

    def test_the_verify_hook_requires_a_container_runtime(self):
        v = VERIFY.read_text()
        assert re.search(r"command -v docker .*\|\|.*command -v podman", v), (
            "the ISO verify hook does not assert a container runtime is present"
        )
        assert "no container runtime in the image" in v, \
            "the runtime assertion does not fail the build with a named reason"

    def test_the_verify_hook_requires_compose(self):
        v = VERIFY.read_text()
        assert "no compose implementation in the image" in v, (
            "nothing asserts compose is in the image; compose is packaged "
            "separately from the engine on every path, so the engine landing "
            "does not mean a product can be brought up"
        )
