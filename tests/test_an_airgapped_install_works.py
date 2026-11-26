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


def _run_code(job):
    """The shell actually run by a job's steps, comments stripped.

    NOT yaml.dump of the steps: that re-serialises and re-wraps, so a comment
    inside a `run:` block comes back as an ordinary line and a line-based scan
    cannot tell it from a command. That is exactly how a comment mentioning
    `docker save` made the single-archive check count two.
    """
    out = []
    for st in JOBS[job]["steps"]:
        for line in (st.get("run") or "").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                out.append(line)
    return out


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
    # Count INVOCATIONS, not mentions: a comment naming `docker save` made this
    # count two the first time.
    calls = [l for l in _run_code("app-images") if "docker save" in l]
    assert calls, "nothing saves the images"
    assert len(calls) == 1, f"saved piecemeal — the base ships many times: {calls}"
    assert "-o" in calls[0], "the archive has no output path"


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


def test_the_profiled_apps_are_actually_built():
    """The Controller, SLEP and Connect sit under the `integrated` profile, and
    compose SKIPS a profiled service unless asked for it. Listing them in the
    save command is not enough -- that is what failed: five images built, three
    did not, and `docker save` was the first thing to notice."""
    build = [l for l in _run_code("app-images") if "compose" in l and " build" in l]
    assert build, "nothing builds the images"
    assert all("--profile integrated" in l for l in build), (
        "the build does not ask for the integrated profile, so the Controller, "
        "SLEP and Connect are silently skipped")


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


# --------------------------------------------------------------------------
# The installer itself.
#
# Everything above shipped, and ticking "slop" in the installer STILL left a
# host with nothing running. The ISO side was all correct; `install-sysible`
# refused before it looked at any of it:
#
#     say "== checking the internet connection =="
#     _online || { ... "Nothing has been installed." ; exit 1; }
#
# An unconditional gate, so on a host with no route out the first-boot service
# ran the script, the script exited 1 with "Nothing has been installed", the
# service retried three times and wrote /etc/sysible/apps-failed -- while the
# images and the source sat on the disk, unread. And past that gate, the
# per-product loop would still `git clone` all three apps that the shipped SLOP
# checkout already vendors.
#
# These run the real script against a simulated host, because a grep for the
# fix would have passed on the broken version too: the gate it has to NOT run
# is still in the file, for the host that does need it.
INSTALLER = ROOT / "packages/sysible-cli/install-sysible"

_STUB_OFFLINE = {
    "curl": '#!/bin/sh\necho "curl: (6) Could not resolve host" >&2\nexit 6\n',
    "git": (
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in clone|ls-remote)\n'
        '  echo "fatal: unable to access" >&2; exit 128 ;; esac; done\n'
        'case " $* " in *" pull "*) echo "fatal: unable to access" >&2; exit 1 ;; esac\n'
        "exit 0\n"
    ),
}
_STUB_ONLINE = {
    "curl": "#!/bin/sh\nexit 0\n",
    "git": (
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  if [ "$a" = clone ]; then\n'
        '    d=$(eval echo "\\${$#}"); mkdir -p "$d/.git" "$d/deploy"\n'
        "    printf 'services: {}\\n' > \"$d/deploy/docker-compose.yml\"\n"
        "    printf '#!/bin/sh\\nexit 0\\n' > \"$d/deploy/sysiblectl\"\n"
        '    chmod +x "$d/deploy/sysiblectl"; echo "CLONED $d"; exit 0\n'
        "  fi\n"
        "done\n"
        "exit 0\n"
    ),
}
_STUB_COMMON = {
    "sysiblectl": (
        "#!/bin/sh\n"
        'echo "SYSIBLECTL product=$1 verb=${2:-}'
        ' dir=${SYSIBLE_CONTROLLER_DIR:-}${SYSIBLE_SLEP_DIR:-}'
        '${SYSIBLE_CONNECT_DIR:-}${SYSIBLE_SLOP_DIR:-}"\nexit 0\n'
    ),
    "docker": "#!/bin/sh\nexit 0\n",
    "whiptail": "#!/bin/sh\nexit 0\n",
}


