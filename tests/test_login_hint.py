"""What a machine tells you at login about its Sysible software.

Two gaps this closes. On Sysible Server there is no app grid, so `install-sysible`
was not discoverable at all — you had to already know it existed. And on both
editions, updates are deliberately NOT automatic (an update rebuilds from source
and recreates containers; that is not something to do behind someone's back), so
nothing ever said a product was behind its release.

The hard constraint is that a login must never wait on a network. The release check
runs from a timer and writes a state file; the hint only reads that file. These
tests hold that line — a hint that hangs a login shell is far worse than no hint.
"""
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import BIN, CHROOT, UNITS


@pytest.fixture()
def machine(tmp_path):
    """A pretend machine: a src dir, a state dir, an /etc/sysible."""
    class M:
        src = tmp_path / "src"
        state = tmp_path / "state"
        etc = tmp_path / "etc"
        home = tmp_path / "home"

        def __init__(self):
            for d in (self.src, self.state, self.etc, self.home):
                d.mkdir(parents=True, exist_ok=True)

        def installed(self, *names):
            for n in names:
                (self.src / n / ".git").mkdir(parents=True, exist_ok=True)

        def state_says(self, behind="", checked=1):
            (self.state / "update-state").write_text(
                f"checked_at=2026-01-01T00:00:00Z\nchecked={checked}\nbehind={behind}\n")

        def hint(self, **env):
            e = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "TERM": "dumb",
                 "SYSIBLE_SRC_DIR": str(self.src), "SYSIBLE_STATE_DIR": str(self.state),
                 "SYSIBLE_ETC_DIR": str(self.etc)}
            e.update({k: str(v) for k, v in env.items()})
            return subprocess.run(["/bin/sh", str(BIN / "sysible-hint")],
                                  capture_output=True, text=True, env=e, timeout=20)
    return M()


class TestWhenNothingIsInstalled:
    def test_it_names_the_installer(self, machine):
        out = machine.hint().stdout
        assert "No Sysible software is installed" in out
        assert "sudo install-sysible" in out, \
            "on Server there is no app grid — this line is the only way to find it"

    def test_it_says_nothing_is_running_yet(self, machine):
        """So an operator knows the machine is not quietly serving something."""
        out = machine.hint().stdout
        assert "no ports open" in out


class TestWhenSomethingIsInstalled:
    def test_it_is_silent_with_nothing_to_report(self, machine):
        machine.installed("sysible-controller")
        machine.state_says(behind="")
        assert machine.hint().stdout.strip() == "", "a quiet machine must stay quiet"

    def test_it_is_silent_before_the_first_check(self, machine):
        """No state file yet: say nothing rather than guess."""
        machine.installed("sysible-controller")
        assert machine.hint().stdout.strip() == ""

    def test_it_reports_what_is_behind(self, machine):
        machine.installed("sysible-controller", "sysible-connect")
        machine.state_says(behind="sysible-controller sysible-connect")
        out = machine.hint().stdout
        assert "2 Sysible products have an update" in out, out
        assert "sysible-controller" in out and "sysible-connect" in out
        assert "sudo sysible_ctl update all" in out

    def test_one_product_reads_as_one(self, machine):
        machine.installed("sysible-controller")
        machine.state_says(behind="sysible-controller")
        out = machine.hint().stdout
        assert "1 Sysible product has an update" in out, out

    def test_it_promises_the_data_volumes_are_safe(self, machine):
        """The reason people put updates off. Say it where they read it."""
        machine.installed("sysible-controller")
        machine.state_says(behind="sysible-controller")
        assert "Data volumes are never touched" in machine.hint().stdout


