"""Wallpaper strokes have to be at least a pixel wide on the screen they land on.

Reported from a MacBook Air, of art that had just been upgraded correctly:
"the lines are kind of fuzzy".

It was not compression and it was not the downscale. Both were measured: a
master re-encoded at JPEG q92 and scaled 7680 -> 1440 keeps essentially all of
its line signal. The fault was geometry. Stroke widths were authored as a
fraction of the MASTER — "the site's 0.9px hairline" at 8K is 5 canvas pixels
— and the master is almost never what you look at. GNOME scales it to the
panel, and on a 1440x900 laptop those 5px become 0.94px:

    contour base      5px canvas -> 0.94px      <- under a pixel
    neural edge       2px canvas -> 0.38px      <- a rumour of a line
    roads             3px canvas -> 0.56px

A display cannot draw a line narrower than a pixel. It averages it into its
neighbours, and a field of them reads as grey haze rather than as lines.

So widths are declared in SCREEN pixels at a reference panel (see stroke() in
the renderer) and converted for whichever master is rendered. These tests hold
that line: every stroke the renderer draws must still be a line on the smallest
panel Workstation ships against.

Run: pytest tests/test_lines_survive_a_laptop_screen.py
"""
import pathlib
import re
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image, ImageFilter  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
RENDERER = REPO / "branding/wallpapers/render_wallpapers.py"
ART = REPO / "packages/sysible-artwork/backgrounds"
sys.path.insert(0, str(RENDERER.parent))


@pytest.fixture(scope="module")
def R():
    sys.argv = ["render_wallpapers.py", "--test"]
    import render_wallpapers
    return render_wallpapers


# ---------------------------------------------------------------------------
# the conversion itself
# ---------------------------------------------------------------------------
def test_a_stroke_measures_what_it_asks_for(R):
    """stroke(ow, px) must land at px on a reference-width display, for any
    master. The whole point is that the master stops mattering."""
    for master in (1440, 1920, 2560, 3840, 7680):
        for ss in (1, 2):
            ow = master * ss
            for want in (1.0, 1.25, 1.75, 2.1):
                w = R.stroke(ow, want)
                # canvas -> master -> reference screen
                got = (w / ss) * (R.REFERENCE_SCREEN_W / master)
                assert abs(got - want) <= 0.5, (
                    f"master={master} ss={ss} asked {want}px, got {got:.2f}px")


def test_a_stroke_is_never_zero(R):
    """A zero-width line draws nothing. Rounding must never reach it."""
    for ow in (640, 1440, 7680, 15360):
        assert R.stroke(ow, 0.01) >= 1


# ---------------------------------------------------------------------------
# every stroke the renderer actually draws
# ---------------------------------------------------------------------------
def _stroke_calls():
    """The screen widths the renderer asks for, read out of its own source."""
    src = RENDERER.read_text(encoding="utf-8")
    calls = re.findall(r"\bstroke\(\s*\w+\s*,\s*([0-9.]+)\s*\)", src)
    assert calls, "no stroke() calls found — has the renderer been rewritten?"
    return [float(c) for c in calls]


def test_every_stroke_is_at_least_a_pixel_on_the_smallest_panel():
    """Under 1.0 and it is not a line on that screen, whatever it is at 8K."""
    thin = [px for px in _stroke_calls() if px < 1.0]
    assert not thin, (
        f"stroke widths {thin} are below one screen pixel on a "
        f"1440-wide panel — they will render as haze, which is "
        f"the defect this file exists for")


def test_no_stroke_bypasses_the_conversion():
    """The trap is writing width=max(1, int(W / 3600)) again: it looks precise
    and it silently means 'however thin the panel makes it'."""
    src = RENDERER.read_text(encoding="utf-8")
    # Any max(N, int(<width> / M)) shape, whether passed to width= directly or
    # parked in a variable first — which is how the roads grid's W/1500 (0.96px
    # on a laptop) slipped past the first version of this check.
    #
    # The marching-squares GRID resolution is the one legitimate use of that
    # shape: gw/gh are how many cells to sample the field at, not how thick to
    # draw. Everything else that divides the image width is a stroke.
    bad = [ln.strip() for ln in src.splitlines()
           if re.search(r"max\(\s*\d+\s*,\s*int\(\s*(?:round\(\s*)?(?:ow|W|w)\s*/\s*\d+", ln)
           and not re.match(r"\s*g[wh]\s*=", ln)]
    assert not bad, (
        "a stroke width is computed straight from the image width again; "
        "use stroke(ow, <px on screen>) so it survives the scale to a panel")


# ---------------------------------------------------------------------------
# ...and the shipped art, at the size it is actually looked at
# ---------------------------------------------------------------------------
def _at_laptop(name, sw=1440, sh=900):
    im = Image.open(ART / f"{name}.jpg").convert("RGB")
    r = max(sw / im.width, sh / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    l, t = (im.width - sw) // 2, (im.height - sh) // 2
    return im.crop((l, t, l + sw, t + sh))


def _line_pixels(im):
    """Share of pixels carrying contrast a display can actually show."""
    g = im.convert("L")
    a = np.asarray(g, dtype=np.float32)
    lo = np.asarray(g.filter(ImageFilter.GaussianBlur(2.5)), dtype=np.float32)
    return float((np.abs(a - lo) > 3.0).mean() * 100)


# REMOVED (0.1.7): the end-to-end check that the SHIPPED wallpapers read as
# lines at 1440x900.
#
# It measured the files in packages/sysible-artwork/backgrounds, and those are
# no longer what this renderer produces. The user restored the 28 August
# rendering — the stroke-width work below was part of an artwork change they did
# not ask for, and the heavier contours it produced were the complaint that
# ended it ("these lines are way too prominent").
#
# The shipped files are pinned by sha256 in
# tests/test_the_wallpapers_are_the_ones_signed_off.py, which is a stronger
# guarantee than a signal floor: it catches ANY change, not just a thinner one.
#
# Everything above still applies to the renderer itself, which was NOT reverted:
# if someone regenerates the artwork one day, stroke() is still the right way to
# ask for a width and these guards still hold them to it.
