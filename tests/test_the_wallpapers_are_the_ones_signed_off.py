"""The shipped wallpapers are pinned to the rendering the user approved.

This file exists because the artwork changed twice under someone who never
asked for it to change. The request was for screensavers. What happened instead:

    0.1.5  wide brand blooms added under every linework style, so the art would
           survive the lock screen's 60px blur
    0.1.6  stroke widths re-authored in screen pixels, to fix hairlines going
           sub-pixel on a 1440-wide laptop

Both were defensible on their own terms and neither was asked for. The second
made the contours visibly heavy on a large panel ("these lines are way too
prominent"), and because the files keep their names and are replaced in place,
there was no way to go back — the picker offers one "Sysible Topographic" and
its bytes had simply changed underneath.

So the shipped set is frozen at the 28 August 2026 field art (commit 6cf23da0),
verified byte for byte against the machine it was approved on.

0.1.8 then adds CLOUD to the banner tagline, which was the one thing that WAS
asked for. The field art is untouched and that is provable rather than
asserted: the banner is drawn on top as a separate step, so the art underneath
was reconstructed from the renderer at 6cf23da0 and re-encoded to a file
byte-identical to the one that shipped. Only then was a new banner drawn on it.
The pixels that differ sit in a band at x 10.8-35.0%, y 85.2-86.7% — the
tagline row, nothing else. The wordmark and the green rule are identical.

The result is byte-identical to commit a243a43b, the 31 August rendering, which
was exactly this: the same art carrying the newer tagline.

These hashes are the agreement. The wallpapers are NOT regenerated from
branding/wallpapers/render_wallpapers.py as part of a build — that renderer has
moved on, and re-running it would produce different art. Regenerating shipped
artwork is a product decision that needs sign-off, not a refactor. If you change
these files, this test fails, and that failure is the point: say who asked.
"""
import hashlib
from pathlib import Path

import pytest

BACKGROUNDS = Path(__file__).resolve().parents[1] / "packages/sysible-artwork/backgrounds"

# sha256 of each shipped wallpaper, as approved. Taken from the user's own
# machine (`sha256sum /usr/share/backgrounds/sysible/*.jpg`) and matched back to
# commit 6cf23da0, so this is the rendering they have been looking at since
# August — not merely "some older version".
APPROVED = {
    "sysible-cosmos-light.jpg":              "9caf2c9fc010c203bc07402bee7e948425381d47118fdfbad4af21cf4271f46d",
    "sysible-cosmos.jpg":                    "7fa2db42e986f251e133d6f556d4fb6a67a325e84dc19ade8b075acc0a743ab2",
    "sysible-neural-light.jpg":              "c1b1cfbe77ca0655e7b2a85204251726a2bf63bb1a17c2f0c09107b80fe8e78c",
    "sysible-neural.jpg":                    "9a1f0b8f5710885289c4eab8f874505794bd40cf26c4f0a687cd95fb63952981",
    "sysible-roads-light.jpg":               "1b7a8a70789a21f78b1c663984891ca15cbcaf7a6293808d30a13c570985e500",
    "sysible-roads.jpg":                     "27fbb4b278e7f2b2db11410756636a459b0dd87cb8e00e9246875cd82bd6d3fe",
    "sysible-topographic-light.jpg":         "f12401b47aff09930e92f6f4fc0c65fdd245dbea336ed33541a57c96e3ec6060",
    "sysible-topographic-ridge-light.jpg":   "74d50d4e36d8bf73b86c1d1915a2beb240712b86d931c9b30b961b9a7bfa2029",
    "sysible-topographic-ridge.jpg":         "bdd1e9e6d65499f5f0b08bb7f5e3bdc4da22ac66012b31a73bbcfb3403a29dd4",
    "sysible-topographic.jpg":               "2b8d30c1e9b3e73daf3057815c1abd86b67baf0f1f3b88bd4b884b2b9f21eaca",
}


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize("name,want", sorted(APPROVED.items()))
def test_the_shipped_wallpaper_is_the_approved_one(name, want):
    p = BACKGROUNDS / name
    assert p.exists(), f"{name} is no longer shipped — that removes it from the picker"
    got = _sha(p)
    assert got == want, (
        f"{name} is not the approved rendering.\n"
        f"  approved: {want}\n"
        f"  shipped:  {got}\n"
        "The wallpapers are pinned deliberately. If this change is wanted, update "
        "APPROVED in this file in the same commit and say in the message who asked."
    )


def test_no_wallpaper_is_added_or_removed_without_saying_so():
    """A file appearing or vanishing changes what the picker offers. Removing one
    is worse than it looks: dpkg deletes it from installed machines, including
    out from under a live picture-uri, and the user cannot pick it back."""
    on_disk = {p.name for p in BACKGROUNDS.glob("*.jpg")}
    assert on_disk == set(APPROVED), (
        "the shipped wallpaper set changed\n"
        f"  added:   {sorted(on_disk - set(APPROVED))}\n"
        f"  removed: {sorted(set(APPROVED) - on_disk)}"
    )


def test_every_shipped_wallpaper_is_offered_in_the_picker():
    """A wallpaper that ships but is not in the XML cannot be selected, and one
    in the XML that does not ship is a dead tile."""
    xml = (BACKGROUNDS.parent / "gnome-background-properties/sysible.xml").read_text()
    for name in APPROVED:
        assert name in xml, f"{name} ships but is not selectable in the picker"
