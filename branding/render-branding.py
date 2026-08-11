#!/usr/bin/env python3
"""Sysible branding generator — the SINGLE place all logo assets are produced.

Every logo the product shows (GRUB boot menu, isolinux/BIOS splash, Plymouth,
Calamares, the app-grid icon, README badges) is rendered here FROM ONE SOURCE:
branding/logo/sysible-mark.svg. This exists because the boot logo used to be a
hand-committed PNG that drifted from the dock icon every time branding changed —
so the live-boot screen kept shipping the old mark. Now there is one source and
one generator; a derived PNG can never silently fall behind the mark again.

Usage:
    python3 branding/render-branding.py           # (re)render + write all assets
    python3 branding/render-branding.py --check    # render in memory, FAIL if any
                                                    # committed asset is out of sync

The --check mode is what scripts/verify-branding.sh runs in CI *before* the long
ISO build, so a stale logo fails in seconds instead of after a 35-minute build.

Determinism: assets are compared/committed as produced by the pinned toolchain
(cairosvg + Pillow) in the CI image. Always regenerate with that toolchain (or
the provided container) so bytes match; do not hand-edit derived files.
"""
import hashlib
import io
import math
import os
import sys

import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(ROOT, "branding/logo/sysible-mark.svg")
# The install launcher is a DIFFERENT mark (download glyph, not the brand logo);
# it has its own canonical SVG and is rendered here too so all branding is owned.
INSTALL_SVG = os.path.join(
    ROOT, "live-build/config/includes.chroot/usr/share/icons/hicolor/scalable/apps/sysible-install.svg"
)
LB = os.path.join(ROOT, "live-build/config")
CHROOT = os.path.join(LB, "includes.chroot")

BG = (13, 17, 23)            # #0d1117 dark field
FG_DARK = (233, 240, 247)    # wordmark on dark
FG_LIGHT = (20, 29, 56)      # wordmark on light
GREEN = (109, 219, 115)      # #6ddb73
BLUE = (122, 162, 255)       # #7aa2ff
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
WORDMARK = "SYSIBLE LINUX"


