"""apt cannot use an ASCII-armoured keyring, and nothing said so.

The ISO build died with

    sysible-workstation : Depends: docker-ce but it is not installable

thousands of lines after the actual cause. live-build copies
config/archives/<name>.key.chroot VERBATIM to the chroot's
/etc/apt/trusted.gpg.d/<name>.gpg, and apt hands those files to gpgv.
gpgv cannot read ASCII armour:

    $ gpgv --keyring armoured.gpg sig msg
    gpgv: [don't know]: invalid packet (ctb=2d)      <- no "Good signature"
    $ gpgv --keyring dearmored.gpg sig msg
    gpgv: Good signature from ...

Docker publishes its key armoured. The build saved it as fetched, so apt
silently dropped the Docker archive as unsigned, docker-ce had no candidate,
and the dependency failure surfaced far from the cause with no hint in between.

The failure mode is what makes this worth a test: nothing errors. The key
downloads, the fingerprints verify, the repo line is written, and the archive
is quietly untrusted.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD = (REPO / "live-build" / "build.sh").read_text(encoding="utf-8")
GPG = shutil.which("gpg")


def _key_block():
    """The real archives block from build.sh, ready to run."""
    start = BUILD.index("DOCKER_KEY_FPRS=")
    end = BUILD.index("# --- expand the metapackage")
    return "set -e\nCODENAME=bookworm\n" + BUILD[start:end]


def test_the_key_is_dearmored_before_apt_sees_it():
    blk = _key_block()
    code = "\n".join(l for l in blk.split("\n") if not l.strip().startswith("#"))
    assert "--dearmor" in code, \
        "the key is handed to apt exactly as Docker serves it — armoured, which gpgv cannot read"


def test_a_missing_gpg_is_fatal_not_a_warning():
    """It used to warn and carry on. That skipped the fingerprint pinning AND
    left the key unusable, so carrying on could only produce a failed build."""
    blk = _key_block()
    assert "WARNING: gpg is not available" not in blk, \
        "a missing gpg still degrades silently"
    assert re.search(r"command -v gpg[^\n]*\|\|\s*\{", blk), \
        "nothing makes a missing gpg stop the build"


@pytest.mark.skipif(not GPG, reason="gpg is not on this machine")
def test_running_the_block_produces_a_keyring_gpgv_can_actually_use(tmp_path):
    """Executed, not read. A keyring that merely EXISTS is what shipped; the
    question is whether gpgv can verify a signature with it."""
    (tmp_path / "config" / "archives").mkdir(parents=True)
    (tmp_path / "block.sh").write_text(_key_block())
    r = subprocess.run(["sh", "block.sh"], cwd=tmp_path, capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0 and "could not fetch" in (r.stdout + r.stderr):
        pytest.skip("download.docker.com is not reachable from here")
    assert r.returncode == 0, r.stdout + r.stderr

    key = tmp_path / "config" / "archives" / "docker.key.chroot"
    assert key.exists(), "no key was produced"
    raw = key.read_bytes()
    assert not raw.startswith(b"-----"), \
        "the key is still ASCII-armoured — apt will drop the archive as unsigned"
    assert raw[0] == 0x99, \
        f"not a binary OpenPGP public-key packet (first byte 0x{raw[0]:02x})"

    # And the armoured intermediate must not be left behind in config/archives:
    # live-build would copy THAT into trusted.gpg.d too.
    leftovers = list((tmp_path / "config" / "archives").glob("*.asc"))
    assert not leftovers, f"an armoured key is still in config/archives: {leftovers}"


@pytest.mark.skipif(not GPG, reason="gpg is not on this machine")
def test_gpgv_reads_a_dearmored_keyring_and_not_an_armoured_one(tmp_path):
    """The premise the fix rests on, demonstrated rather than asserted, so a
    future reader does not have to take it on trust."""
    import os
    env = {**os.environ, "GNUPGHOME": str(tmp_path / "gnupg")}
    (tmp_path / "gnupg").mkdir(mode=0o700)
    subprocess.run([GPG, "--batch", "--passphrase", "", "--quick-gen-key",
                    "t@example.invalid", "default", "default", "never"],
                   env=env, capture_output=True, timeout=120, check=True)
    msg = tmp_path / "m.txt"; msg.write_text("x\n")
    subprocess.run([GPG, "--batch", "--yes", "-u", "t@example.invalid", "--output",
                    str(tmp_path / "m.sig"), "--detach-sign", str(msg)],
                   env=env, capture_output=True, timeout=120, check=True)
    armoured = subprocess.run([GPG, "--armor", "--export", "t@example.invalid"],
                              env=env, capture_output=True, timeout=60).stdout
    binary = subprocess.run([GPG, "--export", "t@example.invalid"],
                            env=env, capture_output=True, timeout=60).stdout
    (tmp_path / "a.gpg").write_bytes(armoured)
    (tmp_path / "b.gpg").write_bytes(binary)

    def verify(keyring):
        p = subprocess.run(["gpgv", "--keyring", str(tmp_path / keyring),
                            str(tmp_path / "m.sig"), str(msg)],
                           capture_output=True, text=True, timeout=60)
        return "Good signature" in (p.stdout + p.stderr)

    assert not verify("a.gpg"), \
        "an armoured keyring verified — the premise of this fix no longer holds"
    assert verify("b.gpg"), "a dearmored keyring failed to verify"
