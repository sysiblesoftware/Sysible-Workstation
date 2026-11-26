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
HISTORICAL = re.compile(r"\b(?:earlier,? in|fixed in|new in|from|since|before|arrived"
    r"|if you are on|if you installed|upgrading from)\b", re.I)
VERSION = re.compile(r"(?<![\w.-])\d+\.\d+\.\d+(?![\w.-])")


def test_no_version_number_is_written_into_the_notes_by_hand():
    """A literal x.y.z presented as the CURRENT release goes stale silently."""
    body = _body()
    bad = []
    for para in re.split(r"\n\s*\n", body):
        if "${{" in para or HISTORICAL.search(para):
            continue
        for m in VERSION.finditer(para):
            line = para[:m.start()].count("\n")
            if re.search(r"(BUSL|GPL|LGPL|AGPL|MPL|Apache)[- ]?$", para[:m.start()]):
                continue
            bad.append("  " + para.splitlines()[line].strip()[:100])
    assert not bad, (
        "these present a version as the current release:\n" + "\n".join(bad))


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
