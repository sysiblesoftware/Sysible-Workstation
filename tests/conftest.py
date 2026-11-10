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
# install-sysible moved OUT of includes.chroot and into the sysible-cli package.
# It used to ship only inside the ISO, so no `apt upgrade` could ever replace it
# and every installer fix reached new images only. The package installs it to
# /usr/sbin and its postinst takes over the stale /usr/local/bin copy an older
# ISO left behind. The other launchers here are still image-only.
PKG_BIN = REPO / "packages" / "sysible-cli"


def script_source(name):
    """Where a launcher's source lives, wherever it ships from."""
    for d in (PKG_BIN, BIN):
        if (d / name).is_file():
            return d / name
    raise AssertionError(f"{name} is in neither {PKG_BIN} nor {BIN}")
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
    # Every real product checkout has a compose file, and install-sysible now
    # records the console's URL prefix in the .env beside it. A fake clone with
    # no compose file is not a checkout any of this could act on.
    printf 'services:\n  app:\n    image: busybox\n' > "$d/docker-compose.yml"
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
# `docker compose` is the v2 PLUGIN, installed separately from the engine — a
# machine can have a working daemon and no compose at all, which is what the
# marker stands for. Without this the installer's compose gate was untestable.
[ "$1" = compose ] && { [ -e "$FAKE_BIN/.compose-plugin" ] || exit 1; exit 0; }
exit 0
""",
    # Standalone compose, the second thing the installer's gate looks for.
    "docker-compose": r"""#!/bin/sh
printf 'docker-compose %s\n' "$*" >> "$FAKE_LOG"
exit 0
""",
    # apt-get is the installer's ONLY way to put a runtime on a machine that has
    # none, so the fake has to really provision: it drops the commands it claims
    # to install into the sandbox PATH. A fake that just exited 0 would let a
    # version of the script that "tries" and recovers nothing pass this suite.
    #
    # FAKE_APT_NO is a space-separated list of packages THIS machine cannot get —
    # that is how a test says "download.docker.com was never wired up here",
    # which is the condition that produced the original bug report.
    "apt-get": r"""#!/bin/sh
printf 'apt-get %s\n' "$*" >> "$FAKE_LOG"
[ "$1" = update ] && exit "${FAKE_APT_UPDATE_RC:-0}"
for p in "$@"; do
  for bad in ${FAKE_APT_NO:-}; do
    [ "$p" = "$bad" ] && { echo "E: Unable to locate package $p" >&2; exit 100; }
  done
done
for p in "$@"; do
  case "$p" in
    docker-ce)             cp "$FAKE_SEED/docker" "$FAKE_BIN/docker" ;;
    podman)                cp "$FAKE_SEED/podman" "$FAKE_BIN/podman" ;;
    # podman-docker is what makes the Podman fallback real: it ships
    # /usr/bin/docker as a shim onto podman. So the fake installs the docker
    # command, exactly as the package does.
    podman-docker)         cp "$FAKE_SEED/docker" "$FAKE_BIN/docker" ;;
    docker-compose-plugin) : > "$FAKE_BIN/.compose-plugin" ;;
    docker-compose)        cp "$FAKE_SEED/docker-compose" "$FAKE_BIN/docker-compose" ;;
  esac
done
exit 0
""",
    "podman": r"""#!/bin/sh
printf 'podman %s\n' "$*" >> "$FAKE_LOG"
exit 0
""",
    "curl": r"""#!/bin/sh
printf 'curl %s\n' "$*" >> "$FAKE_LOG"
[ "${FAKE_ONLINE:-1}" = 1 ] || exit 7
exit 0
""",
    # The real CLI refuses `rebuild __probe__` while PARSING, before it touches
    # anything — that refusal is how install-sysible works out which build verb
    # this CLI speaks. So the fake answers it the same way, and does NOT log it:
    # a probe is not a call, and counting it as one would hide a missing bring-up.
    # FAKE_CTL_OLD=1 makes it answer as a CLI from before `rebuild` existed.
    "sysiblectl": r"""#!/bin/sh
