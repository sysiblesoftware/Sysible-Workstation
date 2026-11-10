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

    def test_a_missing_runtime_is_installed_not_reported(self, installer):
        """The bug this class exists for. It used to print "Docker is required and
        is not installed" and exit 1 — handing the one prerequisite the operator
        could do least about to the one person who had just been given a finished
        install. An installer that stops at a missing dependency it could fetch
        has not installed the software."""
        installer.drop("docker")
        p = installer.run("all")
        assert p.returncode == 0, p.stderr
        assert "apt-get install" in installer.calls(), \
            "it refused instead of installing a runtime"
        # and it got all the way through to bringing the products up
        assert "sysiblectl controller rebuild" in installer.calls()

    def test_it_falls_back_to_podman_when_docker_ce_is_unreachable(self, installer):
        """Exactly the machine that produced the report. docker-ce is a Recommends
        from download.docker.com, excluded from the ISO package list and installed
        by a build hook; podman/buildah/skopeo are hard Depends from Debian itself.
        So the runtime that is guaranteed and the runtime the stack demanded were
        different ones, and when the Docker repo was not wired up the operator was
        told to go and install Docker by hand."""
        installer.drop("docker")
        p = installer.run("all", FAKE_APT_NO="docker-ce")
        assert p.returncode == 0, p.stderr
        calls = installer.calls()
        assert re.search(r"apt-get install.*\bpodman-docker\b", calls), calls
        assert "sysiblectl controller rebuild" in calls, \
            "it installed a runtime and then still did not install the software"

    def test_the_podman_fallback_takes_compose_that_writes_docker_labels(self, installer):
        """podman-compose would be the obvious partner and is the wrong one:
        sysiblectl finds a product's compose file by reading the running
        container's com.docker.compose.* labels back, and podman-compose writes
        io.podman.compose.* instead, so every one of those lookups returns empty.
        Standalone docker-compose drives podman's socket and writes the labels."""
        installer.drop("docker")
        installer.run("all", FAKE_APT_NO="docker-ce")
        calls = installer.calls()
        assert "podman-compose" not in calls, calls
        assert re.search(r"apt-get install.*\bdocker-compose\b", calls), calls

    def test_no_runtime_and_no_way_to_get_one_still_says_so(self, installer):
        """Installing is the new behaviour; inventing a success is not."""
        installer.drop("docker")
        p = installer.run("all", FAKE_APT_NO="docker-ce podman podman-docker")
        assert p.returncode != 0
        assert "No container runtime" in p.stderr
        assert "Nothing has been installed" in p.stderr
        assert "sysiblectl controller rebuild" not in installer.calls()

    def test_a_runtime_with_no_compose_is_completed_not_abandoned(self, installer):
        """Compose is installed separately from the engine on every path, so a
        machine can have a working daemon and nothing to bring a product up with.
        That used to be found at the first bring-up, products in, half-installed."""
        installer.drop_compose()
        p = installer.run("all")
        assert p.returncode == 0, p.stderr
        assert re.search(r"apt-get install.*compose", installer.calls()), \
            "it went to the bring-up with no compose at all"

    def test_the_runtime_is_sorted_out_before_the_menu(self, installer):
        """Same reason the network check moved up: a prerequisite discovered
        mid-run loses its message when the launcher's window closes."""
        installer.drop("docker")
        calls = installer.run("all").stdout + installer.calls()
        apt = installer.calls().index("apt-get install")
        ctl = installer.calls().index("sysiblectl controller rebuild")
        assert apt < ctl, "it started installing products before it had a runtime"

    def test_being_offline_is_reported_before_blaming_the_runtime(self, installer):
        """Every runtime path here is an apt fetch, so "could not install Docker"
        is the wrong thing to say to someone who is simply not on a network."""
        installer.drop("docker")
        p = installer.run("all", FAKE_ONLINE=0)
        assert p.returncode != 0
        assert "No internet connection" in p.stderr
        assert "container runtime" not in p.stderr
        assert "apt-get install" not in installer.calls()

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
    """The app-grid .desktop is Terminal=true, so the emulator closes the instant
    this exits. Whether an error can be read is the whole difference between "it
    does nothing" and "it told me I was offline". The launcher asks for the pause
    with SYSIBLE_INSTALLER_PAUSE=1; a shell run (the only kind on Server) must not
    stop to ask for a keypress, because the shell is still there afterwards."""

    def test_a_failed_run_waits_before_closing(self, installer):
        out, _status, asked = installer.run_on_a_terminal(
            "all", FAKE_ONLINE=0, SYSIBLE_INSTALLER_PAUSE=1)
        assert asked, "the window closed on the error message"
        assert "No internet connection" in out
        assert "The installer stopped" in out

    def test_a_successful_run_waits_too(self, installer):
        out, _status, asked = installer.run_on_a_terminal(
            "all", SYSIBLE_INSTALLER_PAUSE=1)
        assert asked
        assert "All done" in out

    def test_a_shell_run_on_a_terminal_does_not_stop_to_ask(self, installer):
        out, _status, asked = installer.run_on_a_terminal("all")
        assert not asked, "a command run from a shell should just finish"
        assert "All done" in out

    def test_it_does_not_wait_when_nobody_is_watching(self, installer):
        """Piped or scripted, it must not block forever on a read."""
        p = installer.run("all", SYSIBLE_INSTALLER_PAUSE=1)
        assert "Press Enter" not in p.stdout


