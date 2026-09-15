"""Shared sandbox for exercising the workstation's shell helpers for real.

These scripts run on a freshly installed workstation, where the failure modes are
environmental — no network, a Docker daemon that has not started, a package that
is not there. None of that is reachable from a unit test of anything smaller, so
the tests here run the REAL script with a PATH that contains only fakes, and read
what it did from a call log.

They also run it under a pty where the point is what an operator SEES: the
installer is launched from a Terminal=true .desktop, so whether the window stays
open long enough to read an error is a behaviour, not a detail.
"""
import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHROOT = REPO / "live-build" / "config" / "includes.chroot"
BIN = CHROOT / "usr" / "local" / "bin"
UNITS = CHROOT / "usr" / "lib" / "systemd" / "system"

# Fakes stand in for the whole outside world. Each logs its argv, and reads an
# env var for the condition under test — so a test says "no network" by setting
# FAKE_ONLINE=0 rather than by mocking a function the script does not have.
FAKES = {
    "git": r"""#!/bin/sh
printf 'git %s\n' "$*" >> "$FAKE_LOG"
case "$1" in
  ls-remote)
    [ "${FAKE_ONLINE:-1}" = 1 ] || { echo "fatal: could not resolve host: github.com" >&2; exit 128; }
    echo "deadbeef	HEAD"; exit 0 ;;
  clone)
    [ "${FAKE_ONLINE:-1}" = 1 ] || { echo "fatal: could not resolve host: github.com" >&2; exit 128; }
    # the destination is the LAST argument
    for d in "$@"; do :; done
    mkdir -p "$d/.git"
    case "$d" in
      *controller*)
        [ "${FAKE_CTL_HAS_CLI:-1}" = 1 ] || exit 0
        mkdir -p "$d/deploy"; printf '#!/bin/sh\n' > "$d/deploy/sysible_ctl"
        chmod +x "$d/deploy/sysible_ctl" ;;
    esac
    exit 0 ;;
  -C) [ "${FAKE_ONLINE:-1}" = 1 ] || exit 128; exit 0 ;;
esac
exit 0
""",
    "docker": r"""#!/bin/sh
printf 'docker %s\n' "$*" >> "$FAKE_LOG"
[ "$1" = info ] && { [ "${FAKE_DOCKER_UP:-1}" = 1 ] || exit 1; exit 0; }
exit 0
""",
    "curl": r"""#!/bin/sh
printf 'curl %s\n' "$*" >> "$FAKE_LOG"
[ "${FAKE_ONLINE:-1}" = 1 ] || exit 7
exit 0
""",
    "sysible_ctl": r"""#!/bin/sh
printf 'sysible_ctl %s\n' "$*" >> "$FAKE_LOG"
exit "${FAKE_CTL_RC:-0}"
""",
    # `list` answers in the real catalog's shape: a header row, one row per tool,
    # a blank line, then a sentence. FAKE_TOOLS_CATALOG says which tools THIS
    # edition offers (Server carries no Obsidian).
    "sysible-tools": r"""#!/bin/sh
printf 'sysible-tools %s
' "$*" >> "$FAKE_LOG"
if [ "$1" = list ]; then
  printf '%-10s %-10s %-12s %s
' TOOL STATE LICENSE DESCRIPTION
  for t in ${FAKE_TOOLS_CATALOG:-terraform vault consul nomad packer boundary aws-cli obsidian}; do
    printf '%-10s %-10s %-12s %s
' "$t" available Various "a tool"
  done
  printf '
'
  echo "Already in the image: OpenTofu (tofu), gcloud, Docker, kubectl."
  exit 0
fi
exit "${FAKE_TOOLS_RC:-0}"
""",
    "systemctl": r"""#!/bin/sh
printf 'systemctl %s\n' "$*" >> "$FAKE_LOG"
exit 0
""",
}


class Sandbox:
    def __init__(self, tmp_path, script):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.write_text("")
        for name, body in FAKES.items():
            f = self.bin / name
            f.write_text(body)
            f.chmod(0o755)
        # The sandbox is the WHOLE PATH (see _env). Without that, dropping a fake
        # to simulate "this workstation has no docker" just fell through to the
        # real binary in /usr/bin and the test proved nothing. So the ordinary
        # tools the script needs are linked in explicitly, and only those.
        for name in ("basename", "dirname", "tr", "sleep", "mkdir", "ln", "id",
                     "cat", "sed", "rm", "env", "uname", "chmod", "printf", "awk"):
            real = shutil.which(name)
            if real and not (self.bin / name).exists():
                (self.bin / name).symlink_to(real)
        # A copy of the real script, with only its install root redirected — the
        # logic under test is untouched.
        src = (BIN / script).read_text()
        self.src_dir = tmp_path / "src"
        assert "SRC_DIR=/opt/sysible-src" in src, "the script no longer sets SRC_DIR"
        src = src.replace("SRC_DIR=/opt/sysible-src", f"SRC_DIR={self.src_dir}")
        # /usr/local/bin is not writable in a test; the symlink lands here instead.
        src = src.replace("/usr/local/bin/sysible_ctl", str(tmp_path / "sysible_ctl"))
        self.script = tmp_path / script
        self.script.write_text(src)
        self.script.chmod(0o755)

    def drop(self, *names):
        """Make a command unavailable, the way a workstation that lacks it would."""
        for n in names:
            (self.bin / n).unlink(missing_ok=True)

    def _env(self, extra):
        env = {
            # ONLY the sandbox: a test that removes a command must actually remove
            # it, not be shadowed by the real one on this machine.
            "PATH": str(self.bin),
            "FAKE_LOG": str(self.log),
            "HOME": str(self.tmp),
            # Root already: the script's `exec sudo` line is for a real desktop.
        }
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def run(self, *args, **env):
        p = subprocess.run(["/bin/sh", str(self.script), *args], capture_output=True,
                           text=True, env=self._env(env), timeout=120)
        return p

    def run_on_a_terminal(self, *args, timeout=30, **env):
        """Run it attached to a pty, as the app-grid launcher does, and answer the
        one Enter it asks for. Returns (output, exit_status, waited_for_enter)."""
        pid, fd = pty.fork()
        if pid == 0:                                    # child
            os.environ.clear()
            os.environ.update(self._env(env))
            os.execv("/bin/sh", ["/bin/sh", str(self.script), *args])
        out, asked, deadline = "", False, time.time() + timeout
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 4096).decode("utf-8", "replace")
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                if "Press Enter to close" in out and not asked:
                    asked = True
                    os.write(fd, b"\n")
            else:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    break
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = 0
        return out, status, asked

    def calls(self):
        return self.log.read_text()


@pytest.fixture()
def installer(tmp_path):
    return Sandbox(tmp_path, "install-sysible")
