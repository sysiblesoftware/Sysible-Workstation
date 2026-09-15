"""`install-sysible`: the menu is fine — what happens after it is the problem.

Reported as "the Sysible software install gives a great menu but when I press
enter it doesn't seem to install anything". Something did happen: the run hit a
prerequisite it could not meet (no network, or a Docker daemon that had not
started), printed why, and exited. It runs under a Terminal=true .desktop, so the
terminal emulator closed on that message — and the pause that would have held the
window open was the LAST line of the script, reached only on the paths that
succeeded. Every failure closed the window on its own explanation.

So: check the prerequisites BEFORE the menu, say so in the UI the operator is
already in, and hold the window open on every exit rather than only the happy one.
"""
import re

import pytest


class TestPrerequisitesAreCheckedBeforeAnythingIsAsked:
    def test_no_network_refuses_before_touching_the_disk(self, installer):
        p = installer.run("all", FAKE_ONLINE=0)
        assert p.returncode != 0
        assert "git clone" not in installer.calls(), \
            "it started cloning before finding out it was offline"
        assert not (installer.src_dir / "sysible-controller").exists()

    def test_no_network_says_what_to_do_about_it(self, installer):
        out = installer.run("all", FAKE_ONLINE=0).stderr
        assert "No internet connection" in out
        assert "github.com" in out
        assert "Nothing has been installed" in out, \
            "the operator must know whether they are half-installed"
        assert "\\n" not in out, "escape sequences leaked into the terminal message"

    def test_a_stopped_docker_daemon_is_started_then_reported(self, installer):
        p = installer.run("all", FAKE_DOCKER_UP=0)
        assert p.returncode != 0
        assert "systemctl start docker" in installer.calls(), \
            "a daemon that is merely not started yet should just be started"
        assert "Docker daemon is not running" in p.stderr
        assert "systemctl start docker" in p.stderr, "tell them the command"

    def test_missing_docker_is_named_not_guessed_at(self, installer):
        installer.drop("docker")
        p = installer.run("all")
        assert p.returncode != 0
        assert "Docker is required" in p.stderr

    def test_missing_git_is_named(self, installer):
        installer.drop("git")
        p = installer.run("all")
        assert p.returncode != 0
        assert "git is required" in p.stderr

    def test_a_healthy_machine_gets_past_the_checks(self, installer):
        p = installer.run("all")
        assert p.returncode == 0, p.stderr
        assert "online" in p.stdout


class TestTheWindowStaysOpenLongEnoughToRead:
    """The .desktop is Terminal=true, so the emulator closes the instant this
    exits. Whether an error can be read is the whole difference between "it does
    nothing" and "it told me I was offline"."""

    def test_a_failed_run_waits_before_closing(self, installer):
        out, _status, asked = installer.run_on_a_terminal("all", FAKE_ONLINE=0)
        assert asked, "the window closed on the error message"
        assert "No internet connection" in out
        assert "The installer stopped" in out

    def test_a_successful_run_waits_too(self, installer):
        out, _status, asked = installer.run_on_a_terminal("all")
        assert asked
        assert "All done" in out

    def test_it_does_not_wait_when_nobody_is_watching(self, installer):
        """Piped or scripted, it must not block forever on a read."""
        p = installer.run("all")
        assert "Press Enter" not in p.stdout


class TestWhatItActuallyInstalls:
    def test_all_brings_up_the_three_apps(self, installer):
        installer.run("all")
        calls = installer.calls()
        for app in ("controller", "slep", "connect"):
            assert re.search(rf"sysible_ctl {app} up\b", calls), calls
        assert "sysible_ctl slop up" not in calls

    def test_slop_brings_up_the_gateway_and_all_three(self, installer):
        installer.run("slop")
        calls = installer.calls()
        for app in ("controller", "slep", "connect", "slop"):
            assert re.search(rf"sysible_ctl {app} up\b", calls), calls

    def test_one_app_failing_never_stops_the_others(self, installer):
        """The run is best-effort by design; it used to abort on an undefined
        _warn, which killed the very case it was built for."""
        p = installer.run("all", FAKE_CTL_RC=1)
        calls = installer.calls()
        assert calls.count(" up") >= 3, calls
        assert "WITH PROBLEMS" in (p.stdout + p.stderr)

    def test_an_unknown_build_is_refused(self, installer):
        p = installer.run("frobnicate")
        assert p.returncode != 0
        assert "unknown build" in p.stderr


class TestOptionalSoftware:
    """Obsidian was never installed and never mentioned: install-sysible called
    /usr/local/bin/sysible-install-obsidian, a script REMOVED when the work moved
    into the sysible-obsidian-installer package. The call was guarded by
    `command -v`, so the test simply failed and the branch was skipped in silence."""

    def test_obsidian_is_installed_with_the_rest(self, installer):
        installer.run("slop")
        tools = [l for l in installer.calls().splitlines() if l.startswith("sysible-tools")]
        assert tools, "the optional-software catalog was never called"
        assert "obsidian" in tools[0], tools

    def test_it_no_longer_calls_the_deleted_helper(self):
        from conftest import BIN
        src = (BIN / "install-sysible").read_text()
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert "sysible-install-obsidian" not in body, \
            "that script was removed with the package split; calling it silently skips Obsidian"

    def test_the_licensed_tools_are_all_requested(self, installer):
        installer.run("slop")
        tools = [l for l in installer.calls().splitlines() if l.startswith("sysible-tools")][0]
        for t in ("terraform", "vault", "consul", "nomad", "packer", "boundary", "aws-cli"):
            assert t in tools, tools

    def test_a_missing_catalog_is_reported_not_skipped_quietly(self, installer):
        installer.drop("sysible-tools")
        p = installer.run("slop")
        both = p.stdout + p.stderr
        assert "SKIPPED" in both
        assert "sysible-tools install" in both, "tell them how to get it later"
        assert "WITH PROBLEMS" in both, "a silent skip reads as a successful install"

    def test_optional_software_is_not_touched_for_a_plain_app_install(self, installer):
        installer.run("all")
        assert "sysible-tools" not in installer.calls()
