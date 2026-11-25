"""Setting SYSIBLE_VERSION_SUFFIX is not the same as applying it.

Sysible Server shipped every package UNSTAMPED for the entire life of the
version-suffix scheme, and nothing noticed, because the existing tests check
that publish.yml *sets* the suffix and nothing checked that anything *reads*
it. The consumer lives in scripts/build-all.sh, and Server's copy of that file
simply did not have it. The release log said

    SYSIBLE_VERSION_SUFFIX: +ci20261125171311.r45656415089.g98cc552
    [+] sysible-cli_0.3.2_all added          <- no suffix anywhere

so each publish rewrote the SAME immutable pool path with different bytes,
which is the "File has unexpected size" apt failure the suffix exists to
prevent. Workstation's copy had the stamping and was fine; the two files had
drifted.

A test that greps for the env var would have passed throughout. So this one
RUNS the stamping and reads the version back out with dpkg-parsechangelog.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_ALL = ROOT / "scripts/build-all.sh"
TEXT = BUILD_ALL.read_text(encoding="utf-8")

SUFFIX = "+ci20261125999999.r424242.gfeedface"

needs_dpkg = pytest.mark.skipif(
    shutil.which("dpkg-parsechangelog") is None,
    reason="dpkg-dev not available",
)


def _code():
    """build-all.sh with comments stripped.

    Three guards earlier in this project passed by finding their subject in a
    COMMENT rather than in code. Strip them before asserting anything about
    what the script does.
    """
    out = []
    for line in TEXT.splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line)
        if stripped.strip():
            out.append(stripped)
    return "\n".join(out)


def _stamp_fn():
    """The stamp_changelog definition, lifted out so it can be executed."""
    lines = TEXT.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("stamp_changelog() {")), None)
    assert start is not None, (
        "scripts/build-all.sh defines no stamp_changelog function, so "
        "SYSIBLE_VERSION_SUFFIX cannot be applied to anything. This is exactly "
        "how Sysible Server published unstamped packages onto immutable pool "
        "paths."
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def _changelog(version, source="sysible-test"):
    d = Path(tempfile.mkdtemp())
    cl = d / "changelog"
    cl.write_text(
        f"{source} ({version}) sysible; urgency=medium\n\n"
        "  * Initial.\n\n"
        " -- Sysible <maintainers@sysible.com>  Mon, 24 Nov 2026 12:00:00 +0000\n",
        encoding="utf-8",
    )
    return cl


def _run_stamp(cl, suffix, times=1):
    body = _stamp_fn()
    script = f'SUFFIX="{suffix}"\n{body}\n' + "".join(
        f'stamp_changelog "{cl}"\n' for _ in range(times))
    r = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, f"stamp_changelog failed: {r.stderr}"
    return r


def _version(cl):
    r = subprocess.run(["dpkg-parsechangelog", "-l", str(cl), "-S", "Version"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


@needs_dpkg
def test_the_suffix_reaches_the_package_version():
    """The regression. Run it and read the version back."""
    cl = _changelog("0.3.2")
    _run_stamp(cl, SUFFIX)
    assert _version(cl) == "0.3.2" + SUFFIX, (
        "the version suffix was set but never applied — the published .deb "
        "would land on the same pool path as the previous build"
    )


@needs_dpkg
def test_stamping_twice_in_one_run_stamps_once():
    """build-all.sh may reach the same changelog twice; the version must not
    grow a second suffix (which would also break version ordering)."""
    cl = _changelog("0.3.2")
    _run_stamp(cl, SUFFIX, times=3)
    assert _version(cl) == "0.3.2" + SUFFIX


@needs_dpkg
def test_a_local_build_keeps_its_clean_version():
    """No suffix set => developer .debs keep the changelog version untouched."""
    cl = _changelog("0.3.2")
    _run_stamp(cl, "")
    assert _version(cl) == "0.3.2"


@needs_dpkg
def test_the_stamped_version_is_an_upgrade_over_the_unstamped_one():
    """Machines are sitting on the unstamped 0.3.2 right now. If the stamped
    build did not sort above it, apt would see no upgrade and the repair would
    never reach them."""
    assert subprocess.run(
        ["dpkg", "--compare-versions", "0.3.2" + SUFFIX, "gt", "0.3.2"]
    ).returncode == 0, f"0.3.2{SUFFIX} does not sort above 0.3.2"


def test_every_built_package_is_stamped_before_it_is_built():
    """Having the function is not enough; it has to be called in the loop, and
    called BEFORE dpkg-buildpackage reads the changelog."""
    code = _code()
    stamp = code.find('stamp_changelog "${pkg}debian/changelog"')
    assert stamp != -1, (
        "the package loop never calls stamp_changelog, so no package in "
        "packages/ gets a unique version"
    )
    build = code.find("dpkg-buildpackage", stamp)
    assert build != -1 and stamp < build, (
        "stamp_changelog runs after dpkg-buildpackage — the .deb is built from "
        "the unstamped version"
    )


def test_systerm_is_stamped_too():
    """systerm is cloned from its own repo mid-build and was published to the
    same immutable pool, so it needs the same treatment."""
    code = _code()
    assert "stamp_changelog /tmp/systerm-src/debian/changelog" in code, (
        "systerm is built from a fresh clone and never stamped, so its pool "
        "path repeats on every publish"
    )


def test_the_workflow_still_exports_what_the_script_reads():
    """The two halves live in different files; this is the seam that drifted."""
    wf = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "SYSIBLE_VERSION_SUFFIX" in wf, "publish.yml no longer sets the suffix"
    assert "SYSIBLE_VERSION_SUFFIX" in _code(), (
        "build-all.sh no longer reads SYSIBLE_VERSION_SUFFIX — the workflow "
        "would export it into a void, which is the original bug"
    )