def _host(tmp_path, *, network, ships_platform, also_cloned=(), ships_images=None):
    """A fake machine: stub binaries on PATH and the on-disk state under tmp."""
    import os
    import stat

    bins = tmp_path / "bin"
    bins.mkdir()
    for name, body in {
        **(_STUB_ONLINE if network else _STUB_OFFLINE),
        **_STUB_COMMON,
    }.items():
        f = bins / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    src = tmp_path / "src"
    imgs = tmp_path / "app-images"
    marker = tmp_path / "images-loaded"
    src.mkdir()

    if ships_platform:
        slop = src / "sysible-linux-operations-platform"
        (slop / ".git").mkdir(parents=True)
        (slop / "docker-compose.yml").write_text("services: {}\n")
        for app in ("controller", "slep", "connect"):
            d = slop / "apps" / app / "deploy"
            d.mkdir(parents=True)
            (d / "docker-compose.yml").write_text("services: {}\n")
        ctl = slop / "apps/controller/deploy/sysiblectl"
        ctl.write_text("#!/bin/sh\nexit 0\n")
        ctl.chmod(ctl.stat().st_mode | stat.S_IEXEC)
        # Independently settable: "source but no images" is a real state (a host
        # that cloned, or an ISO that shipped one half) and it must NOT be
        # mistaken for a complete airgapped install.
        if ships_images if ships_images is not None else True:
            imgs.mkdir()
            (imgs / "sysible-images.tar").write_bytes(b"\0" * 4096)

    for repo in also_cloned:
        d = src / repo
        (d / ".git").mkdir(parents=True)
        (d / "docker-compose.yml").write_text("services: {}\n")

    # The three absolute paths are rewritten, nothing else: the logic under test
    # is byte-for-byte the shipped logic. Each substitution is ASSERTED, so a
    # rename upstream fails this loudly instead of quietly testing nothing.
    script = INSTALLER.read_text()
    for const, value in (
        ("SRC_DIR=/opt/sysible-src", f"SRC_DIR={src}"),
        ("PREBUILT_IMAGES_DIR=/usr/share/sysible/app-images", f"PREBUILT_IMAGES_DIR={imgs}"),
        (
            "PLATFORM_IMAGES_MARKER=/var/lib/sysible/platform-images-loaded",
            f"PLATFORM_IMAGES_MARKER={marker}",
        ),
    ):
        assert script.count(const) == 1, (
            f"install-sysible no longer defines {const!r} exactly once, so this "
            f"test would run against the real /opt and /usr/share. Fix the test."
        )
        script = script.replace(const, value, 1)

    run = tmp_path / "install-sysible"
    run.write_text(script)

    env = dict(os.environ, PATH=f"{bins}:/usr/bin:/bin")
    return run, env, src


def _install(tmp_path, *args, network, ships_platform, also_cloned=(), ships_images=None):
    import subprocess

    run, env, src = _host(
        tmp_path,
        network=network,
        ships_platform=ships_platform,
        also_cloned=also_cloned,
        ships_images=ships_images,
    )
    p = subprocess.run(
        ["sh", str(run), "-y", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return p.stdout + p.stderr, src


# -- the bug: an airgapped host that ships everything must install -----------


def test_an_airgapped_host_that_ships_the_platform_does_not_check_the_network(tmp_path):
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=True)
    assert "Nothing has been installed" not in out, (
        "install-sysible aborted on a host that already holds the images and the "
        "source. This is the whole airgap requirement, and the path the installer "
        "menu takes on first boot.\n\n" + out
    )
    assert "nothing to download" in out


@pytest.mark.parametrize("product", ["controller", "slep", "connect", "slop"])
def test_every_app_is_started_on_an_airgapped_host(tmp_path, product):
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=True)
    assert f"SYSIBLECTL product={product}" in out, (
        f"{product} never got started on an airgapped host.\n\n" + out
    )


def test_nothing_is_cloned_when_the_source_is_already_vendored(tmp_path):
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=True)
    assert "(clone)" not in out, "a product was skipped because a clone failed\n\n" + out
    for app in ("controller", "slep", "connect"):
        assert f"using the {app} source vendored in the platform checkout" in out


def test_the_apps_resolve_to_the_vendored_source_not_an_empty_directory(tmp_path):
    out, src = _install(tmp_path, "slop", network=False, ships_platform=True)
    vendored = src / "sysible-linux-operations-platform/apps"
    for app in ("controller", "slep", "connect"):
        assert f"dir={vendored / app}" in out, (
            f"{app} was handed a path that is not the vendored checkout.\n\n" + out
        )


def test_a_failed_refresh_does_not_look_like_a_broken_install(tmp_path):
    """An unreachable remote is not an error when the code is already here."""
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=True)
    assert "could not reach the remote" in out
    assert not re.search(r"^fatal:", out, re.M), (
        "git's raw 'fatal: unable to access' reached the operator, which reads as "
        "a failed install on a host that is working exactly as designed.\n\n" + out
    )


# -- and the gate must STILL fire for the host that really is just offline ---


def test_a_host_with_nothing_local_still_gets_the_offline_message(tmp_path):
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=False)
    assert "checking the internet connection" in out
    assert "Nothing has been installed" in out, (
        "the connectivity gate was removed rather than made conditional: a host "
        "that genuinely needs the network now fails later and less clearly.\n\n" + out
    )


