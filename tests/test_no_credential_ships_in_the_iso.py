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

Rule 1 was first met by STRIPPING the header out of the checkout before the
build. That worked, but it defended a thing that did not need to exist: the ISO
no longer ships a source checkout at all. install-sysible clones the source, as
it always did on any other machine, so there is no .git in the image to carry a
credential and nothing to strip. A guarantee you get by not having the thing is
better than one you get by remembering to clean it.

The checkout was also stale from the moment it was built, so every host
installed from an ISO started life behind — and `sysiblectl update` existed to
fix that, which is precisely the command the token broke.

So the assertion is now the absence: no step may put anything under
includes.chroot/opt/sysible-src, and the build fails if one appears.
"""
import pathlib
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ISO_YML = ROOT / ".github/workflows/iso.yml"
CONFIRM = "Confirm the images arrived, and that no checkout did"
SRC_PATH = "includes.chroot/opt/sysible-src"


def _steps():
    doc = yaml.safe_load(ISO_YML.read_text())
    return doc["jobs"]["iso"]["steps"]


def _names():
    return [s.get("name", "") for s in _steps()]


def test_no_step_puts_a_source_checkout_into_the_image():
    """The structural fix. A checkout that is never created cannot carry a
    token, go stale, or need a cleanup step that runs on time."""
    offenders = []
    for s in _steps():
        blob = " ".join(str(v) for v in s.values())
        if SRC_PATH in blob and s.get("name") != CONFIRM:
            offenders.append(s.get("name", "(unnamed)"))
    assert not offenders, (
        "these steps write into %s again: %s.\n"
        "A checkout baked into the ISO is how v1.0.10 shipped a live GitHub "
        "token, and how every installed host started out stale. install-sysible "
        "clones the source." % (SRC_PATH, offenders))


def test_the_build_refuses_to_ship_one_if_a_step_ever_adds_it_back():
    """Belt to the braces above: the guard must be FATAL, not a warning in a
    35-minute log, and it must trigger on a directory that actually exists."""
    body = next(s for s in _steps() if s.get("name") == CONFIRM)["run"]
    img = tmp_img = None
    import subprocess as _sp
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        img = root / "live-build/config/includes.chroot/usr/share/sysible/app-images"
        img.mkdir(parents=True)
        (img / "sysible-images.tar").write_text("not empty")
        script = root / "step.sh"
        script.write_text(body)

        # Images present, no checkout: the step passes.
        r = _sp.run(["sh", str(script)], cwd=root, capture_output=True, text=True,
                    timeout=60)
        assert r.returncode == 0, (
            "the step failed on a correct tree:\n%s%s" % (r.stdout, r.stderr))

        # A checkout reappears: the step must FAIL.
        d = root / "live-build/config/includes.chroot/opt/sysible-src/x"
        d.mkdir(parents=True)
        r = _sp.run(["sh", str(script)], cwd=root, capture_output=True, text=True,
                    timeout=60)
        assert r.returncode != 0, (
            "a source checkout was present and the step still exited 0 — the "
            "build would ship it")


def test_the_images_are_still_shipped_and_still_required():
    """The counterweight. Dropping the SOURCE must not quietly drop the images
    too: they are what stops a first install pulling and building everything."""
    body = next(s for s in _steps() if s.get("name") == CONFIRM)["run"]
    assert "sysible-images.tar" in body
    assert "exit 1" in body, "a missing image archive does not stop the build"
    assert any("download-artifact" in str(s.get("uses", "")) for s in _steps()), (
        "nothing collects the prebuilt images any more")


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