class TestOneScriptForEveryEdition:
    """install-sysible ships byte-identical on Workstation and Server. They used to
    be two copies and they drifted: the Server's predated the SLOP option, still
    aborted the whole run on the first app that failed, and never offered the
    optional software — so "install the Sysible software" meant something different
    depending on which ISO you booted."""

    def test_the_edition_name_is_read_at_runtime(self, installer, tmp_path):
        """Not written into the file, or the two copies differ by construction."""
        from conftest import script_source
        src = script_source("install-sysible").read_text()
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert "Sysible Workstation" not in body, \
            "the edition is named in the script, so the Server's copy cannot be identical"
        assert "os-release" in src

    def test_the_title_follows_os_release(self, installer):
        """Workstation's PRETTY_NAME carries a tagline; the name is what we want."""
        for pretty, want in (
                ("Sysible Workstation — Engineering Automation Cloud", "Sysible Workstation"),
                ("Sysible Server", "Sysible Server")):
            osr = installer.tmp / "os-release"
            osr.write_text(f'PRETTY_NAME="{pretty}"\n')
            src = installer.script.read_text().replace("/etc/os-release", str(osr))
            installer.script.write_text(src)
            p = installer.run("all")
            assert p.returncode == 0, p.stderr
            got = installer.tmp / "edition"
            # The name only shows in the whiptail title, so read it back directly.
            import subprocess
            r = subprocess.run(["/bin/sh", "-c",
                                f'. {osr}; printf "%s" "${{PRETTY_NAME}}" | sed "s/ [—-].*//"'],
                               capture_output=True, text=True)
            assert r.stdout == want, r.stdout

    def test_the_sync_stamp_matches_the_file(self):
        """Editing one copy without restamping fails here, in this repo alone —
        no need for the other repo to be checked out."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        import stamp_sync
        assert stamp_sync.main(["--check"]) == 0


class TestWhatItActuallyInstalls:
    def test_all_brings_up_the_three_apps(self, installer):
        installer.run("all")
        calls = installer.calls()
        for app in ("controller", "slep", "connect"):
            assert re.search(rf"sysiblectl {app} rebuild\b", calls), calls
        assert "sysiblectl slop rebuild" not in calls

    def test_slop_brings_up_the_gateway_and_all_three(self, installer):
        installer.run("slop")
        calls = installer.calls()
        for app in ("controller", "slep", "connect", "slop"):
            assert re.search(rf"sysiblectl {app} rebuild\b", calls), calls

    def test_one_app_failing_never_stops_the_others(self, installer):
        """The run is best-effort by design; it used to abort on an undefined
        _warn, which killed the very case it was built for."""
        p = installer.run("all", FAKE_CTL_RC=1)
        calls = installer.calls()
        assert calls.count(" rebuild") >= 3, calls
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
        installs = [l for l in installer.calls().splitlines()
                    if l.startswith("sysible-tools install")]
        assert installs, "the optional-software catalog was never installed from"
        assert "obsidian" in installs[0], installs

    def test_it_installs_what_THIS_edition_offers(self, installer):
        """Server deliberately carries no Obsidian — a note-taking GUI on a headless
        box. A hard-coded list would make a correct Server install report a failure
        for something it was right not to have."""
        installer.run("slop", FAKE_TOOLS_CATALOG="terraform vault aws-cli")
        installs = [l for l in installer.calls().splitlines()
                    if l.startswith("sysible-tools install")][0]
        assert "obsidian" not in installs, installs
        for t in ("terraform", "vault", "aws-cli"):
            assert t in installs, installs

    def test_a_tool_added_to_the_catalog_needs_no_change_here(self, installer):
        installer.run("slop", FAKE_TOOLS_CATALOG="terraform something-new")
        installs = [l for l in installer.calls().splitlines()
                    if l.startswith("sysible-tools install")][0]
        assert "something-new" in installs, installs

    def test_an_unreadable_catalog_is_reported(self, installer):
        p = installer.run("slop", FAKE_TOOLS_CATALOG=" ")
        both = p.stdout + p.stderr
        assert "could not read the optional-software catalog" in both
        assert "WITH PROBLEMS" in both

    def test_it_no_longer_calls_the_deleted_helper(self):
        from conftest import script_source
        src = script_source("install-sysible").read_text()
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert "sysible-install-obsidian" not in body, \
            "that script was removed with the package split; calling it silently skips Obsidian"

    def test_the_licensed_tools_are_all_requested(self, installer):
        installer.run("slop")
        tools = [l for l in installer.calls().splitlines()
                 if l.startswith("sysible-tools install")][0]
        for t in ("terraform", "vault", "consul", "nomad", "packer", "boundary", "aws-cli"):
            assert t in tools, tools

    def test_a_missing_catalog_is_reported_not_skipped_quietly(self, installer):
        installer.drop("sysible-tools")
        p = installer.run("slop")
        both = p.stdout + p.stderr
        assert "SKIPPED" in both
        assert "sudo sysible-tools" in both, "tell them how to get it later"
        assert "WITH PROBLEMS" in both, "a silent skip reads as a successful install"

    def test_optional_software_is_not_touched_for_a_plain_app_install(self, installer):
        installer.run("all")
        assert "sysible-tools" not in installer.calls()


class TestItAsksTheCliWhichVerbItSpeaks:
    """A real install failed on exactly this: the platform installer had been
    updated to say `rebuild` while the Controller checkout it clones still had a
    CLI that only knew `up`, so EVERY product failed at its first command with
    "'rebuild' is not a command" and the run finished WITH PROBLEMS.

    The two are separate repositories that reach a host at different times, so
    neither verb can be hard-coded. The script asks the CLI, using the CLI's own
    parser and a product name that cannot exist — both answers are refusals
    raised while parsing, so nothing is built either way."""

    def test_a_current_cli_gets_rebuild(self, installer):
        installer.run("all")
        calls = installer.calls()
        for app in ("controller", "slep", "connect"):
            assert re.search(rf"sysiblectl {app} rebuild\b", calls), calls

    def test_a_cli_from_before_the_rename_gets_up(self, installer):
        """The reported failure, from the other side: an ISO built after the
        rename, pointed at a Controller checkout from before it."""
        installer.run("all", FAKE_CTL_OLD=1)
        calls = installer.calls()
        for app in ("controller", "slep", "connect"):
            assert re.search(rf"sysiblectl {app} up\b", calls), calls
            assert f"sysiblectl {app} rebuild" not in calls

    def test_the_probe_itself_never_counts_as_a_bring_up(self, installer):
        """It must not look like work was done. The real CLI refuses it during
        argument parsing and touches nothing."""
        installer.run("all")
        assert "__probe__" not in installer.calls()


class TestTheConsolesAreBuiltForWhereTheyAreServed:
    """A fresh `install-sysible slop` came up with blank Controller and SLEP
    consoles.

    Behind the SLOP gateway each app is path-routed (/slep/, /connect/). A
    console built for the domain root bakes an absolute /assets/index-*.js into
    its index.html, so the browser asks the SLOP PORTAL for that app's script,
    gets a 404, and renders nothing — no error, just a blank page.

    SLOP's own install.sh passes SYSIBLE_BASE_PATH per app for exactly this
    reason. `install-sysible` brings products up through sysiblectl instead, and
    sysiblectl never sets one, so this path passed nothing at all.
    """

    def _basepaths(self, installer):
        """What each product's checkout will be built with, read from the .env
        compose actually consults — not from the environment of one command.

        The first version of this asserted the env var passed to that single
        sysiblectl call, and passed while the real behaviour was still wrong:
        the value is gone by the next `sysiblectl <p> rebuild`, which rebuilds
        the console for the domain root and blanks it again. So the assertion
        has to be the durable thing.
        """
        out = {}
        for d in sorted(installer.src_dir.glob("*")):
            env = None
            for c in (d, d / "deploy", d / "deploy" / "docker"):
                if (c / ".env").is_file():
                    env = c / ".env"
                    break
            key = {"sysible-controller": "controller",
                   "sysible-linux-engineering-platform": "slep",
                   "sysible-connect": "connect",
                   "sysible-linux-operations-platform": "slop"}.get(d.name)
            if key is None:
                continue
            val = "<unset>"
            if env:
                for line in env.read_text().splitlines():
                    if line.startswith("SYSIBLE_BASE_PATH="):
                        val = line.split("=", 1)[1]
            out[key] = val
        return out

    def test_an_app_behind_the_gateway_is_built_for_its_prefix(self, installer):
        installer.run("slop")
        bp = self._basepaths(installer)
        assert bp.get("slep") == "/slep/", bp
        assert bp.get("connect") == "/connect/", bp

    def test_the_controller_is_not_pinned_to_a_prefix(self, installer):
        """Its console defaults to a relative base and reads the prefix at
        runtime from <base href>, so ONE build is right behind the gateway and on
        its own port. Pinning would break the direct address — the same
        controller is reached both ways."""
        installer.run("slop")
        bp = self._basepaths(installer)
        assert bp.get("controller") in ("<unset>", ""), \
            f"the controller was pinned to {bp.get('controller')!r}"

    def test_a_standalone_install_pins_nothing(self, installer):
        """With no gateway every app is served at its own root; a prefix there is
        the same bug pointing the other way."""
        installer.run("all")
        bp = self._basepaths(installer)
        for app in ("controller", "slep", "connect"):
            assert bp.get(app) in ("<unset>", ""), (app, bp)

    def test_the_prefix_matches_the_gateway_route(self, installer):
        """The gateway path-routes /<product>/, so the build-time prefix has to
        be exactly that, leading and trailing slash included — vite joins it to
        asset names by concatenation."""
        installer.run("slop")
        for app, got in self._basepaths(installer).items():
            if got in ("<unset>", ""):
                continue
            assert got.startswith("/") and got.endswith("/"), (app, got)
            assert got == f"/{app}/", (app, got)


class TestRemovingEverything:
    """`sysiblectl uninstall` removes the CLI symlinks and NOTHING else — it
    leaves every container, volume and checkout in place, and takes away the tool
    you would have removed them with. Asked for: "a complete uninstall and
    reinstall command for all products not just sysiblectl"."""

    def test_it_refuses_without_a_confirmation(self, installer):
        """Piped, with no --yes. Deleting every data volume on a guess is not a
        default anything should have."""
        (installer.src_dir / "sysible-controller").mkdir(parents=True, exist_ok=True)
        p = installer.run("--uninstall")
        assert p.returncode != 0
        assert "refusing to remove anything" in p.stderr
        assert (installer.src_dir / "sysible-controller").exists(), \
            "it deleted a checkout without being confirmed"

    def test_yes_takes_every_product_down_with_its_volumes(self, installer):
        p = installer.run("--uninstall", "--yes")
        assert p.returncode == 0, p.stderr
        calls = installer.calls()
        for app in ("controller", "slep", "connect", "slop"):
            assert re.search(rf"sysiblectl {app} destroy -v\b", calls), (app, calls)

    def test_keep_data_removes_containers_but_not_volumes(self, installer):
        p = installer.run("--uninstall", "--yes", "--keep-data")
        assert p.returncode == 0, p.stderr
        calls = installer.calls()
        for app in ("controller", "slep", "connect", "slop"):
            assert re.search(rf"sysiblectl {app} destroy\b(?! -v)", calls), (app, calls)
        assert "destroy -v" not in calls, "--keep-data still deleted the data volumes"

    def test_the_checkouts_go(self, installer):
        (installer.src_dir / "sysible-controller").mkdir(parents=True, exist_ok=True)
        installer.run("--uninstall", "--yes")
        assert not installer.src_dir.exists(), f"{installer.src_dir} survived"

    def test_it_needs_no_network(self, installer):
        """A host you are removing Sysible from may well be the one that cannot
        reach GitHub — that can be WHY you are removing it."""
        p = installer.run("--uninstall", "--yes", FAKE_ONLINE=0)
        assert p.returncode == 0, p.stderr
        assert "No internet connection" not in p.stderr
        assert "git clone" not in installer.calls()

    def test_it_works_when_the_install_never_finished(self, installer):
        """No CLI, no checkouts — the state a failed install leaves, and the one
        an operator most wants a clean slate from."""
        installer.drop("sysiblectl")
        p = installer.run("--uninstall", "--yes")
        assert p.returncode == 0, p.stderr
        assert "Sysible has been removed" in p.stdout

    def test_it_does_not_offer_the_install_menu(self, installer):
        """It used to fall through into the product checklist, because the menu
        ran before the mode was acted on."""
        out, _status, _asked = installer.run_on_a_terminal("--uninstall", "--yes")
        assert "Pick what to install" not in out

    def test_it_never_deletes_a_volume_by_name_pattern(self):
        """compose down -v is the only thing that knows which volumes belong to
        which project. These sit beside volumes that are not ours, and matching
        'sysible' against a name is how you delete somebody else's data."""
        from conftest import script_source
        body = script_source("install-sysible").read_text()
        assert "docker volume rm" not in body.replace(
            "  Remove one with:  docker volume rm <name>", ""), \
            "the teardown removes volumes directly instead of through compose"

    def test_it_says_the_os_is_left_alone(self, installer):
        """Removing the products is not removing Docker or the sysible-* packages,
        and an operator should not have to guess which happened."""
        p = installer.run("--uninstall", "--yes")
        assert "OS itself is untouched" in p.stdout