if [ "$1" = rebuild ] && [ "$2" = __probe__ ]; then
  if [ "${FAKE_CTL_OLD:-0}" = 1 ]; then
    echo "ERROR: unknown or ambiguous: 'rebuild __probe__'" >&2
  else
    echo "ERROR: '__probe__' is not a product. Name the one you mean:" >&2
  fi
  exit 1
fi
printf 'sysiblectl %s\n' "$*" >> "$FAKE_LOG"
# The URL prefix a console's assets are built for. sysiblectl never sets one, so
# install-sysible has to — and getting it wrong is invisible until a browser asks
# the SLOP portal for an app's script and renders a blank page. Log it per call
# so a test can assert it per product.
printf 'basepath %s=%s\n' "$1" "${SYSIBLE_BASE_PATH-<unset>}" >> "$FAKE_LOG"
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
        # The sandbox PATH, and a pristine SEED copy beside it. apt-get installs
        # by copying out of the seed, so "the installer recovered" means a command
        # really appeared on PATH where there was none — not that a stub exited 0.
        self.seed = tmp_path / "seed"
        self.seed.mkdir()
        for name, body in FAKES.items():
            for d in (self.bin, self.seed):
                f = d / name
                f.write_text(body)
                f.chmod(0o755)
        # A healthy machine has the compose v2 plugin. `docker compose` consults
        # this marker, so a test drops it to mean "engine up, no compose".
        (self.bin / ".compose-plugin").write_text("")
        # The sandbox is the WHOLE PATH (see _env). Without that, dropping a fake
        # to simulate "this workstation has no docker" just fell through to the
        # real binary in /usr/bin and the test proved nothing. So the ordinary
        # tools the script needs are linked in explicitly, and only those.
        for name in ("basename", "dirname", "tr", "sleep", "mkdir", "ln", "id",
                     "cat", "sed", "rm", "env", "uname", "chmod", "printf", "awk",
                     # cp: the apt-get fake installs by copying out of the seed.
                     "cp",
                     # grep: the script reads the CLI's own refusal to work out
                     # which build verb it speaks. Without it here the probe
                     # silently answered "the old one" and the bring-up assertions
                     # failed for a reason that had nothing to do with the script.
                     "grep"):
            real = shutil.which(name)
            if real and not (self.bin / name).exists():
                (self.bin / name).symlink_to(real)
        # A copy of the real script, with only its install root redirected — the
        # logic under test is untouched.
        src = script_source(script).read_text()
        self.src_dir = tmp_path / "src"
        assert "SRC_DIR=/opt/sysible-src" in src, "the script no longer sets SRC_DIR"
        src = src.replace("SRC_DIR=/opt/sysible-src", f"SRC_DIR={self.src_dir}")
        # /usr/local/bin is not writable in a test; the symlinks land here instead.
        # BOTH names, or the test would write a real link into /usr/local/bin on
        # whatever machine it runs on.
        src = src.replace("/usr/local/bin/sysiblectl", str(tmp_path / "sysiblectl"))
        src = src.replace("/usr/local/bin/sysible_ctl", str(tmp_path / "sysible_ctl"))
        self.script = tmp_path / script
        self.script.write_text(src)
        self.script.chmod(0o755)

    def drop(self, *names):
        """Make a command unavailable, the way a workstation that lacks it would."""
        for n in names:
            (self.bin / n).unlink(missing_ok=True)

    def drop_compose(self):
        """Neither the v2 plugin nor standalone compose — the state a machine is
        in when the engine installed and its compose package did not."""
        (self.bin / ".compose-plugin").unlink(missing_ok=True)
        (self.bin / "docker-compose").unlink(missing_ok=True)

    def _env(self, extra):
        env = {
            # ONLY the sandbox: a test that removes a command must actually remove
            # it, not be shadowed by the real one on this machine.
            "PATH": str(self.bin),
            "FAKE_LOG": str(self.log),
            "FAKE_BIN": str(self.bin),
            "FAKE_SEED": str(self.seed),
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
