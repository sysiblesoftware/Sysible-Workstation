"""A debootstrapped chroot has no CA store, and Docker's repo is https-only.

This is what made the ISO unbuildable, and it took three runs to see because
nothing along the way errored:

    W: No system certificates available. Try installing ca-certificates.
    W: Failed to fetch .../bookworm/InRelease  Certificate verification failed:
       The certificate is NOT trusted. The certificate issuer is unknown.
    ...
    sysible-server : Depends: docker-ce but it is not installable

Debian's own mirrors are plain http, so Docker's is the FIRST https source the
chroot ever sees. The repo line was written, the key was in place and correctly
paired -- and apt could not complete the handshake, so the index was never
fetched and docker-ce had no candidate. The dependency failure surfaced four
minutes and ninety thousand log lines after the cause.

A CA store has to be in the chroot BEFORE lb_chroot_archives runs its apt
update. Package lists and hooks both run later, so the build is staged: `lb
bootstrap` first, the bundle planted into the chroot it leaves behind, then `lb
build` -- which resumes at `lb chroot`, because every live-build stage guards
itself with a stamp under .build/.

The ordering IS the fix. Each of these tests was checked by breaking the
implementation and watching it fail.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD = (REPO / "live-build" / "build.sh").read_text(encoding="utf-8")


def _code():
    """build.sh with comments stripped.

    Every claim below is about what the script DOES. An earlier guard in this
    file was satisfied by a comment that merely named the package it was
    hunting for, and passed with the real line deleted.
    """
    return "\n".join(l for l in BUILD.split("\n") if not l.strip().startswith("#"))


def test_the_build_is_staged_so_there_is_a_chroot_to_trust_anything():
    """A single `lb build` leaves no point between debootstrap and the first apt
    update, which is the only window this can be fixed in."""
    code = _code()
    assert re.search(r"^\s*\$SUDO lb bootstrap\s*$", code, re.M), \
        "the build is not staged, so there is no moment at which the chroot " \
        "exists but its apt has not yet reached Docker's https repo"


def test_the_chroot_is_given_a_ca_store_before_the_rest_of_the_build():
    code = _code()
    plant = re.search(r"install -D[^\n]*ca-certificates\.crt", code)
    assert plant, "nothing installs a CA bundle into the chroot"
    boot = re.search(r"^\s*\$SUDO lb bootstrap\s*$", code, re.M)
    rest = re.search(r"^\s*\$SUDO lb build\s*$", code, re.M)
    assert rest, "the build never runs"
    assert boot.start() < plant.start() < rest.start(), (
        "the CA store must be planted AFTER lb bootstrap creates the chroot and "
        "BEFORE lb build runs the archives stage; order was "
        f"bootstrap@{boot.start()} plant@{plant.start()} build@{rest.start()}"
    )


def test_the_bundle_lands_where_apt_actually_reads_it():
    """/etc/ssl/certs/ca-certificates.crt is the system trust store apt's GnuTLS
    reads on Debian. Anywhere else is a file nothing consults."""
    assert re.search(
        r"install -D[^\n]*\s+chroot/etc/ssl/certs/ca-certificates\.crt",
        _code(), re.S,
    ), "the bundle is not installed to chroot/etc/ssl/certs/ca-certificates.crt"


def test_a_copy_that_did_not_land_stops_the_build_here():
    """The failure it prevents names a PACKAGE, four minutes downstream. This is
    the difference between a one-line error and a three-run investigation."""
    code = _code()
    assert re.search(r"cmp -s[^\n]*ca-certificates\.crt", code, re.S), \
        "nothing verifies the bundle actually reached the chroot"


def test_the_bootstrap_cache_is_made_harmless_not_deleted():
    """Two attempts at this went wrong in opposite directions.

    live-build keeps a copy of the bootstrapped chroot in cache/bootstrap, and
    two later stages read it. lb_bootstrap_cache's restore is, verbatim:

        if [ -d cache/bootstrap ]; then rm -rf chroot; cp -a cache/bootstrap chroot

    so the cached copy -- taken before the bundle was planted -- gets put back
    over it. The first attempt lost the CA store that way, and failed at the
    same four-minute mark with the same docker-ce message as no fix at all.

    The second attempt removed the cache to stop that, and broke the OTHER
    reader: lb_installer_chroot copies cache/bootstrap to build the Debian
    Installer's chroot, so Server died with

        cp: cannot stat 'cache/bootstrap': No such file or directory

    AFTER the chroot stage had completed and docker-ce had installed. It showed
    up only on Server, because Workstation installs with Calamares and has no
    installer_chroot stage to break.

    So the cache must SURVIVE and must carry the same CA store. Verified by
    running `lb bootstrap_cache restore` three ways: with the cache deleted
    (installer_chroot's input gone), with the cache planted and the stagefile
    present (restore skipped, both copies trusted), and with the stagefile
    absent so the restore really runs (chroot still trusted -- the restore is
    harmless now rather than merely blocked).
    """
    code = _code()
    assert "rm -rf cache" not in code, (
        "deleting the bootstrap cache breaks lb_installer_chroot, which copies "
        "cache/bootstrap to build the Debian Installer's chroot")

    plant_cache = re.search(
        r"install -D[^\n]*\n?[^\n]*cache/bootstrap/etc/ssl/certs/ca-certificates\.crt",
        code)
    assert plant_cache, \
        "the cached bootstrap chroot gets no CA store, so a restore would " \
        "replace the planted one with an un-trusted copy"

    stamp = re.search(r"^\s*\$SUDO touch \.build/bootstrap_cache\.restore\s*$", code, re.M)
    assert stamp, \
        "the restore stagefile is not pre-created, so Check_stagefile would not skip it"

    plant = re.search(r"install -D[^\n]*\n?[^\n]*chroot/etc/ssl/certs/ca-certificates\.crt", code)
    build = re.search(r"^\s*\$SUDO lb build\s*$", code, re.M)
    for what, m in (("the cached copy's CA store", plant_cache), ("restore stagefile", stamp)):
        assert plant.start() < m.start() < build.start(), (
            f"{what} must be set up after the chroot is bootstrapped and before "
            f"lb build; plant@{plant.start()} {what}@{m.start()} build@{build.start()}")


def test_lb_build_is_not_left_to_debootstrap_again():
    """If the bootstrap stamp were missing, `lb build` would debootstrap from
    scratch over the top of the planted store -- the other way this comes apart,
    and indistinguishable from it in the log."""
    assert re.search(r"\[ -f \.build/bootstrap \]", _code()), \
        "nothing checks the bootstrap stage was actually stamped as done"


def test_the_shipped_image_gets_a_store_a_package_owns():
    """The planted copy belongs to no package: update-ca-certificates could
    never regenerate it, and the hash symlinks that directory-based verifiers
    read would not exist. Nothing in Docker's repo depends on ca-certificates
    (checked across bookworm/stable, docker-ce 23.0.0 to 29.9.3), so it has to
    be asked for explicitly."""
    code = _code()
    assert re.search(
        r"ca-certificates\s*>\s*config/package-lists/[^\n]*\.list\.chroot", code
    ), "the image would ship an unowned CA bundle that nothing can maintain"


def test_it_does_not_go_back_to_asserting_live_builds_private_files():
    """This is a regression test for a fix that broke the build by itself.

    The previous attempt exported LB_BOOTSTRAP_INCLUDE and then hard-failed if
    the value did not appear in config/bootstrap. That was verified against
    live-build 3.0 from Ubuntu, which is a different program from the 2023
    live-build the image is built with: the file is not the same. The guard
    exited one minute in, before a chroot existed to look at.

    LB_BOOTSTRAP_INCLUDE may still be exported -- a live-build that honours it
    fixes this a stage earlier for free -- but nothing may DEPEND on it.
    """
    code = _code()
    assert "config/bootstrap" not in code, \
        "the build again asserts the contents of a live-build-internal file " \
        "whose name and format differ between live-build versions"


def test_the_https_repo_this_is_all_for_is_still_https():
    """If Docker ever served plain http this would be unnecessary -- and if
    another https vendor repo is added, the same fix already covers it.

    http:// is not a way out: download.docker.com answers port 80 with a 301 to
    https, which apt follows into the same handshake.
    """
    assert "https://download.docker.com" in BUILD