class TestReinstalling:
    def test_it_tears_down_before_installing(self, installer):
        p = installer.run("--reinstall", "all", "--yes")
        assert p.returncode == 0, p.stderr
        calls = installer.calls()
        first_destroy = calls.index("destroy")
        first_build = calls.index("controller rebuild")
        assert first_destroy < first_build, \
            "it rebuilt before removing, so the old stack was never cleared"

    def test_it_checks_the_prerequisites_first(self, installer):
        """The destructive half must not run until the install half is known to
        be possible — otherwise an offline host is left with nothing and no way
        back."""
        p = installer.run("--reinstall", "all", "--yes", FAKE_ONLINE=0)
        assert p.returncode != 0
        assert "No internet connection" in p.stderr
        assert "destroy" not in installer.calls(), \
            "it tore the stack down and only then found it could not reinstall"

    def test_an_unknown_option_is_refused(self, installer):
        p = installer.run("--frobnicate")
        assert p.returncode != 0
        assert "unknown option" in p.stderr


class TestEveryNameAnOperatorTypes:
    """`sysible-install` is how Sysible Server is installed — it is the name an
    operator is most likely to type, and it was shipping only inside the ISO.

    Both aliases just exec install-sysible, so a stale alias does the right thing
    anyway. The reason they are packaged is the other half: a stale REGULAR FILE
    at any of these /usr/local/bin paths outranks /usr/sbin on root's PATH, so
    the postinst has to take over all three, not just the canonical one.
    """
    ALIASES = ("sysible-install", "install-sysible-controller")

    @pytest.mark.parametrize("name", ALIASES)
    def test_the_alias_ships_from_the_package(self, name):
        from conftest import PKG_BIN, BIN
        assert (PKG_BIN / name).is_file(), (
            f"{name} is not in the package, so no apt upgrade can reach it"
        )
        assert not (BIN / name).exists(), (
            f"{name} is in includes.chroot as well — two copies is how they drift"
        )

    @pytest.mark.parametrize("name", ALIASES)
    def test_the_alias_still_just_delegates(self, name):
        """If one ever grows logic of its own, the suite has three installers to
        keep in step instead of one. That is what install-sysible-controller used
        to be, and it shipped a pre-container layout for months."""
        from conftest import script_source
        lines = script_source(name).read_text().splitlines()
        assert lines[0] == "#!/bin/sh", lines[0]
        # Everything after the shebang that is not a comment — the sync stamp is
        # a comment too, so filtering them is what leaves the actual body.
        body = [l for l in lines[1:] if l.strip() and not l.strip().startswith("#")]
        assert len(body) == 1, f"{name} is no longer a one-line alias: {body}"
        assert body[0].startswith("exec install-sysible"), body[0]

    def test_the_package_installs_all_three_to_usr_sbin(self):
        from conftest import PKG_BIN
        inst = (PKG_BIN / "debian" / "sysible-cli.install").read_text().split()
        for name in ("install-sysible",) + self.ALIASES:
            assert name in inst, f"{name} is not in debian/sysible-cli.install"
        assert inst.count("usr/sbin") == 3

    @pytest.mark.parametrize("name", ("install-sysible",) + ALIASES)
    def test_the_postinst_takes_over_a_stale_copy_of_each(self, name):
        """A regular file left by an older ISO shadows the packaged one forever.
        Taking over only install-sysible would leave Server's own entry point
        stale."""
        from conftest import PKG_BIN
        post = (PKG_BIN / "debian" / "sysible-cli.postinst").read_text()
        assert name in post, f"the postinst does not take over {name}"
        assert "/var/backups/sysible" in post, \
            "it replaces the operator's file without keeping a copy"

    @pytest.mark.parametrize("name", ("install-sysible",) + ALIASES)
    def test_the_prerm_only_removes_a_link_that_is_ours(self, name):
        from conftest import PKG_BIN
        pre = (PKG_BIN / "debian" / "sysible-cli.prerm").read_text()
        assert name in pre
        assert "readlink" in pre, \
            "it removes the path without checking the link still points at us"

    def test_the_iso_refuses_to_ship_an_unowned_copy(self):
        """The guarantee is dpkg OWNERSHIP, not existence — existence was always
        true and was never the problem."""
        import pathlib
        v = (pathlib.Path(__file__).resolve().parents[1] / "live-build" / "config"
             / "hooks" / "normal" / "9500-sysible-verify.hook.chroot").read_text()
        assert "dpkg -S" in v, "the ISO does not check that a package owns the installer"
        assert "not owned by any package" in v
        for name in ("install-sysible", "sysible-install", "install-sysible-controller"):
            assert name in v, f"the ISO assertion does not cover {name}"
