"""The shared aptly database must not be able to come back half-written.

On 25 November every publish from every product started failing with:

    ERROR: unable to switch: unable to load package with key
      Pall sysible-app-connect 0.1.0+ci20261125182740.r45675190193... : key not found

The archive was fine. The DATABASE referenced a package it no longer held, and
that database is shared by Sysible Server, Sysible Workstation and anything
else publishing into the same suite — so one product's broken entry blocked
every product's publish.

It arrived there because the database travelled as `aws s3 sync` over a LevelDB
directory, with no --delete in either direction:

  * nothing was ever removed from the bucket, so every generation LevelDB had
    ever written piled up there (measured locally: 10 files after one publish,
    22 after four);
  * a directory sync has no consistent snapshot, so a restore could assemble a
    database whose manifest referenced data files it never fetched.

Two things fix it. The database moves as ONE object, because an S3 PUT is
atomic. And a publish that still meets a dangling reference repairs itself.

The repair REBUILDS the repo from the package pool rather than removing the
offending package, for a reason worth recording: every aptly CLI path loads a
repo's whole package set before doing anything, so `repo remove`, `repo add`
and `repo show -with-packages` all die on the very entry that needs removing.
Verified against a database corrupted on purpose — by raw package ref, by name
and by query, all three fail identically. aptly cannot repair this from the
command line. The pool holds the real .deb files, so rebuilding from it also
RESTORES the package instead of evicting it, including packages belonging to
other products that this run has no copy of.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/publish.yml"
WF_TEXT = WF.read_text(encoding="utf-8")
STEPS = {s["name"]: s for s in yaml.safe_load(WF_TEXT)["jobs"]["publish"]["steps"] if "name" in s}
STATE = ROOT / "scripts/aptly-state.sh"
REPAIR = ROOT / "scripts/repair-aptly-db.sh"
PUBLISH = ROOT / "scripts/publish-repo.sh"


def _code(p):
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = re.sub(r"(^|\s)#.*$", "", line)
        if s.strip():
            out.append(s)
    return "\n".join(out)


def test_the_database_is_not_moved_with_a_directory_sync():
    """The regression itself."""
    for name in ("Restore aptly database", "Persist aptly database"):
        body = STEPS[name].get("run", "")
        assert "aws s3 sync" not in body, (
            f"{name!r} is back to a directory sync of the aptly database. That "
            f"has no consistent snapshot and never deletes, which is how a "
            f"restore produced a database referencing data it did not have."
        )
        assert "aptly-state.sh" in body, f"{name!r} no longer uses the atomic helper"


def test_a_failed_restore_is_fatal_not_an_empty_database():
    """If a broken fetch read as 'first run', the publish would rebuild an empty
    archive and then persist it over the real one."""
    c = _code(STATE)
    assert "exit 1" in c, "aptly-state.sh never fails"
    assert re.search(r"404|NoSuchKey|Not Found", c), (
        "nothing distinguishes 'no database yet' from 'the fetch broke', so any "
        "error would be treated as a first publish"
    )


def test_the_previous_database_is_kept_before_being_replaced():
    c = _code(STATE)
    assert "backup" in c, "persist overwrites the only copy with no way back"


def test_a_dangling_reference_triggers_a_repair():
    c = _code(PUBLISH)
    assert "key not found" in c, "nothing detects a dangling package reference"
    assert "repair-aptly-db.sh" in c, "a dangling reference no longer repairs itself"


def test_the_repair_rebuilds_from_the_pool_and_does_not_evict():
    """A targeted `aptly repo remove` cannot work here — it loads the package
    set first and dies on the same entry — and would drop another product's
    package out of the archive even if it did."""
    c = _code(REPAIR)
    assert "repo drop" in c and "repo create" in c and "repo add" in c, \
        "the repair no longer rebuilds the repo"
    assert "pool" in c, "the repair does not read the package pool"
    assert "aptly repo remove" not in c, (
        "the repair is removing packages again. aptly cannot remove a package "
        "it cannot load, and removing would evict other products' packages."
    )


def test_the_repair_keeps_only_the_newest_build_of_each_package():
    """The pool keeps every +ci build ever published. Re-adding all of them
    would publish every historical version and grow the index without bound."""
    c = _code(REPAIR)
    assert "dpkg --compare-versions" in c, \
        "nothing compares versions, so every historical build would be re-added"


@pytest.mark.skipif(shutil.which("aptly") is None or shutil.which("dpkg-deb") is None,
                    reason="aptly/dpkg-deb not available")
def test_the_repair_actually_picks_the_newest(tmp_path):
    """Run it. Three builds of one package in the pool, newest must win."""
    root = tmp_path / "db"
    (root / "pool/ab/cd").mkdir(parents=True)
    (tmp_path / ".aptly.conf").write_text(
        '{"rootDir": "%s", "architectures": ["amd64","arm64"], "gpgProvider": "gpg"}' % root,
        encoding="utf-8")
    vers = ["1.0+ci20261101000000.r1.ga", "1.0+ci20261125000000.r3.gc",
            "1.0+ci20261115000000.r2.gb"]
    for i, v in enumerate(vers):
        d = tmp_path / f"b{i}/DEBIAN"
        d.mkdir(parents=True)
        (d / "control").write_text(
            f"Package: pkg-x\nVersion: {v}\nArchitecture: all\n"
            "Maintainer: t <t@t>\nDescription: t\n", encoding="utf-8")
        subprocess.run(["dpkg-deb", "-b", str(tmp_path / f"b{i}"),
                        str(root / f"pool/ab/cd/{i}_pkg-x_{v}_all.deb")],
                       check=True, capture_output=True)
    env = {"HOME": str(tmp_path), "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin")}
    r = subprocess.run([str(REPAIR), "sysible-stable"], capture_output=True, text=True,
                       env=env, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    show = subprocess.run(["aptly", "repo", "show", "-with-packages", "sysible-stable"],
                          capture_output=True, text=True, env=env)
    assert "1.0+ci20261125000000.r3.gc" in show.stdout, show.stdout
    for stale in ("r1.ga", "r2.gb"):
        assert stale not in show.stdout, f"stale build {stale} was re-added:\n{show.stdout}"