def test_an_online_host_still_clones(tmp_path):
    out, src = _install(tmp_path, "controller", network=True, ships_platform=False)
    assert "  online." in out
    assert f"CLONED {src / 'sysible-controller'}" in out, (
        "the normal online install stopped cloning.\n\n" + out
    )


def test_a_real_checkout_is_preferred_over_the_vendored_copy(tmp_path):
    """A host that cloned SLEP keeps using that clone, not SLOP's vendored one."""
    out, src = _install(
        tmp_path,
        "slep",
        network=True,
        ships_platform=True,
        also_cloned=("sysible-linux-engineering-platform",),
    )
    assert f"dir={src / 'sysible-linux-engineering-platform'}" in out, (
        "a standalone checkout was ignored in favour of the vendored copy, so "
        "`sysiblectl slep update` would stop tracking the repo the operator "
        "cloned.\n\n" + out
    )


def test_source_without_the_images_is_not_treated_as_airgap_ready(tmp_path):
    """Half a shipment is not a shipment.

    The source alone gets compose as far as reading its file and then straight
    to a registry for images this host does not have. Skipping the gate there
    trades one clear "no internet connection" for a wall of pull failures from
    inside a build, which is strictly worse than what it replaced.
    """
    out, _ = _install(
        tmp_path, "slop", network=False, ships_platform=True, ships_images=False
    )
    assert "checking the internet connection" in out, (
        "the network check was skipped on a host that has the source but NOT the "
        "images, so the install will fail later, inside compose, pulling images "
        "it cannot reach.\n\n" + out
    )
    assert "Nothing has been installed" in out


# --------------------------------------------------------------------------
# The first-boot unit that runs the installer.
#
# Sysible Server's unit has ordered after the image loader since the loader was
# added. Sysible Workstation uses a different mechanism entirely -- marker files
# and sysible-platform-installer.service -- and never got the same ordering, so
# the two editions raced differently on the first boot: Workstation could run
# the install before the images were in Docker's store, and compose would then
# go to a registry for images the machine was already carrying.
#
# Parameterised over whichever unit this repo ships so neither edition can be
# fixed alone again.
_APPS_UNITS = [
    p
    for p in (
        ROOT / "live-build/config/includes.chroot/usr/lib/systemd/system/sysible-apps-firstboot.service",
        ROOT / "packages/sysible-platform-apps/debian/sysible-platform-installer.service",
    )
    if p.exists()
]


def test_this_repo_ships_a_first_boot_apps_unit():
    assert _APPS_UNITS, (
        "no first-boot unit runs the apps the operator ticked in the installer, "
        "so ticking one does nothing at all"
    )


@pytest.mark.parametrize("unit", _APPS_UNITS, ids=lambda p: p.name)
def test_the_apps_unit_waits_for_the_images_to_be_loaded(unit):
    text = _code(unit)
    assert "After=sysible-platform-images.service" in text, (
        f"{unit.name} does not order after the image loader, so on first boot "
        f"compose can run before the shipped images are in Docker's store and "
        f"will try to pull them from a registry this host may not be able to "
        f"reach at all"
    )


@pytest.mark.parametrize("unit", _APPS_UNITS, ids=lambda p: p.name)
def test_the_apps_unit_does_not_require_the_network(unit):
    """Wants= is an optimisation; Requires= would block the airgapped install."""
    text = _code(unit)
    assert "Requires=network-online.target" not in text, (
        f"{unit.name} REQUIRES the network, so a host that ships the platform "
        f"images and source -- and needs no network to install them -- would "
        f"never run the install at all"
    )
    assert "Wants=network-online.target" in text, (
        f"{unit.name} should still WANT the network, so a host that does need to "
        f"clone and build waits for it rather than failing and retrying"
    )


def test_an_offline_install_does_not_report_problems_it_cannot_avoid(tmp_path):
    """A machine that did exactly the right thing must not say it failed.

    The optional software -- HashiCorp's tools, the AWS CLI, Obsidian where the
    edition offers it -- is downloaded from the vendors at install time. That is
    the whole reason the ISO cannot carry it, licensing included. So an airgapped
    host can never have it, and counting that as a failure ended a flawless
    offline install on

        Finished WITH PROBLEMS -- these did not come up: optional-software

    which is how a working machine gets read as a broken one, and is the
    complaint this whole path exists to answer.
    """
    out, _ = _install(tmp_path, "slop", network=False, ships_platform=True)
    assert "WITH PROBLEMS" not in out, (
        "an offline install still finished WITH PROBLEMS:\n\n" + out
    )
    assert "optional-software" not in out, (
        "the optional software was still counted as a failed component\n\n" + out
    )
    assert "it was SKIPPED. Nothing is wrong." in out, (
        "nothing told the operator why the optional software is absent, so its "
        "absence looks like a fault\n\n" + out
    )
