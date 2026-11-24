"""A debootstrapped chroot has no CA store, and Docker's repo is https-only.

This is what made the ISO unbuildable, and it took three runs to see because
nothing along the way errored:

    W: No system certificates available. Try installing ca-certificates.
    W: Failed to fetch .../bookworm/InRelease  Certificate verification failed:
       The certificate is NOT trusted. The certificate issuer is unknown.
    ...
    sysible-workstation : Depends: docker-ce but it is not installable

Debian's own mirrors are plain http, so Docker's is the FIRST https source the
chroot ever sees. The repo line was written, the key was in place and correctly
paired -- and apt could not complete the handshake, so the index was never
fetched and docker-ce had no candidate. The dependency failure surfaced four
minutes and ninety thousand log lines after the cause.

ca-certificates has to be in the chroot BEFORE lb_chroot_archives runs its apt
update. Package lists and hooks both run later; the only stage early enough is
the debootstrap itself.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD = (REPO / "live-build" / "build.sh").read_text(encoding="utf-8")


def _code():
    return "\n".join(l for l in BUILD.split("\n") if not l.strip().startswith("#"))


def test_ca_certificates_are_bootstrapped_into_the_chroot():
    code = _code()
    assert "LB_BOOTSTRAP_INCLUDE" in code, \
        "nothing puts a CA store in the chroot, so any https repo fails its handshake"
    m = re.search(r"export LB_BOOTSTRAP_INCLUDE=[^\n]*", code)
    assert m and "ca-certificates" in m.group(0), \
        f"the bootstrap include does not carry ca-certificates: {m.group(0) if m else None}"


def test_it_is_set_before_lb_config_reads_it():
    """lb config snapshots the environment into config/bootstrap. Exporting it
    afterwards would be silently ignored and cost a whole build to notice."""
    code = _code()
    assert code.index("export LB_BOOTSTRAP_INCLUDE") < code.index("\nlb config"), \
        "LB_BOOTSTRAP_INCLUDE is exported after lb config has already run"


def test_it_appends_rather_than_clobbers():
    """A future caller setting LB_BOOTSTRAP_INCLUDE must not lose ca-certificates,
    and must not lose their own value either."""
    m = re.search(r"export LB_BOOTSTRAP_INCLUDE=([^\n]*)", _code())
    assert "${LB_BOOTSTRAP_INCLUDE" in m.group(1), \
        f"an existing bootstrap include would be discarded: {m.group(1)}"


def test_a_dropped_value_stops_the_build_rather_than_failing_later():
    """The failure it prevents names a PACKAGE, not a certificate, four minutes
    downstream. Checking here is the difference between a one-line error and a
    three-run investigation."""
    code = _code()
    assert re.search(r'grep -q "ca-certificates" config/bootstrap', code), \
        "nothing verifies the value actually reached config/bootstrap"


def test_the_https_repo_this_is_for_is_still_https():
    """If Docker ever served plain http this guard would be pointless -- and if
    another https vendor repo is added, it is covered by the same fix."""
    assert "https://download.docker.com" in BUILD
