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
CONTROLLER_MARK = os.path.join(ROOT, "branding/logo/sysible-controller-mark.svg")
INSTALL_SVG = os.path.join(ROOT, "live-build/config/includes.chroot/usr/share/icons/hicolor/scalable/apps/sysible-install.svg")
LB = os.path.join(ROOT, "live-build/config")
CHROOT = os.path.join(LB, "includes.chroot")

BG = (13, 17, 23)            # #0d1117 dark field
FG_DARK = (233, 240, 247)    # wordmark on dark
FG_LIGHT = (20, 29, 56)      # wordmark on light
GREEN = (109, 219, 115)      # #6ddb73
BLUE = (122, 162, 255)       # #7aa2ff
FONT = os.path.join(ROOT, "branding/fonts/Sora.ttf")   # Sora (OFL), SES rebrand
WORDMARK = "SYSIBLE LINUX"


def _sora(size):
    """Sora at SemiBold — the display weight of the SES brand. (Variable font;
    fall back gracefully if an instance name is unavailable.)"""
    f = ImageFont.truetype(FONT, size)
    for nm in ("SemiBold", "Bold", "Regular"):
        try:
            f.set_variation_by_name(nm); break
        except Exception:
            continue
    return f


# ---------------------------------------------------------------- primitives
def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _svg_png(url, size):
    png = cairosvg.svg2png(url=url, output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def mark(size):
    """The Sysible Linux brand mark, size x size, transparent background."""
    return _svg_png(MARK, size)


def controller_mark(size):
    """The Sysible Controller mark (matched family body), transparent."""
    return _svg_png(CONTROLLER_MARK, size)


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


def _rng(seed):
    s = seed & 0x7fffffff
    while True:
        s = (1103515245 * s + 12345) & 0x7fffffff
        yield s / 0x7fffffff


def _hgrid(GW, GH, seed):
    r = _rng(seed)
    bumps = [(next(r) * 1.1 - 0.05, next(r) * 1.1 - 0.05, next(r) * 2 - 1, 0.08 + next(r) * 0.22)
             for _ in range(14)]
    H = [[0.0] * GW for _ in range(GH)]
    for j in range(GH):
        for i in range(GW):
            x, y = i / (GW - 1), j / (GH - 1)
            v = x * 0.5 + y * 0.3
            for cx, cy, amp, sig in bumps:
                v += amp * math.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * sig * sig)))
            H[j][i] = v
    return H


def _contour(H, GW, GH, level):
    segs = []

    def ip(a, b, pa, pb):
        t = (level - a) / (b - a) if b != a else 0.5
        return (pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t)
    for j in range(GH - 1):
        for i in range(GW - 1):
            tl, tr, br, bl = H[j][i], H[j][i + 1], H[j + 1][i + 1], H[j + 1][i]
            p = []
            if (tl > level) != (tr > level): p.append(ip(tl, tr, (i, j), (i + 1, j)))
            if (tr > level) != (br > level): p.append(ip(tr, br, (i + 1, j), (i + 1, j + 1)))
            if (br > level) != (bl > level): p.append(ip(br, bl, (i + 1, j + 1), (i, j + 1)))
            if (bl > level) != (tl > level): p.append(ip(bl, tl, (i, j + 1), (i, j)))
            if len(p) == 2:
                segs.append((p[0], p[1]))
            elif len(p) == 4:
                segs.append((p[0], p[1])); segs.append((p[2], p[3]))
    return segs


