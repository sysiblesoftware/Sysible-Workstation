"""What the machine shows while it sits idle and locked.

There is no screensaver on this image and there cannot be one: GNOME 43 on
Wayland has no screensaver framework, and xscreensaver cannot draw over a
Wayland session. What an idle Workstation actually shows is the DESKTOP
WALLPAPER, blurred and dimmed by the shell.

The trap is that org.gnome.desktop.screensaver still has a picture-uri key.
Setting it looks exactly like configuring the lock screen and does nothing:
gnome-shell 43's unlock dialog builds its BackgroundManager with no
settingsSchema, so it reads org.gnome.desktop.background (js/ui/unlockDialog.js,
js/ui/background.js). The shell then applies BlurEffect sigma 60 at brightness
0.55.

A 60-pixel blur erases line art, and line art is what these wallpapers are.
Measured on the set as shipped in v1.0.3, three of the four dark styles came
out of that treatment at a mean luminance of 8-10 out of 255 — a black
rectangle with a clock on it, on a machine whose desktop is anything but.

So these tests apply the shell's real treatment to the real shipped files and
assert the result is still Sysible:

  * it must not be black;
  * it must still carry brand colour, not just grey;
  * and it must stay dark enough BEHIND THE CLOCK that white text reads.

Run: pytest tests/test_the_lock_screen_is_not_a_black_rectangle.py
"""
import pathlib

import pytest

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
ART = REPO / "packages/sysible-artwork/backgrounds"

# gnome-shell 43, js/ui/unlockDialog.js
BLUR_SIGMA = 60
BLUR_BRIGHTNESS = 0.55
SCREEN = (1920, 1080)

# Every DARK style. The light ones are not checked for lift: they start bright,
# and adding glow there would cost the clock its contrast instead of buying it.
DARK = ["sysible-topographic", "sysible-topographic-ridge",
        "sysible-neural", "sysible-cosmos", "sysible-roads"]


def _lock(name):
    """The wallpaper as the lock screen really renders it."""
    im = Image.open(ART / f"{name}.jpg").convert("RGB")
    # picture-options='zoom' — cover-fit, crop, never distort.
    sw, sh = SCREEN
    r = max(sw / im.width, sh / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    l, t = (im.width - sw) // 2, (im.height - sh) // 2
    im = im.crop((l, t, l + sw, t + sh))
    im = im.filter(ImageFilter.GaussianBlur(BLUR_SIGMA))
    return ImageEnhance.Brightness(im).enhance(BLUR_BRIGHTNESS)


def _luma(im):
    return np.asarray(im.convert("L"), dtype=np.float32)


# What each approved style actually measures under the shell's own treatment
# (GaussianBlur sigma 60 x scale, brightness 0.55), on the 28 August artwork the
# user restored in 0.1.7. These are a RECORD, not a target.
#
# The linework styles sit at 7-10, which is a near-black field with a clock on
# it. 0.1.5 had lifted them past 12 with wide brand blooms; that was part of an
# artwork change nobody asked for, and it went back out with the rest of it.
# Cosmos has always cleared it alone, because it is built from large soft nebula
# forms rather than strokes — a 60px blur has nothing fine to destroy.
APPROVED_LOCK_LUMA = {
    "sysible-topographic": 7.2,
    "sysible-topographic-ridge": 8.8,
    "sysible-neural": 9.5,
    "sysible-cosmos": 14.8,
    "sysible-roads": 8.2,
}


@pytest.mark.parametrize("name", sorted(APPROVED_LOCK_LUMA))
def test_the_lock_screen_brightness_has_not_drifted(name):
    """The brightness floor this file once enforced is withdrawn — the user
    chose the desktop art over lock-screen legibility, knowingly.

    The measurement stays live so the number cannot move unnoticed. It moves
    only if the shipped wallpapers change, and those are pinned in
    test_the_wallpapers_are_the_ones_signed_off.py.
    """
    mean = float(_luma(_lock(name)).mean())
    want = APPROVED_LOCK_LUMA[name]
    assert abs(mean - want) <= 0.5, (
        f"{name} locks at {mean:.1f}/255, approved is {want}. The wallpaper "
        f"behind it is not the one that was signed off — check "
        f"test_the_wallpapers_are_the_ones_signed_off.py and say who asked."
    )


def test_no_dead_screensaver_image_config():
    """A picture-uri under org.gnome.desktop.screensaver is the trap this whole
    file exists to document: it reads as configuring the lock screen and does
    nothing in GNOME 43."""
    for db in (REPO / "live-build/config/includes.chroot/etc/dconf/db").rglob("*"):
        if not db.is_file():
            continue
        text = db.read_text(encoding="utf-8", errors="replace")
        if "[org/gnome/desktop/screensaver]" not in text:
            continue
        block = text.split("[org/gnome/desktop/screensaver]", 1)[1].split("\n[", 1)[0]
        live = [ln for ln in block.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]
        bad = [ln for ln in live if ln.split("=")[0].strip()
               in ("picture-uri", "picture-uri-dark", "picture-options")]
        assert not bad, (
            f"{db}: {bad} under org.gnome.desktop.screensaver does nothing in "
            f"GNOME 43 — the lock screen reads org.gnome.desktop.background")


def test_the_wallpaper_the_desktop_defaults_to_is_one_of_the_checked_ones():
    """These tests only prove the art they look at. If the default wallpaper
    were some file outside that set, the lock screen could still be black."""
    cfg = (REPO / "live-build/config/includes.chroot/etc/dconf/db/local.d"
                  "/00-sysible-desktop").read_text(encoding="utf-8")
    block = cfg.split("[org/gnome/desktop/background]", 1)[1].split("\n[", 1)[0]
    dark = [ln for ln in block.splitlines() if ln.startswith("picture-uri-dark=")]
    assert dark, "no dark wallpaper default"
    stem = dark[0].rsplit("/", 1)[-1].rstrip("'").removesuffix(".jpg")
    assert stem in DARK, (
        f"the default dark wallpaper is {stem!r}, which no lock-screen test "
        f"covers — add it to DARK or the lock screen is unverified")
