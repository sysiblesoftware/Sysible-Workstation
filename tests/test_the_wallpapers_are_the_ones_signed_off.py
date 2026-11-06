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

So the shipped set is now frozen at the 28 August 2026 rendering (commit
6cf23da0), byte for byte, verified against the machine it was approved on.

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
    "sysible-cosmos.jpg":                   "f4c46ecf3a1baaff4675fdbbecf2e47d34a1d81b7d4a389cd7292d91cce3c6e4",
    "sysible-cosmos-light.jpg":             "17c2fbb4b498b7083b41424a573cdd790e267e335d2e3e204e30ee50a255ea15",
    "sysible-neural.jpg":                   "e778813c10a5abffaaf7d8e9e33a55883861ac8ad2e830b365f9a5df03b00ddf",
    "sysible-neural-light.jpg":             "92fc820ba293bcb014a99169233fe3c9bd899347a59427be62e1e59e8cdce2d6",
    "sysible-roads.jpg":                    "c2246ccc63ac3ae564372cb37eaf9d4d307b247b699907db99f2306d0d259a19",
    "sysible-roads-light.jpg":              "899032b052e89dd7aeb18a25c11a9d49fc9b0f7842c8371a5563cd53d7945b3f",
    "sysible-topographic.jpg":              "7fa6ddbdc1363a3526148e20c5e8837838dacc45126409a8944e6f326e93b935",
    "sysible-topographic-light.jpg":        "5cfda5eeee44974036a1d93acd7590379c00a89538141217bf4b1a11bc03a508",
    "sysible-topographic-ridge.jpg":        "95d703a0da90bfb286967ae92121dc4e096fc118778f4e781e60a18c02f92fd6",
    "sysible-topographic-ridge-light.jpg":  "4fe778fcfa75516b3ea254432d4526e2bbc113950d656afa132824787d9e4858",
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
