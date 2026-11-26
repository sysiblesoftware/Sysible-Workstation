"""The release page a user lands on must describe the release they are getting.

The body in iso.yml is hard-coded, and it opened with a literal

    ### New in 1.0.5

followed by 1.0.5's bullets. Nothing derives that from the tag being published,
so cutting 1.0.6 would have produced a release page headed "New in 1.0.5",
describing changes a user already had, and saying nothing about the one that
matters — that the installer is no longer the text-mode one.

Exactly the shape of the website's own "1.0.3 Ignition": a version written by
hand into a file that is not rewritten when a release is cut.

The heading now comes from the tag. These guards keep it that way, and keep the
things a user needs in order to USE the download present.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISO_YML = ROOT / ".github/workflows/iso.yml"


def _body():
    """The release body block from the publish step."""
    s = ISO_YML.read_text(encoding="utf-8")
    m = re.search(r"\n          body: \|\n(.*?)\n          fail_on_unmatched_files:", s, re.S)
    assert m, "could not find the release body in iso.yml"
    return m.group(1)


def test_the_heading_is_not_a_hard_coded_version():
    body = _body()
    m = re.search(r"###\s*New in\s*(.+)", body)
    assert m, "the release body has no 'New in' heading"
    heading = m.group(1).strip()
    assert not re.fullmatch(r"v?\d+\.\d+(\.\d+)?", heading), (
        f"the release heading is the literal version {heading!r}. It is not "
        f"rewritten when a tag is cut, so the next release would be published "
        f"under the previous release's number. Derive it from the tag.")
    assert "${{" in heading and "tag" in heading, (
        f"the heading should come from the tag being published, got {heading!r}")


# A literal version is fine when it is EXPLICITLY historical -- "Earlier, in
# 1.0.8", "Fixed in 1.0.6". Those label a past release and do not go stale; the
# whole point of the heading being templated is that the CURRENT release is
# never written by hand. Workstation's notes accumulate that history on purpose,
# so the check is for present-tense version claims only.
# A literal version is fine when it is EXPLICITLY historical -- "Earlier, in
# 1.0.8", "Fixed in 1.0.6", "From 1.0.4". Those label a past release and cannot
# go stale; the point of templating the heading is that the CURRENT release is
# never written by hand. Workstation's notes accumulate that history on purpose.
#
# Checked per PARAGRAPH, not per line: the marker sits on a paragraph's first
# line and the version often lands on a wrapped continuation, so a line-wise
# check flags the continuation and misses the relationship entirely.
# A version named as HISTORY cannot go stale -- "fixed in 1.0.6" stays true
# forever. A version presented as the CURRENT release is the thing that rots,
# and that is what this guards.
#
# Three things this got wrong before, each of which let a stale claim through or
# blocked a true one:
#
#   * The marker was looked for anywhere in the same PARAGRAPH. The marker list
#     contains "from", "since" and "before" -- ordinary English words -- so one
#     "cloned from GitHub" exempted every version number in the paragraph, and a
#     hand-written "New in 1.0.99" sailed through. The marker now has to sit
#     immediately before the version.
#   * "new in" was listed as historical. It is the opposite: it introduces the
#     release being published, so it is rejected outright.
#   * A second version in a conjunction -- "nothing from 1.0.6 or 1.0.7" -- has
#     no marker of its own, and was flagged. A chain of versions inherits the
#     marker in front of the first one.
# A paragraph that OPENS with a historical marker is historical throughout, so a
# past release can be the subject of a later sentence in it:
#
#     **Fixed in 1.0.6 -- wallpapers back to the rendering people liked.**
#     1.0.5 widened the contour strokes to stop them going sub-pixel ...
#
# This is not the old paragraph-wide scan that let everything through: the marker
# has to be the paragraph's OPENING, not merely somewhere inside it, and "new in"
# is not a historical opener.
HISTORICAL_OPENER = re.compile(
    r"^[\s*_#]*(?:earlier,?\s+in|fixed\s+in|from|since|before)\b", re.I)


def _paragraph_of(body, pos):
    start = body.rfind("\n\n", 0, pos)
    start = 0 if start < 0 else start + 2
    end = body.find("\n\n", pos)
    return body[start : len(body) if end < 0 else end]


CURRENT_CLAIM = re.compile(r"\bnew\s+in\s+v?$", re.I)
HISTORICAL_BEFORE = re.compile(
    r"(?:earlier,?\s+in|fixed\s+in|arrived\s+in|upgrading\s+from"
    r"|if\s+you\s+are\s+on|if\s+you\s+installed"
    r"|from|since|before|in)\s+v?$", re.I)
LICENCE_BEFORE = re.compile(r"(BUSL|GPL|LGPL|AGPL|MPL|Apache)[- ]?$")
# "1.0.6 or", "1.0.2, " -- strip these so a chain inherits the first marker.
LINK = re.compile(r"\d+\.\d+\.\d+\s*(?:,|or|and|to|through|[-\u2013\u2014])\s*$", re.I)
VERSION = re.compile(r"(?<![\w.-])\d+\.\d+\.\d+(?![\w.-])")


def test_no_version_number_is_written_into_the_notes_by_hand():
    """A literal x.y.z presented as the CURRENT release goes stale silently."""
    body = _body()
    bad = []
    for m in VERSION.finditer(body):
        head = body[: m.start()]
        line = head[head.rfind("\n") + 1 :] + m.group(0)
        if "${{" in line:                      # the interpolated heading
            continue
        if LICENCE_BEFORE.search(head):        # BUSL-1.1 is a licence version
            continue
        if CURRENT_CLAIM.search(head):         # "New in 1.0.99" -- the stale claim
            bad.append(f"  {line.strip()[:100]}")
            continue
        chain = head                           # "from 1.0.6 or <here>"
        while True:
            mm = LINK.search(chain)
            if not mm:
                break
            chain = chain[: mm.start()]
        if HISTORICAL_BEFORE.search(chain):    # "fixed in 1.0.6" -- cannot rot
            continue
        if HISTORICAL_OPENER.search(_paragraph_of(body, m.start()).lstrip()):
            continue
        bad.append(f"  {line.strip()[:100]}")
    assert not bad, (
        "these present a version as the current release, so the next build "
        "publishes notes describing the wrong one:\n" + "\n".join(bad)
    )


@pytest.mark.parametrize("needed", [
    "SHA256SUMS",            # how to verify
    "sysible.com/security",  # where the key fingerprint lives
    "REASSEMBLE",            # how to put the parts together
    "cat sysible-workstation-",   # how to join the parts
])
def test_the_notes_tell_a_user_how_to_use_the_download(needed):
    """The ISO ships split across several files. Without these a release is a
    pile of .part files with no instructions."""
    assert needed in _body(), (
        f"the release notes no longer mention {needed!r}, which a user needs in "
        f"order to verify or reassemble the download")


def test_both_authenticity_checks_are_given():
    """There are TWO things to verify -- the parts before joining them, and the
    whole ISO after -- and each has its own signed manifest.

    A plain `"gpg --verify" in body` check passed while one of them was
    deleted, because the other was still there. Name them separately.
    """
    body = _body()
    for what, needle in (
            ("the downloaded parts", "gpg --verify SHA256SUMS.<arch>.parts.gpg SHA256SUMS.<arch>.parts"),
            ("the reassembled ISO", "gpg --verify SHA256SUMS.<arch>.gpg SHA256SUMS.<arch>")):
        assert needle in body, (
            f"the notes no longer say how to check the authenticity of {what}")
    for what, needle in (
            ("the downloaded parts", "sha256sum -c SHA256SUMS.<arch>.parts"),
            ("the reassembled ISO", "sha256sum -c SHA256SUMS.<arch>")):
        assert needle in body, (
            f"the notes no longer say how to checksum {what}")


def test_the_publish_step_refuses_to_ship_missing_files():
    """fail_on_unmatched_files keeps a release from being published with some of
    its parts or checksums silently absent."""
    s = ISO_YML.read_text(encoding="utf-8")
    assert re.search(r"fail_on_unmatched_files:\s*true", s), (
        "a release could publish with assets missing and nobody would be told")
