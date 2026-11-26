"""The tools the product pages promise must be guaranteed, not hoped for.

"kubectl, Helm, k9s, OpenTofu = hard deps i want these and docker compose and
ALL SLOP dependencies installed on install."

They cannot all be apt dependencies, and that is the point of this file. helm
and opentofu are installed from their vendors' official binaries because their
apt repos misbehave in a fresh chroot; k9s comes from a GitHub release. There is
no package for apt to depend on, so `Depends: helm` would fail the build with
"no installation candidate" -- and the `Recommends` they sat in was satisfied by
nothing at all, because apt skips an unsatisfiable Recommends in silence.

So the guarantee lives in two places instead, and both are checked here:

  1. The vendor hook must INSTALL them or fail the build. k9s was explicitly
     best-effort ("k9s is optional"), and on Workstation its guard read
     `[ -z "$k9s_sum" ] || [ sums match ]` -- which installed an UNVERIFIED
     binary whenever the checksum file could not be fetched, directly below a
     comment claiming it would not.
  2. 9500-sysible-verify must assert they are on PATH in the finished image, so
     the ISO cannot be published without them.

Plus openssl, which SLOP's installer needs to mint its five 64-hex secrets and
which was only a Recommends -- dropped silently by --no-install-recommends.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "live-build/config/hooks/normal/8000-sysible-vendor-tools.hook.chroot"
VERIFY = ROOT / "live-build/config/hooks/normal/9500-sysible-verify.hook.chroot"
CONTROL = ROOT / "packages/sysible-meta/debian/control"

def _code(path):
    """Shell source with comment lines removed.

    Written because the first version of the checks below matched the comment
    that DESCRIBES the bug -- the block explaining `[ -z "$k9s_sum" ] ||` is
    itself a line containing `[ -z "$k9s_sum" ] ||`. A guard that reads prose
    as if it were code passes and fails for the wrong reasons.
    """
    return "\n".join(l for l in path.read_text().splitlines()
                     if not l.lstrip().startswith("#"))


PROMISED = ["docker", "kubectl", "helm", "k9s", "tofu", "ansible", "podman",
            "git", "curl", "openssl", "nft"]


def _stanza():
    s = CONTROL.read_text()
    m = re.search(r"^Package: sysible-(?:server|workstation)$", s, re.M)
    assert m, "no sysible-server/workstation stanza"
    nxt = s.find("\nPackage: ", m.end())
    return s[m.start():nxt if nxt != -1 else len(s)]


def _field(name):
    m = re.search(rf"^{name}:(.*?)(?=^[A-Z][A-Za-z-]*:|\Z)", _stanza(), re.S | re.M)
    if not m:
        return []
    body = "\n".join(l for l in m.group(1).splitlines() if not l.strip().startswith("#"))
    return [p.strip().split()[0] for p in body.split(",")
            if p.strip() and not p.strip().startswith("${")]


# ---- openssl: a SLOP prerequisite, so a hard dependency --------------------
def test_openssl_is_a_hard_dependency():
    assert "openssl" in _field("Depends"), (
        "openssl is not a Depends. SLOP's installer mints its SSO, updater, "
        "Baseline and Flashback secrets with `openssl rand -hex 32`, and "
        "`install-sysible slop` is one of the questions the installer asks.")


def test_openssl_is_not_merely_recommended():
    assert "openssl" not in _field("Recommends"), \
        "openssl is in both lists — Recommends is dropped by --no-install-recommends"


@pytest.mark.parametrize("pkg", ["docker-ce", "docker-compose-plugin", "containerd.io",
                                 "podman", "ansible", "nftables", "git", "curl"])
def test_the_real_packages_are_hard_dependencies(pkg):
    assert pkg in _field("Depends"), f"{pkg} is not a hard dependency"


# ---- k9s: required, and never installed unverified -------------------------
def test_k9s_is_no_longer_optional():
    s = VENDOR.read_text()
    assert "k9s is optional" not in s, "the hook still calls k9s optional"
    assert "k9s (best-effort)" not in s, "the hook still treats k9s as best-effort"


def test_a_missing_k9s_checksum_does_not_install_it_anyway():
    """The Workstation bug: `[ -z "$k9s_sum" ] ||` short-circuited to install."""
    s = _code(VENDOR)
    assert not re.search(r'\[\s*-z\s*"\$k9s_sum"\s*\]\s*\|\|', s), (
        "a missing checksum still short-circuits into the install branch — "
        "that installs an unverified binary into /usr/local/bin")
    assert re.search(r'\[\s*-n\s*"\$k9s_sum"\s*\]', s), \
        "nothing requires a checksum to have been found at all"


@pytest.mark.parametrize("failure", [
    "could not download k9s",
    "refusing to install it unverified",
    "checksum mismatch",
])
def test_every_k9s_failure_path_stops_the_build(failure):
    s = _code(VENDOR)
    m = re.search(re.escape(failure) + r'[^\n]*"\s*>&2;\s*exit 1', s)
    assert m, f"the {failure!r} path does not exit 1 — the ISO would ship without k9s"


# ---- the finished image is checked ----------------------------------------
@pytest.mark.parametrize("tool", PROMISED)
def test_the_build_verifies_the_tool_is_present(tool):
    s = VERIFY.read_text()
    m = re.search(r"for _t in ([^;]*?); do", s, re.S)
    assert m, "9500-sysible-verify has no promised-tools loop"
    listed = m.group(1).replace("\\\n", " ").split()
    assert tool in listed, (
        f"{tool} is not asserted by the build. The product pages say it is "
        f"included; nothing checks that it is.")


def test_the_tool_check_fails_the_build():
    s = VERIFY.read_text()
    m = re.search(r"for _t in .*?done", s, re.S)
    assert m and "fail " in m.group(0), \
        "the promised-tools loop does not call fail(), so it cannot stop the build"


def test_compose_is_checked_without_needing_a_daemon():
    s = _code(VERIFY)
    assert "docker-compose-plugin" in s, "the compose plugin package is not checked"
    assert "cli-plugins/docker-compose" in s, "the compose plugin binary path is not checked"
    assert "docker compose version" not in s, (
        "running `docker compose version` in a build chroot is not a safe probe — "
        "there is no daemon there")