def field(W, H, seed=7):
    """Dark ground + TOPOGRAPHIC contour lines (survey-map style) + soft glow.
    Replaces the old honeycomb/hex-mesh. Deterministic (fixed seed)."""
    top, bot = (16, 22, 33), (8, 11, 18)
    canvas = Image.new("RGB", (W, H), bot)
    d = ImageDraw.Draw(canvas)
    for y in range(H):
        t = y / max(1, H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)))
    canvas = canvas.convert("RGBA")
    GW, GH = 200, 120
    Hf = _hgrid(GW, GH, seed)
    lo = min(map(min, Hf)); hi = max(map(max, Hf)); step = (hi - lo) / 26.0
    sx, sy = W / (GW - 1), H / (GH - 1)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    lv = lo + step * 0.5
    while lv < hi:
        idx = round((lv - lo) / step); ic = (idx % 5 == 0)
        col = (150, 178, 225, 70) if ic else (108, 136, 185, 34)
        wd = max(2, int(H * 0.0011)) if ic else max(1, int(H * 0.0006))
        for a, b in _contour(Hf, GW, GH, lv):
            ld.line([(a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy)], fill=col, width=wd)
        lv += step
    canvas.alpha_composite(lay)
    al = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ad = ImageDraw.Draw(al)
    for kk in (8, 15):
        for a, b in _contour(Hf, GW, GH, lo + step * kk):
            ad.line([(a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy)], fill=GREEN + (55,),
                    width=max(2, int(H * 0.0009)))
    canvas.alpha_composite(al)
    canvas.alpha_composite(_glow(W, H, W // 2, int(H * 0.05), int(H * 0.42), BLUE, 40))
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
    font = _sora(fsize)
    wy = logo_top + logo_h + int(H * 0.04)
    _draw_wordmark(draw, WORDMARK, font, W / 2, wy, FG_DARK, tracking=int(H * 0.013))
    uw, uh = int(W * 0.40), max(2, int(H * 0.006))
    ux, uy = (W - uw) // 2, wy + fsize + int(H * 0.03)
    # Solid green accent underline (SES rebrand — was a green->blue gradient bar).
    bar = Image.new("RGBA", (uw, uh), GREEN + (255,))
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
    font = _sora(size)
    tr = size * tracking_ratio
    tw = sum(d.textlength(c, font=font) for c in text) + tr * (len(text) - 1)
    if tw > max_w:                       # scale down proportionally to fit the box
        size = max(8, int(size * max_w / tw))
        font = _sora(size)
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


def avatar(size, mark_url=MARK):
    """Square social avatar: the mark on the dark hex-mesh field. The mark is kept
    within the centre ~62% so a circular crop (GitHub/X) never clips it."""
    canvas = field(size, size).convert("RGBA")
    canvas.alpha_composite(_glow(size, size, size // 2, size // 2, int(size * 0.42), GREEN, 34))
    s = int(size * 0.60)
    m = _svg_png(mark_url, s)
    canvas.alpha_composite(m, ((size - s) // 2, (size - s) // 2))
    return canvas.convert("RGB")


def grub_background(W, H):
    """GRUB menu background: the topographic field with the horizontal lockup
    BAKED IN, top-centre. The lockup is part of the picture on purpose — it is NOT
    a separate GRUB `+ image` element, because arm64 GRUB ignored the width/height
    on that element and drew the logo at full native size (huge, over the menu).
    Baked in, GRUB only has to scale the background to the screen. Logo = 30% of
    width, top 13%, centred — well above the boot menu at 40%. (Keep in sync with
    theme.txt desktop-image-scale-method=crop.)"""
    bg = field(W, H).convert("RGBA")
    lw = int(W * 0.30)
    logo = hlockup(1040, 300, FG_DARK)
    lh = int(logo.height * lw / logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    bg.alpha_composite(logo, ((W - lw) // 2, int(H * 0.13)))
    return bg.convert("RGB")




# ---------------------------------------------------------------- output map
def build():
    """Return {relpath: PIL.Image or ('tga', PIL.Image)} for every derived asset."""
    A = {}
    C = lambda p: os.path.join(CHROOT, p)
    L = lambda p: os.path.join(LB, p)
    G = lambda p: os.path.join(ROOT, p)

    # Boot — GRUB theme (the asset that was drifting): 1040x300 horizontal lockup.
    A[C("boot/grub/themes/sysible/logo.png")] = hlockup(1040, 300, FG_DARK)
    # background = topo field with the lockup BAKED IN (see grub_background / theme.txt).
    A[C("boot/grub/themes/sysible/background.png")] = grub_background(1920, 1080)
    # Boot — composed splashes.
    A[L("branding/splash.png")] = splash(1920, 1080)
    A[L("bootloaders/isolinux/splash.png")] = splash(800, 600)
    A[("tga", L("binary_grub/splash.tga"))] = splash(640, 480)
    # Plymouth (boot animation) + Calamares (installer) + GDM.
    # Plymouth boot/shutdown splash: vertical lockup so the loading screen shows
    # the "SYSIBLE LINUX" wordmark under the mark (a bare mark read as unbranded).
    # Rendered at 2x (was 360x320) so the baked "SYSIBLE LINUX" wordmark stays
    # crisp on the boot splash — Plymouth blits the sprite 1:1, so a small source
    # read soft/upscaled on HiDPI panels.
    A[C("usr/share/plymouth/themes/sysible/logo.png")] = vlockup(720, 640, FG_DARK)
    A[C("etc/calamares/branding/sysible/sysible-logo.png")] = centred_mark(96, 104, pad=0.02)
    # Calamares HERO (productWelcome) + slideshow mark — the big centred logo.
    A[C("etc/calamares/branding/sysible/sysible-welcome.png")] = centred_mark(240, 260, pad=0.04)
    A[C("etc/calamares/branding/sysible/mark.png")] = centred_mark(440, 476, pad=0.04)
    # Login / GDM / polkit avatar (.face) — the mark on the dark field, shown in a
    # circle. The 9000 hook copies sysible-face.png over .face + the AccountsService
    # icon at build, so all three are generated identically here to stay in sync.
    _face = avatar(256)
    A[C("usr/share/pixmaps/sysible-face.png")] = _face
    A[C("etc/skel/.face")] = _face
    A[C("var/lib/AccountsService/icons/user")] = _face
    # Calamares productLogo — render from the (solid, family-style) install icon so
    # the install window matches the dock instead of the old hollow-gradient art.
    A[C("etc/calamares/branding/sysible/install-logo.png")] = _svg_png(INSTALL_SVG, 512)
    # The SysTerm/install DOCK icons themselves are the approved art and are not
    # regenerated here (they derive from their own SVGs, not the brand mark).
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

    # Sysible Controller — matched family mark (same body, hub+nodes design).
    for sz in (48, 64, 128, 256):
        A[C(f"usr/share/icons/hicolor/{sz}x{sz}/apps/sysible-controller.png")] = controller_mark(sz)
    A[C("usr/share/pixmaps/sysible-controller.png")] = controller_mark(256)

    # Social avatars (square, circle-crop-safe) for GitHub org + Twitter/X.
    A[G("branding/social/github-avatar.png")] = avatar(512)
    A[G("branding/social/twitter-avatar.png")] = avatar(400)
    A[G("branding/social/controller-avatar.png")] = avatar(512, CONTROLLER_MARK)
    return A


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
    # Keep every SVG copy byte-identical to its canonical source, so no consumer
    # (app grid, lockscreen renderer, pixmap lookups) can pick up old art again.
    # (target_path, source_svg): the Linux marks track sysible-mark.svg; the
    # Controller dock icon tracks sysible-controller-mark.svg.
    svg_targets = [
        (os.path.join(CHROOT, "usr/share/icons/hicolor/scalable/apps/sysible-logo.svg"), MARK),
        (os.path.join(CHROOT, "usr/share/pixmaps/sysible-logo-dark.svg"), MARK),
        (os.path.join(CHROOT, "usr/share/pixmaps/sysible-logo-light.svg"), MARK),
        (os.path.join(CHROOT, "usr/share/icons/hicolor/scalable/apps/sysible-controller.svg"), CONTROLLER_MARK),
    ]
    src_bytes = {p: open(p, "rb").read() for p in {MARK, CONTROLLER_MARK}}

    drift = []
    manifest = ["# sysible branding manifest — sha256 of the canonical marks + every",
                "# generated asset. Regenerate with: python3 branding/render-branding.py",
                f"{hashlib.sha256(src_bytes[MARK]).hexdigest()}  branding/logo/sysible-mark.svg",
                f"{hashlib.sha256(src_bytes[CONTROLLER_MARK]).hexdigest()}  branding/logo/sysible-controller-mark.svg"]

    for tgt, src in svg_targets:
        rel = os.path.relpath(tgt, ROOT)
        data = src_bytes[src]
        if check:
            cur = open(tgt, "rb").read() if os.path.exists(tgt) else b""
            if cur != data:
                drift.append(rel)
        else:
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            with open(tgt, "wb") as f:
                f.write(data)
        manifest.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")

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