class TestItNeverGetsInTheWay:
    def test_a_login_never_waits_on_the_network(self, machine):
        """The whole reason for the state file. If the hint ever grows a git or
        curl call, this is what catches it."""
        src = (BIN / "sysible-hint").read_text()
        body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for forbidden in ("curl", "wget", "ls-remote", "git fetch", "nc "):
            assert forbidden not in body, f"sysible-hint reaches the network via {forbidden!r}"

    def test_the_machine_can_switch_it_off(self, machine):
        (machine.etc / "no-hints").touch()
        assert machine.hint().stdout.strip() == ""

    def test_one_user_can_switch_it_off_for_themselves(self, machine):
        (machine.home / ".sysible-no-hints").touch()
        assert machine.hint().stdout.strip() == ""

    def test_it_is_plain_text_on_a_dumb_terminal(self, machine):
        assert "\x1b[" not in machine.hint(TERM="dumb").stdout

    def test_it_honours_no_color(self, machine):
        assert "\x1b[" not in machine.hint(TERM="xterm", NO_COLOR="1").stdout

    def test_the_profile_snippet_cannot_break_a_login(self):
        snippet = (CHROOT / "etc" / "profile.d" / "sysible-hint.sh").read_text()
        assert "|| true" in snippet, "a failing hint must not fail the login shell"
        assert "*i*" in snippet, "non-interactive shells (scp, rsync) must stay silent"


class TestTheReleaseCheck:
    """It is the half that DOES touch the network — from a timer, never a login."""

    def _repo(self, path, remote):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
        def run(*a, cwd):
            subprocess.run(a, cwd=str(cwd), check=True, capture_output=True, env=env)
        remote.mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", "-b", "main", cwd=remote)
        (remote / "f").write_text("1")
        run("git", "add", "f", cwd=remote)
        run("git", "commit", "-qm", "one", cwd=remote)
        path.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "-q", str(remote), str(path), cwd=path.parent)
        return env

    def _check(self, machine):
        return subprocess.run(["/bin/sh", str(BIN / "sysible-release-check")],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ,
                                   "SYSIBLE_SRC_DIR": str(machine.src),
                                   "SYSIBLE_STATE_DIR": str(machine.state)})

    def _state(self, machine):
        return dict(l.split("=", 1) for l in
                    (machine.state / "update-state").read_text().splitlines() if "=" in l)

    def test_an_up_to_date_checkout_is_not_reported(self, machine, tmp_path):
        self._repo(machine.src / "prod", tmp_path / "origin")
        assert self._check(machine).returncode == 0
        st = self._state(machine)
        assert st["behind"] == "" and st["checked"] == "1"

    def test_a_release_that_landed_upstream_is_reported(self, machine, tmp_path):
        origin = tmp_path / "origin"
        env = self._repo(machine.src / "prod", origin)
        (origin / "f").write_text("2")
        subprocess.run(["git", "commit", "-aqm", "two"], cwd=str(origin), check=True,
                       capture_output=True, env=env)
        self._check(machine)
        assert self._state(machine)["behind"] == "prod"

    def test_a_checkout_with_no_upstream_is_skipped(self, machine):
        """A local experiment is not 'behind' anything; reporting it for ever is noise."""
        (machine.src / "loose" / ".git").mkdir(parents=True)
        self._check(machine)
        st = self._state(machine)
        assert st["behind"] == "" and st["checked"] == "0"

    def test_an_unreachable_remote_reports_nothing_rather_than_guessing(self, machine, tmp_path):
        origin = tmp_path / "origin"
        self._repo(machine.src / "prod", origin)
        subprocess.run(["git", "remote", "set-url", "origin", str(tmp_path / "gone")],
                       cwd=str(machine.src / "prod"), check=True, capture_output=True)
        assert self._check(machine).returncode == 0, "offline must not be a failure"
        st = self._state(machine)
        assert st["behind"] == "" and st["checked"] == "0"

    def test_it_never_fetches_into_the_live_checkout(self):
        """A fetch killed part way strands .lock files that break every later ref
        update — in the deployment repo the operator then cannot update."""
        body = (BIN / "sysible-release-check").read_text()
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        assert "ls-remote" in code
        assert "fetch" not in code and " pull" not in code

    def test_the_timer_spreads_the_fleet_out(self):
        unit = (UNITS / "sysible-release-check.timer").read_text()
        assert "RandomizedDelaySec" in unit, \
            "every machine asking the same remotes at the same minute is a thundering herd"
        assert "Persistent=true" in unit, "a machine that was off should still check"

    def test_the_service_cannot_leave_the_system_degraded(self):
        unit = (UNITS / "sysible-release-check.service").read_text()
        assert "|| true" in unit, "a no-network boot must not show as a failed unit"