# ---------------------------------------------------------------- primitives
def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def mark(size):
    """The brand hexagon mark, size x size, transparent background."""
    png = cairosvg.svg2png(url=MARK, output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def install_mark(size):
    png = cairosvg.svg2png(url=INSTALL_SVG, output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _hex_mesh(W, H, r, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    dx = r * math.sqrt(3)
    dy = r * 1.5
    col = (120, 150, 210, alpha)
    row, y = 0, -r
    while y < H + r:
        offset = (dx / 2) if (row % 2) else 0
        x = -dx
        while x < W + dx:
            cx, cy = x + offset, y
            pts = [(cx + r * math.sin(math.radians(a)),
                    cy - r * math.cos(math.radians(a))) for a in range(0, 360, 60)]
            d.line(pts + [pts[0]], fill=col, width=1)
            x += dx
        y += dy
        row += 1
    return layer


def _glow(W, H, cx, cy, radius, color, peak):
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    steps = 48
    for i in range(steps, 0, -1):
        rr = radius * i / steps
        a = round(peak * (1 - i / steps) ** 2)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))
    return g.filter(ImageFilter.GaussianBlur(radius / 12))


def _draw_wordmark(draw, text, font, cx, y, fill, tracking):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def field(W, H):
    """Dark hex-mesh + soft blue/green glow. No logo (GRUB overlays logo.png)."""
    canvas = Image.new("RGBA", (W, H), BG + (255,))
    canvas.alpha_composite(_hex_mesh(W, H, max(24, int(H * 0.055)), 15))
    cy = int(H * 0.30)
    canvas.alpha_composite(_glow(W, H, W // 2, cy, int(H * 0.48), BLUE, 55))
    canvas.alpha_composite(_glow(W, H, W // 2, cy, int(H * 0.30), GREEN, 40))
    return canvas.convert("RGB")


def splash(W, H):
    """Full composed boot splash: field + centred mark + wordmark + underline."""
    canvas = field(W, H).convert("RGBA")
    logo_h = int(H * 0.24)
    logo_top = int(H * 0.07)
    m = mark(logo_h)
    canvas.alpha_composite(m, ((W - m.width) // 2, logo_top))
    draw = ImageDraw.Draw(canvas)
    fsize = int(H * 0.058)
    font = ImageFont.truetype(FONT, fsize)
    wy = logo_top + logo_h + int(H * 0.04)
    _draw_wordmark(draw, WORDMARK, font, W / 2, wy, FG_DARK, tracking=int(H * 0.013))
    uw, uh = int(W * 0.40), max(2, int(H * 0.006))
    ux, uy = (W - uw) // 2, wy + fsize + int(H * 0.03)
    bar = Image.new("RGBA", (uw, uh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for i in range(uw):
        bd.line([(i, 0), (i, uh)], fill=_lerp(GREEN, BLUE, i / uw) + (255,))
    canvas.alpha_composite(bar, (ux, uy))
    return canvas.convert("RGB")


def centred_mark(W, H, pad=0.06):
    """Transparent canvas W x H with the mark centred (for square-ish targets)."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = int(min(W, H) * (1 - 2 * pad))
    m = mark(s)
    canvas.alpha_composite(m, ((W - s) // 2, (H - s) // 2))
    return canvas


def _fit_font(text, max_w, cap_px, tracking_ratio):
    """Largest font (<= cap_px) whose tracked width fits max_w. Returns (font, tw, tracking)."""
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    size = cap_px
    font = ImageFont.truetype(FONT, size)
    tr = size * tracking_ratio
    tw = sum(d.textlength(c, font=font) for c in text) + tr * (len(text) - 1)
    if tw > max_w:                       # scale down proportionally to fit the box
        size = max(8, int(size * max_w / tw))
        font = ImageFont.truetype(FONT, size)
        tr = size * tracking_ratio
        tw = sum(d.textlength(c, font=font) for c in text) + tr * (len(text) - 1)
    return font, tw, tr, size


def hlockup(W, H, fg):
    """Horizontal lockup: mark on the left, SYSIBLE LINUX to its right. Transparent.
    The wordmark is auto-fitted so the whole lockup always sits inside W x H."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = int(H * 0.80)
    m = mark(s)
    gap = int(H * 0.16)
    margin = W * 0.05
    font, tw, tr, fsize = _fit_font(WORDMARK, W - 2 * margin - s - gap, int(H * 0.34), 0.055)
    block = s + gap + tw
    x0 = (W - block) / 2
    canvas.alpha_composite(m, (int(x0), (H - s) // 2))
    draw = ImageDraw.Draw(canvas)
    asc, desc = font.getmetrics()
    ty = (H - (asc + desc)) // 2
    _draw_wordmark(draw, WORDMARK, font, x0 + s + gap + tw / 2, ty, fg, tr)
    return canvas


def vlockup(W, H, fg):
    """Vertical lockup: mark on top, SYSIBLE LINUX beneath. Transparent."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = int(W * 0.58)
    m = mark(s)
    top = int(H * 0.07)
    canvas.alpha_composite(m, ((W - s) // 2, top))
    font, tw, tr, fsize = _fit_font(WORDMARK, W * 0.90, int(W * 0.15), 0.04)
    draw = ImageDraw.Draw(canvas)
    wy = top + s + int(H * 0.05)
    _draw_wordmark(draw, WORDMARK, font, W / 2, wy, fg, tr)
    return canvas


# ---------------------------------------------------------------- output map
def build():
    """Return {relpath: PIL.Image or ('tga', PIL.Image)} for every derived asset."""
    A = {}
    C = lambda p: os.path.join(CHROOT, p)
    L = lambda p: os.path.join(LB, p)
    G = lambda p: os.path.join(ROOT, p)

    # Boot — GRUB theme (the asset that was drifting): 1040x300 horizontal lockup.
    A[C("boot/grub/themes/sysible/logo.png")] = hlockup(1040, 300, FG_DARK)
    A[C("boot/grub/themes/sysible/background.png")] = field(1920, 1080)
    # Boot — composed splashes.
    A[L("branding/splash.png")] = splash(1920, 1080)
    A[L("bootloaders/isolinux/splash.png")] = splash(800, 600)
    A[("tga", L("binary_grub/splash.tga"))] = splash(640, 480)
    # Plymouth (boot animation) + Calamares (installer) + GDM.
    A[C("usr/share/plymouth/themes/sysible/logo.png")] = centred_mark(332, 208)
    A[C("etc/calamares/branding/sysible/sysible-logo.png")] = centred_mark(96, 104, pad=0.02)
    # NOTE: install-logo.png (Calamares) and the SysTerm/install DOCK icons are
    # deliberately NOT regenerated here — they are the approved existing icons and
    # derive from sysible-install.svg / io.systerm.SysTerm.svg, not the brand mark.
    # Pixmaps (app + README + system).
    A[C("usr/share/pixmaps/sysible-logo.png")] = centred_mark(256, 256, pad=0.04)
    A[C("usr/share/pixmaps/sysible-logo-dark.png")] = vlockup(512, 555, FG_DARK)
    A[C("usr/share/pixmaps/sysible-logo-light.png")] = vlockup(512, 555, FG_LIGHT)
    A[C("usr/share/pixmaps/sysible-linux-logo.png")] = vlockup(512, 555, FG_DARK)
    # App-grid icon: keep the hicolor SVG byte-synced with the canonical mark, and
    # render its PNG sizes so themed environments have crisp rasters.
    for sz in (16, 22, 24, 32, 48, 64, 128, 256):
        A[C(f"usr/share/icons/hicolor/{sz}x{sz}/apps/sysible-logo.png")] = mark(sz)
    # README badges.
    A[G(".github/sysible-logo-dark.png")] = hlockup(980, 260, FG_DARK)
    A[G(".github/sysible-logo-light.png")] = hlockup(980, 260, FG_LIGHT)
    return A


def _install(size):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(install_mark(size))
    return canvas


# Files that are branded but INTENTIONALLY not regenerated here, with the reason.
# Documented so a future reader doesn't "fix" them and reintroduce a bug.
EXCLUDED = {
    "usr/share/pixmaps/sysible-login-logo.png":
        "intentional 2x2 transparent blank — hides the GDM 'debian 12' watermark "
        "(fix #31). Rendering a real logo here reintroduces the watermark overlap.",
}


def _encode(obj):
    """Return PNG (or TGA) bytes for an image / ('tga', image) entry."""
    if isinstance(obj, tuple) and obj[0] == "tga":
        img = obj[1].convert("RGB")
        buf = io.BytesIO(); img.save(buf, format="TGA"); return buf.getvalue()
    buf = io.BytesIO(); obj.convert("RGBA").save(buf, format="PNG"); return buf.getvalue()


def _target_path(key):
    return key[1] if isinstance(key, tuple) else key


def main():
    check = "--check" in sys.argv
    assets = build()
    # Keep every SVG copy of the mark byte-identical to the canonical source, so
    # no consumer (app grid, lockscreen renderer, pixmap lookups) can pick up the
    # old ">"+square art again. These were the lingering old-master files.
    svg_targets = [
        os.path.join(CHROOT, "usr/share/icons/hicolor/scalable/apps/sysible-logo.svg"),
        os.path.join(CHROOT, "usr/share/pixmaps/sysible-logo-dark.svg"),
        os.path.join(CHROOT, "usr/share/pixmaps/sysible-logo-light.svg"),
    ]
    with open(MARK, "rb") as f:
        mark_bytes = f.read()

    drift = []
    manifest = ["# sysible branding manifest — sha256 of the canonical mark + every",
                "# generated asset. Regenerate with: python3 branding/render-branding.py",
                f"{hashlib.sha256(mark_bytes).hexdigest()}  branding/logo/sysible-mark.svg"]

    for tgt in svg_targets:
        rel = os.path.relpath(tgt, ROOT)
        if check:
            cur = open(tgt, "rb").read() if os.path.exists(tgt) else b""
            if cur != mark_bytes:
                drift.append(rel)
        else:
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            with open(tgt, "wb") as f:
                f.write(mark_bytes)
        manifest.append(f"{hashlib.sha256(mark_bytes).hexdigest()}  {rel}")

    for key, obj in assets.items():
        path = _target_path(key)
        rel = os.path.relpath(path, ROOT)
        data = _encode(obj)
        manifest.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
        if check:
            cur = open(path, "rb").read() if os.path.exists(path) else b""
            if cur != data:
                drift.append(rel)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)

    manifest_path = os.path.join(ROOT, "branding/logo/BRANDING.manifest")
    # A twin copy is shipped INTO the image so the in-chroot verify hook can prove
    # every branded file in the installed system still matches the canonical mark.
    image_manifest = os.path.join(CHROOT, "usr/share/sysible/branding.manifest")
    manifest_txt = "\n".join(manifest) + "\n"
    if check:
        cur = open(manifest_path).read() if os.path.exists(manifest_path) else ""
        if cur != manifest_txt:
            drift.append("branding/logo/BRANDING.manifest")
        cur2 = open(image_manifest).read() if os.path.exists(image_manifest) else ""
        if cur2 != manifest_txt:
            drift.append(os.path.relpath(image_manifest, ROOT))
        if drift:
            print("BRANDING DRIFT — these committed assets are stale:", file=sys.stderr)
            for d in sorted(set(drift)):
                print(f"  - {d}", file=sys.stderr)
            print("\nRun: python3 branding/render-branding.py   (then commit)", file=sys.stderr)
            sys.exit(1)
        print(f"branding OK — {len(assets) + len(svg_targets)} assets in sync with the canonical mark.")
    else:
        for mp in (manifest_path, image_manifest):
            os.makedirs(os.path.dirname(mp), exist_ok=True)
            with open(mp, "w") as f:
                f.write(manifest_txt)
        print(f"wrote {len(assets) + len(svg_targets)} assets + manifest from {os.path.relpath(MARK, ROOT)}")
        for k in sorted(EXCLUDED):
            print(f"  (left as-is: {k} — {EXCLUDED[k].splitlines()[0]})")


if __name__ == "__main__":
    main()
