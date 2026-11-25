"""`sysiblectl first-run` has to exist on a host that has only just booted.

The unified CLI lives in the Controller checkout and SLOP's installer links it
into /usr/local/bin. So on a freshly installed Sysible host, with nothing cloned
yet, `sysiblectl` was not a command at all -- and `sysiblectl first-run`, which
is documented as THE first thing to run, could not be the first thing to run.
The one command a new box needs cannot be one that appears only after the box
has been set up.

So the OS package ships a bootstrap shim. It installs to /usr/sbin, while the
real CLI installs to /usr/local/bin, which comes FIRST in root's PATH (ENV_SUPATH
in /etc/login.defs) -- so once the platform is installed the real one wins and
this is never consulted again.

Everything here RUNS the shim under dash, because /bin/sh is dash on Debian and
both bugs this file guards against are constructs that fail only there, or fail
everywhere while looking fine.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIM = ROOT / "packages" / "sysible-cli" / "sysiblectl"
INSTALL_LIST = ROOT / "packages" / "sysible-cli" / "debian" / "sysible-cli.install"
SH = shutil.which("dash") or shutil.which("sh")


@pytest.fixture()
def host(tmp_path):
    sbin, localbin, slop, cwd = (tmp_path / d for d in ("sbin", "localbin", "slop", "cwd"))
    for d in (sbin, localbin, slop / "gateway", cwd):
        d.mkdir(parents=True)
    shutil.copy(SHIM, sbin / "sysiblectl")
    for p, body in ((sbin / "install-sysible", 'echo "INSTALL-SYSIBLE: $*"'),
                    (localbin / "sysiblectl", 'echo "REAL-CLI: $*"'),
                    (slop / "install.sh", 'echo "INSTALL.SH: $*"')):
        p.write_text(f"#!/bin/sh\n{body}\n")
        os.chmod(p, 0o755)
    os.chmod(sbin / "sysiblectl", 0o755)
    (slop / "gateway" / "Caddyfile").touch()
    real_bin = str(pathlib.Path(shutil.which("grep")).parent)

    class Host:
        slop_dir = slop

        def run(self, *args, installed=False, slop_checkout="", have_installer=True):
            path = f"{sbin}:{real_bin}:/usr/bin:/bin"
            if installed:
                path = f"{localbin}:{path}"
            moved = None
            if not have_installer:
                moved = sbin / "install-sysible"
                moved.rename(tmp_path / "is.bak")
            try:
                return subprocess.run(
                    [SH, str(sbin / "sysiblectl"), *args], cwd=cwd, capture_output=True,
                    text=True, timeout=60,
                    env={**os.environ, "PATH": path, "HOME": str(cwd),
                         "SYSIBLE_SLOP_DIR": str(slop_checkout)})
            finally:
                if moved:
                    (tmp_path / "is.bak").rename(moved)

    return Host()


def test_the_package_puts_it_on_path():
    assert SHIM.is_file(), "the OS ships no sysiblectl at all"
    assert "sysiblectl usr/sbin" in INSTALL_LIST.read_text(), \
        "sysiblectl is not installed by the package, so it is not on PATH"


def test_the_real_cli_still_wins_once_the_platform_is_installed():
    """/usr/sbin on purpose: /usr/local/bin, where the real CLI goes, precedes
    it in root's PATH. Shipping this to /usr/local/bin would shadow the real
    CLI permanently."""
    assert "usr/sbin" in INSTALL_LIST.read_text()
    assert "usr/local/bin" not in INSTALL_LIST.read_text()


def test_first_run_works_on_a_host_with_nothing_installed(host):
    r = host.run("first-run")
    assert r.returncode == 0, r.stderr
    assert "INSTALL-SYSIBLE: -y slop" in r.stdout, r.stdout


def test_the_bare_command_bootstraps_too(host):
    """And does not die on `shift` with no arguments, which in dash is a special
    builtin error that exits the shell even with `|| true` after it."""
    r = host.run()
    assert r.returncode == 0, f"rc={r.returncode} {r.stdout!r} {r.stderr!r}"
    assert "INSTALL-SYSIBLE: -y slop" in r.stdout


def test_a_checkout_is_used_in_preference_to_fetching(host):
    r = host.run("first-run", slop_checkout=host.slop_dir)
    assert r.returncode == 0, r.stderr
    assert "INSTALL.SH: all --integrated" in r.stdout, r.stdout


def test_a_management_verb_hands_off_once_the_real_cli_exists(host):
    """The bug this replaced: the lookup used `command -v -a`, which exists in
    neither dash nor bash, so with `|| true` after it the result was always
    empty and the hand-off never happened -- reported as "not installed" on a
    host where it plainly was."""
    for args in (("status",), ("update", "all"), ("slep", "logs")):
        r = host.run(*args, installed=True)
        assert r.returncode == 0, f"{args}: {r.stderr}"
        assert f"REAL-CLI: {' '.join(args)}" in r.stdout, f"{args}: {r.stdout}"


def test_a_management_verb_says_what_to_do_when_nothing_is_installed(host):
    r = host.run("status")
    assert r.returncode != 0
    assert "first-run" in (r.stdout + r.stderr)


def test_first_run_still_bootstraps_even_with_the_real_cli_present(host):
    """first-run is OURS; it must not be forwarded to a CLI whose `install`
    verb only makes a symlink."""
    r = host.run("first-run", installed=True)
    assert "INSTALL-SYSIBLE: -y slop" in r.stdout, r.stdout


def test_a_missing_installer_is_reported_not_ignored(host):
    r = host.run("first-run", have_installer=False)
    assert r.returncode != 0
    assert "install-sysible" in (r.stdout + r.stderr)


def _code_only(path):
    """Comments stripped. The shim's own comment NAMES the broken option in
    order to explain why it is not used, so a plain substring search over the
    whole file reads the prose and fails on correct code -- which is exactly
    what it did the first time."""
    return "\n".join(l for l in path.read_text().splitlines()
                      if not l.lstrip().startswith("#"))


def test_it_does_not_use_an_option_that_no_sh_has():
    """`command -v -a` is a zsh/ksh spelling. Both dash and bash reject it, so
    with `|| true` after it the lookup is always empty and the hand-off never
    happens."""
    assert "command -v -a" not in _code_only(SHIM), \
        "command -v -a fails in dash AND bash; the lookup would always be empty"


def test_no_unguarded_shift_anywhere_in_it():
    for line in _code_only(SHIM).splitlines():
        stripped = line.strip()
        if stripped.startswith("shift") and "$#" not in line:
            pytest.fail(f"unguarded shift exits the script in dash: {line!r}")


def test_two_shims_that_can_see_each_other_do_not_loop(host, tmp_path):
    """Each shim skips ITSELF, which is not enough: two of them on PATH would
    exec each other forever. A sentinel limits the chain to one hop."""
    assert "SYSIBLE_CTL_HANDOFF" in SHIM.read_text(), "no loop guard"
    other = tmp_path / "other"
    other.mkdir()
    shutil.copy(SHIM, other / "sysiblectl")
    os.chmod(other / "sysiblectl", 0o755)
    real_bin = str(pathlib.Path(shutil.which("grep")).parent)
    r = subprocess.run(
        [SH, str(other / "sysiblectl"), "status"], capture_output=True, text=True,
        timeout=30,
        env={**os.environ,
             "PATH": f"{other}:{tmp_path / 'sbin'}:{real_bin}:/usr/bin:/bin",
             "HOME": str(tmp_path)})
    assert r.returncode != 124, "it hung — the shims are execing each other"
    assert "first-run" in (r.stdout + r.stderr)
