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


@pytest.mark.parametrize("name", DARK)
def test_it_is_not_a_black_rectangle(name):
    """The floor. Below about 12 the screen reads as off, not as locked."""
    mean = _luma(_lock(name)).mean()
    assert mean >= 12.0, (
        f"{name} renders at mean luminance {mean:.1f}/255 once the shell blurs "
        f"and dims it — that is a black screen with a clock on it. Fine "
        f"linework does not survive a 60px blur; the art needs wide, "
        f"low-amplitude form under it (see add_lock_blooms)")


@pytest.mark.parametrize("name", DARK)
def test_brand_colour_survives_the_blur(name):
    """Grey is not the brand. Something green or blue has to come through, or
    the lock screen is just a dark smudge that could belong to any distro."""
    a = np.asarray(_lock(name), dtype=np.float32)
    # Where the image is brightest, is it tinted?
    luma = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    hot = luma >= np.percentile(luma, 92)
    r, g, b = (a[:, :, i][hot].mean() for i in range(3))
    assert max(g, b) - r >= 2.0, (
        f"{name}: the brightest part of the locked screen is neutral "
        f"(r={r:.1f} g={g:.1f} b={b:.1f}) — no brand colour survived")


@pytest.mark.parametrize("name", DARK)
def test_white_text_still_reads_over_the_clock(name):
    """GNOME puts the time and date in white in the upper centre. Buying a
    prettier lock screen by brightening the one region the text sits in would
    be a straight loss."""
    a = _luma(_lock(name))
    # the clock band, in the 1920x1080 frame
    behind = a[110:350, 680:1240]
    assert behind.mean() <= 60.0, (
        f"{name}: mean luminance behind the clock is {behind.mean():.1f}/255 — "
        f"too bright for white text to stay comfortable")
    assert behind.max() <= 110.0, (
        f"{name}: a hotspot of {behind.max():.0f}/255 sits behind the clock")


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
