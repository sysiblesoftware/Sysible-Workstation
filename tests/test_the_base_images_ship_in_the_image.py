"""The base images the platform builds FROM must ship in the image.

Reported twice from a fresh Sysible Server, on a host whose resolver could not
answer for auth.docker.io:

    target baseline: failed to solve: failed to fetch anonymous token:
      ... dial tcp: lookup auth.docker.io on 172.16.100.2:53: no such host
    ERROR: Sysible SLOP gateway: compose failed to build or start it

Every apt dependency was present on that machine. These are not apt packages --
the platform is BUILT from source on the host, and those builds pull
python:3.12-slim, node:20-slim, node:22-slim and docker:27-cli from Docker Hub.
"Install all the deps" could never reach them, because they are a network fetch
at build time rather than anything dpkg knows about.

So the ISO carries them, and the first boot loads them into Docker's store
before anything builds.
"""
import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "live-build/config/hooks/normal/8500-sysible-base-images.hook.chroot"
LOADER = ROOT / "live-build/config/includes.chroot/usr/lib/sysible/load-base-images"
UNIT = ROOT / "live-build/config/includes.chroot/usr/lib/systemd/system/sysible-base-images.service"
APPS = ROOT / "live-build/config/includes.chroot/usr/lib/systemd/system/sysible-apps-firstboot.service"
ENABLE = ROOT / "live-build/config/hooks/normal/9600-sysible-firstboot.hook.chroot"
VERIFY = ROOT / "live-build/config/hooks/normal/9500-sysible-verify.hook.chroot"

# Every FROM across the suite, as of writing.
BASE_IMAGES = ["python:3.12-slim", "node:20-slim", "node:22-slim", "docker:27-cli"]


def _code(p):
    return "\n".join(l for l in p.read_text().splitlines() if not l.lstrip().startswith("#"))


# ---- the build bakes them in ----------------------------------------------
@pytest.mark.parametrize("img", BASE_IMAGES)
def test_every_base_image_is_baked(img):
    assert img in HOOK.read_text(), (
        f"{img} is a FROM in the suite and is not baked into the image, so a "
        f"host without Docker Hub cannot build what depends on it")


def test_it_uses_skopeo_not_docker():
    """There is no Docker daemon in a live-build chroot."""
    c = _code(HOOK)
    assert "skopeo copy" in c, "nothing fetches the images"
    assert "docker pull" not in c, "docker pull needs a daemon the chroot does not have"


def test_a_missing_base_image_fails_the_build():
    """Scoped to the FETCH's own failure branch. A bare search for "exit 1"
    matched the separate `skopeo is missing` check further up and passed over a
    fetch that had been allowed to fail quietly."""
    c = _code(HOOK)
    assert "set -e" in c
    i = c.index("skopeo copy")
    j = c.index("done", i)
    assert "exit 1" in c[i:j], \
        "a failed image fetch does not stop the build — the ISO would ship " \
        "without an image the platform builds FROM"


def test_the_architecture_is_not_assumed():
    """Checking that the FLAG is present is not enough: `--override-arch amd64`
    contains it, keeps `dpkg --print-architecture` on its own line above, and
    bakes an arm64 ISO full of amd64 images. Assert the flag takes the detected
    value."""
    c = _code(HOOK)
    assert "dpkg --print-architecture" in c, "the build arch is never detected"
    assert re.search(r'--override-arch\s+"\$ARCH"', c), \
        "the image architecture is hardcoded instead of following the build"


# ---- the installed system loads them ---------------------------------------
@pytest.fixture()
def loaded(tmp_path):
    """Run the REAL loader against a fake docker."""
    bindir, share, var, log = (tmp_path / d for d in ("bin", "share", "var", "log"))
    for d in (bindir, share, var, log):
        d.mkdir(parents=True)
    (bindir / "docker").write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  info) exit ${FAKE_NO_DAEMON:-0} ;;\n'
        '  load) printf "%s\\n" "$*" >> "$CALLS"; exit ${FAKE_LOAD_RC:-0} ;;\n'
        'esac\nexit 0\n')
    (bindir / "docker").chmod(0o755)
    for n in ("a", "b"):
        (share / f"{n}.tar").write_text("x")
    src = LOADER.read_text()
    for a, b in (("/usr/share/sysible/base-images", str(share)),
                 ("/var/lib/sysible/base-images-loaded", f"{var}/mark"),
                 ("/var/log/sysible-base-images.log", f"{log}/l.log")):
        src = src.replace(a, b)
    script = tmp_path / "run.sh"
    script.write_text(src)

    class R:
        mark = var / "mark"
        calls_file = tmp_path / "calls"

        def run(self, **env):
            e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                 "CALLS": str(self.calls_file)}
            e.update({k: str(v) for k, v in env.items()})
            return subprocess.run(["/bin/sh", str(script)], env=e,
                                  capture_output=True, text=True, timeout=60)

        def calls(self):
            if not self.calls_file.exists():
                return []
            return [l for l in self.calls_file.read_text().splitlines() if l.strip()]
    return R()


def test_it_loads_every_tarball(loaded):
    loaded.run()
    assert len(loaded.calls()) == 2, f"not every image was loaded: {loaded.calls()}"


def test_a_successful_load_is_not_repeated(loaded):
    loaded.run()
    loaded.run()
    assert len(loaded.calls()) == 2, "it reloads hundreds of megabytes on every boot"


def test_a_failed_load_is_retried_next_boot(loaded):
    """A partial load remembered as complete is an image store missing exactly
    the layer the build will ask for."""
    loaded.run(FAKE_LOAD_RC=1)
    assert not loaded.mark.exists(), "a failed load was recorded as done"
    loaded.run()
    assert loaded.mark.exists()


def test_it_does_nothing_before_the_daemon_is_up(loaded):
    loaded.run(FAKE_NO_DAEMON=1)
    assert loaded.calls() == [], "it tried to load with no daemon running"
    assert not loaded.mark.exists()


# ---- it is wired in --------------------------------------------------------
def test_the_unit_waits_for_docker():
    u = UNIT.read_text()
    assert "After=docker.service" in u and "Requires=docker.service" in u


def test_the_unit_needs_no_network():
    """The whole point is a host that cannot reach a registry."""
    u = UNIT.read_text()
    assert "network-online" not in u, \
        "an offline-capable load must not wait on the network"


def test_the_unit_is_enabled_in_the_image():
    assert "systemctl enable sysible-base-images.service" in ENABLE.read_text()


def test_nothing_builds_before_the_images_are_loaded():
    # Server installs the chosen apps from a first-boot unit; Workstation has no
    # such unit -- there the operator launches "Install Sysible Software" from
    # the app grid, long after the base-image load has run at boot. Nothing to
    # order against, so nothing to assert.
    if not APPS.exists():
        pytest.skip("no first-boot apps unit on this edition")
    a = APPS.read_text()
    assert "After=sysible-base-images.service" in a, (
        "the first-boot install can start before the images are in the store, "
        "which sends it to Docker Hub for images this machine already carries")


def test_the_build_verifies_they_shipped():
    v = _code(VERIFY)
    assert "base-images" in v and "MANIFEST" in v, \
        "nothing checks the images actually got baked in"
    assert "fail " in v
