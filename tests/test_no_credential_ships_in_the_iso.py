"""No credential may ship inside an ISO, and no git call may stop for one.

Found by extracting /opt/sysible-src/sysible-linux-operations-platform/.git/config
out of the RELEASED v1.0.10 ISO. It contained

    [http "https://github.com/"]
        extraheader = AUTHORIZATION: basic <base64 x-access-token:ghs_...>

which is how actions/checkout authenticates. Its post-job step removes it again,
but the ordering in run #114 was:

    13:08:35            "Ship the platform source"  -> header written
    13:08:35-13:31:51   "Build the ISO"             -> squashfs built WITH it
    13:35:02            post-job cleanup            -> removed, 3.5 min too late

So every published ISO carried a live 60-minute GitHub Actions token, and every
git call on an installed machine sent the expired header, got 401 from GitHub,
and stopped at `Username for 'https://github.com':` -- on a PUBLIC repo, because
git never falls back to anonymous once an Authorization header is configured.

Two separate rules, because either alone still leaves a broken machine:
  1. nothing with a credential in it goes into the image, and
  2. no git call can block waiting for one.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ISO_YML = ROOT / ".github/workflows/iso.yml"
STRIP = "Strip CI credentials from the shipped checkout"


def _steps():
    doc = yaml.safe_load(ISO_YML.read_text())
    return doc["jobs"]["iso"]["steps"]


def _names():
    return [s.get("name", "") for s in _steps()]


def test_the_shipped_checkout_is_stripped_of_credentials():
    assert STRIP in _names(), (
        "iso.yml no longer strips actions/checkout's Authorization header from the "
        "checkout it ships. That header is written into .git/config by every "
        "checkout and is only removed by a post-job step that runs AFTER the "
        "squashfs is built -- so without this the token goes into the image.")


def test_it_runs_after_the_checkout_and_before_the_build():
    names = _names()
    i_strip = names.index(STRIP)
    i_ship = names.index("Ship the platform source")
    i_build = names.index("Build the ISO")
    assert i_ship < i_strip < i_build, (
        f"order is ship={i_ship} strip={i_strip} build={i_build}. Stripping before "
        f"the checkout strips nothing; stripping after the build is exactly the "
        f"3.5-minutes-too-late ordering that shipped the token in v1.0.10.")


def test_it_fails_the_build_rather_than_shipping_one(tmp_path):
    """The check has to be fatal. A warning in a 35-minute log is not a gate."""
    body = next(s for s in _steps() if s.get("name") == STRIP)["run"]
    d = tmp_path / "live-build/config/includes.chroot/opt/sysible-src/sysible-linux-operations-platform"
    (d / ".git").mkdir(parents=True)
    (d / ".git/config").write_text(
        '[remote "origin"]\n\turl = https://github.com/sysiblesoftware/x\n'
        '[http "https://github.com/"]\n\textraheader = AUTHORIZATION: basic Zm9v\n')
    script = tmp_path / "step.sh"
    script.write_text(body)
    # clean run: the step strips it and succeeds
    r = subprocess.run(["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"the step failed on a config it should have fixed:\n{r.stdout}{r.stderr}"
    assert "extraheader" not in (d / ".git/config").read_text(), "the credential survived the strip"

    # and if the removal cannot do its job, the step must EXIT NON-ZERO
    (d / ".git/config").write_text(
        '[http "https://github.com/"]\n\textraheader = AUTHORIZATION: basic Zm9v\n')
    neutered = re.sub(r"^\s*git config --file .*$", "          :", body, flags=re.M)
    assert "remove-section" not in neutered, "mutation did not apply"
    script.write_text(neutered)
    r = subprocess.run(["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, (
        "with a credential still present the step exited 0 -- the build would ship it")


def test_no_network_git_call_can_stop_for_a_credential():
    """`>/dev/null 2>&1` does not catch git's prompt: it goes to /dev/tty. The
    only thing that stops it is GIT_TERMINAL_PROMPT=0 (plus an empty askpass, or
    a desktop session pops a GUI dialog instead -- the same hang with a window
    around it)."""
    installer = ROOT / "packages/sysible-cli/install-sysible"
    if not installer.is_file():
        pytest.skip("no install-sysible in this repo")
    code = "\n".join(l for l in installer.read_text().splitlines()
                     if not l.lstrip().startswith("#"))
    assert "GIT_TERMINAL_PROMPT=0" in code, "install-sysible can still be stopped by a credential prompt"
    bare = re.findall(r"(?<![_\w])git\s+(?:-C\s+\S+\s+)?(pull|fetch|clone|ls-remote)\b", code)
    assert not bare, (
        f"these git calls bypass the non-prompting wrapper and can hang an "
        f"install forever: {bare}")
