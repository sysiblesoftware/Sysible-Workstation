"""A release must push its packages to the STABLE apt suite, in the same run.

The `tags: ['v*']` trigger on publish.yml cannot do it, and never has. The
release is cut by softprops/action-gh-release using GITHUB_TOKEN, and GitHub
deliberately refuses to start workflow runs from refs pushed with that token.
So the tag trigger has never once fired. The only thing that ever updated the
apt repo was a push to main, which publishes to DEV -- meaning the STABLE suite,
which every installed machine is pointed at, kept whatever it happened to have
while release after release came and went.

Sysible Workstation hit this and fixed it by having iso.yml CALL publish.yml:
a reusable workflow is not an event, so nothing suppresses it. Server shipped
with the trigger that cannot fire and no caller, so its stable suite was frozen
too. This file pins the working shape in both products, because the broken one
looks completely reasonable -- there IS a tag trigger, it is just inert.
"""
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
ISO = ROOT / ".github" / "workflows" / "iso.yml"
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"


def _load(p):
    d = yaml.safe_load(p.read_text())
    # PyYAML parses the bare key `on:` as the boolean True.
    d["on"] = d.get("on", d.get(True))
    return d


def test_the_release_build_publishes_to_the_apt_repo():
    jobs = _load(ISO)["jobs"]
    apt = [j for n, j in jobs.items() if "publish" in n]
    assert apt, ("iso.yml has no job that publishes packages, so a release "
                 "never reaches the apt repo")
    job = apt[0]
    assert str(job.get("uses", "")).endswith("publish.yml"), job
    assert job.get("with", {}).get("suite") == "stable", (
        f"the release publishes to {job.get('with', {}).get('suite')!r}, not stable")


def test_publish_can_be_called_rather_than_only_triggered():
    """The whole fix. Without workflow_call there is nothing iso.yml can
    invoke, and the tag trigger is inert."""
    on = _load(PUBLISH)["on"]
    assert "workflow_call" in on, (
        "publish.yml takes no workflow_call, so a release build cannot invoke it; "
        "the tags trigger cannot fire on a GITHUB_TOKEN push")
    assert "suite" in (on["workflow_call"] or {}).get("inputs", {}), on["workflow_call"]


def test_it_publishes_once_per_release_not_once_per_arch():
    """The packages are Architecture: all. Two concurrent publishes interleave
    on the shared aptly database, and the second to finish persists one that
    never saw the first's packages."""
    jobs = _load(ISO)["jobs"]
    cond = next(j["if"] for n, j in jobs.items() if "publish" in n)
    assert "amd64" in cond, f"nothing stops this running on every arch: {cond}"
    assert "release" in cond or "refs/tags/" in cond, cond


def test_publishes_are_serialised():
    """A push to main (dev) and the release's own stable publish of the same
    commit overlap on that same shared database."""
    d = _load(PUBLISH)
    conc = d.get("concurrency")
    assert conc, "publish.yml has no concurrency guard"
    group = conc["group"] if isinstance(conc, dict) else conc
    assert group, conc
    if isinstance(conc, dict):
        assert conc.get("cancel-in-progress") is False, (
            "a publish killed partway through leaves the bucket half-updated")


def test_the_reason_is_written_down_where_it_will_be_read():
    """This is invisible in behaviour -- the tag trigger exists and simply does
    nothing -- so the next person to touch these files needs the reason, not
    just the shape."""
    text = PUBLISH.read_text()
    assert "GITHUB_TOKEN" in text, \
        "nothing explains why the tag trigger cannot fire"


# ---------------------------------------------------------------------------
# A publish must not poison the CDN
# ---------------------------------------------------------------------------
# Reported from a fresh Workstation install, on `apt upgrade`:
#
#   Err:1 .../sysible-stable/main amd64 sysible-cli all 0.3.2
#     File has unexpected size (22056 != 22062). Mirror sync in progress?
#
# Note the filename in that error: sysible-cli_0.3.2_all.deb, with NO +ci
# suffix. aptly names pool files by VERSION, not by content, so republishing
# the same version with different bytes overwrites that URL -- while the edge,
# told the path is immutable, keeps serving the old copy against a fresh index.
# apt validates size and hash, so it fails outright.
#
# Sysible Workstation hit this, root-caused it and fixed it; Sysible Server was
# left publishing at fixed paths with no stamp, no guard and no purge. The two
# pipelines are the same pipeline, so these properties are asserted in both.

PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"


def _publish_text():
    return PUBLISH.read_text()


def test_every_package_is_published_at_a_fresh_path():
    """The root-cause fix: a unique, monotonic version suffix, so a rebuild can
    never land on a path the CDN has already cached."""
    t = _publish_text()
    assert "SYSIBLE_VERSION_SUFFIX" in t, (
        "packages publish at a fixed version path; a same-version rebuild will "
        "collide with the immutably-cached .deb at the edge")


def test_the_suffix_is_actually_unique_not_just_a_run_number():
    """`+ci<run_number>` is NOT unique: run_number is per-workflow, and two
    workflows reach this job (publish.yml directly, and iso.yml calling it), so
    their counters collide on different source trees. That is what produced the
    failure the scheme exists to prevent."""
    t = _publish_text()
    m = [l for l in t.splitlines() if "SYSIBLE_VERSION_SUFFIX=" in l and "+ci" in l]
    assert m, "no version suffix is constructed"
    line = m[0]
    assert "GITHUB_RUN_ID" in line, (
        f"the suffix is not globally unique: {line.strip()}")


def test_an_existing_pool_path_is_refused_rather_than_overwritten():
    """pool/ is uploaded immutable -- a promise that a URL's bytes never
    change. Breaking it poisons the edge for a year, silently. The guard turns
    that into a failed build instead."""
    t = _publish_text()
    assert "already exists in the bucket" in t, \
        "nothing stops this run overwriting an immutably-cached pool path"
    assert "head-object" in t, "the guard does not actually check the bucket"


def test_the_index_is_never_cached():
    """dists/ is what apt fetches first and validates everything against."""
    t = _publish_text()
    assert "no-cache" in t, "the Release/Packages index may be served stale"


def test_the_cdn_is_purged():
    t = _publish_text()
    assert "Purge Cloudflare cache" in t, "a stale edge is never cleared"


def test_the_suite_resolves_when_a_release_calls_this_workflow():
    """`github.event.inputs` is null for a workflow_call, so a release-triggered
    publish would silently fall through to the DEV suite -- publishing a release
    to the channel nobody installs from. `inputs` resolves for both."""
    t = _publish_text()
    assert "github.event.inputs.suite" not in t, (
        "github.event.inputs is null on a workflow_call; the release publish "
        "would silently go to dev")
    assert "inputs.suite" in t, "the suite input is not read at all"
