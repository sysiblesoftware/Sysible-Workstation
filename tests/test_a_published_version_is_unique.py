"""A pool path may never be published twice with different bytes.

Reported from an operator's workstation: every `apt upgrade` failed with

    File has unexpected size (10970 != 6736). Mirror sync in progress?

for six of eight Sysible packages. Nothing was mid-sync. The index described
one build and the CDN served another, at the same URL, months apart.

The repo publishes pool/ with `Cache-Control: immutable, max-age=31536000` —
a promise that a given .deb URL's bytes never change — and relies on a unique
per-build version suffix to keep that promise, so each publish lands on a path
the edge has never seen. The suffix was `+ci${github.run_number}`.

github.run_number is scoped to ONE workflow, and two reach the publish job:

    publish.yml on push/dispatch   -> publish.yml's counter  (78 and climbing)
    publish.yml called by iso.yml  -> ISO.YML's counter       (49, 50)

A reusable workflow sees the CALLER's run_number. So iso.yml run 49 stamped
+ci49 on the v1.0.5 stable publish, long after publish.yml run 49 had stamped
+ci49 on a different source tree for dev. Identical pool paths, different
bytes, and an edge under orders to treat them as immutable for a year.

The packages that still worked are the tell: sysible-artwork and systerm had
had their upstream versions bumped, so their +ci49 paths were genuinely new.
Only the six whose upstream version was unchanged collided.

These pin the three things that have to hold together.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/publish.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
STEPS = {s["name"]: s
         for s in yaml.safe_load(TEXT)["jobs"]["publish"]["steps"] if "name" in s}


def _step(name):
    """The shell body of one named step.

    Parsed out of the YAML rather than sliced out of the file: an earlier
    version of this test matched the substring "if:" and tripped over a COMMENT
    that merely mentioned the gate it was checking for. Structure is the thing
    being asserted, so read the structure.
    """
    return STEPS[name].get("run", "")


def test_the_version_suffix_is_not_a_bare_run_number():
    """The regression itself. run_number is per-workflow, so it cannot be the
    sole source of uniqueness for a path that is cached immutably."""
    build = _step("Build all packages")
    assert not re.search(r'SYSIBLE_VERSION_SUFFIX\s*[:=]\s*"?\+ci\$\{\{\s*github\.run_number',
                         build), (
        "the version suffix is github.run_number alone. That is unique within a "
        "single workflow and nothing more — iso.yml and publish.yml have "
        "independent counters and have already collided on +ci49."
    )


def test_the_version_suffix_carries_a_timestamp_a_run_id_and_a_commit():
    """Monotonic from the timestamp, UNIQUE from the run id, traceable from the
    sha — `apt policy` on a user's machine then names the commit it came from.

    The run id is the part that actually guarantees uniqueness. A first attempt
    used timestamp + sha and argued that no two runs share a second. Two did:
    a push to main and a workflow_dispatch of the SAME commit, triggered four
    seconds apart, reached the build step in the same second and produced an
    identical suffix. The immutability guard caught it and failed the publish.
    """
    build = _step("Build all packages")
    assert "date -u +%Y%m%d%H%M%S" in build, "no UTC timestamp in the version suffix"
    assert "git rev-parse --short" in build, "no commit sha in the version suffix"
    assert "GITHUB_RUN_ID" in build, (
        "the suffix has no run id, so two runs of the same commit in the same "
        "second produce the same version — which has already happened"
    )


def test_publishes_are_serialised():
    """They share one aptly database and one bucket. Two at once interleave on
    that state and the loser persists a database missing the winner's packages."""
    wf = yaml.safe_load(TEXT)
    c = wf.get("concurrency")
    assert c, "publish.yml has no concurrency group — publishes can overlap"
    assert c.get("cancel-in-progress") is False, (
        "a publish partway through uploading must not be cancelled, or the "
        "bucket is left half-updated"
    )


def test_the_sync_refuses_to_overwrite_an_existing_pool_path():
    """Uniqueness is an assumption until something checks it. The publish must
    fail rather than quietly poison a path the edge will hold for a year."""
    sync = _step("Sync repo to R2")
    assert "head-object" in sync, \
        "nothing verifies that the pool paths this run publishes are actually new"
    assert "exit 1" in sync, "a collision must fail the publish, not warn"


def test_the_cdn_purge_is_not_silently_skipped():
    """The purge is the documented repair path for a poisoned pool path. It was
    gated on `if: vars.CLOUDFLARE_ZONE_ID != ''`, so with no zone id configured
    the step never ran — and the warning it contains, which was supposed to
    announce exactly that, never ran either. It showed up as a grey skip on a
    green publish and read as benign for months."""
    assert "if" not in STEPS["Purge Cloudflare cache"], (
        "the purge step is gated again — a missing zone id will be a silent "
        "skip instead of a warning, which is how this went unnoticed"
    )
    assert "::warning::" in _step("Purge Cloudflare cache"), \
        "an unconfigured purge must say so out loud"


def test_pool_is_still_published_immutable():
    """If this ever stops being true the uniqueness requirement relaxes — and
    the reasoning in every comment above goes stale. Fail so someone revisits."""
    sync = _step("Sync repo to R2")
    assert "immutable" in sync, \
        "pool/ is no longer immutable — revisit why the version must be unique"


@pytest.mark.skipif(not subprocess.run(["which", "dpkg"], capture_output=True).returncode == 0,
                    reason="dpkg not available")
@pytest.mark.parametrize("older", [
    "0.1.6+ci49",       # what the collision shipped
    "0.1.6+ci99999",    # any run number this scheme could ever reach
    "0.1.6",            # an unstamped local build
    "0.1.5+ci47",       # the previous release
])
def test_the_new_scheme_sorts_as_an_upgrade_over_everything_in_the_wild(older):
    """Machines are sitting on +ci<run_number> right now. If the replacement
    did not sort above it, apt would see no upgrade and the repair would not
    reach them — the failure would just go quiet instead of getting fixed."""
    newer = "0.1.6+ci20261106190000.gbc2f20a"
    assert subprocess.run(
        ["dpkg", "--compare-versions", newer, "gt", older]
    ).returncode == 0, f"{newer} does not sort above {older}"


@pytest.mark.skipif(not subprocess.run(["which", "dpkg"], capture_output=True).returncode == 0,
                    reason="dpkg not available")
def test_two_builds_a_second_apart_are_ordered():
    a = "0.1.6+ci20261106190000.gaaaaaaa"
    b = "0.1.6+ci20261106190001.gbbbbbbb"
    assert subprocess.run(["dpkg", "--compare-versions", b, "gt", a]).returncode == 0
