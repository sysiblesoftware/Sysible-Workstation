#!/usr/bin/env python3
"""Render the Sysible lock / login screen background (SES rebrand).

A calm, atmospheric composition: a dark field with TOPOGRAPHIC contour lines
(survey-map style — no honeycomb), a soft glow, a vignette, and the Sysible mark
+ "SYSIBLE WORKSTATION" wordmark (Sora) with a green accent underline, set a touch
below centre so the top stays clear for GNOME's clock (lock) and user list
(login). Output: a 4K wallpaper consumed by the GDM theme via the system hook.
"""
import io
import math
import os
import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageFilter

LOGO = "branding/logo/sysible-mark.svg"          # canonical S-tile mark
FONT = "branding/fonts/Sora.ttf"                 # Sora (OFL)
GREEN = (109, 219, 115)                           # #6ddb73
BLUE = (122, 162, 255)                            # #7aa2ff
FG = (233, 240, 247)


def _sora(size):
    f = ImageFont.truetype(FONT, size)
    for nm in ("SemiBold", "Bold", "Regular"):
        try:
            f.set_variation_by_name(nm); break
        except Exception:
            continue
    return f


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vgrad(W, H, top, bot):
    g = Image.new("RGB", (1, H))
    for y in range(H):
        g.putpixel((0, y), _lerp(top, bot, y / H))
    return g.resize((W, H))


# ---- topographic contour field (marching squares over a Gaussian terrain) ----
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


def _topo(W, H, seed=7):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    GW, GH = 200, 120
    Hf = _hgrid(GW, GH, seed)
    lo = min(map(min, Hf)); hi = max(map(max, Hf)); step = (hi - lo) / 26.0
    sx, sy = W / (GW - 1), H / (GH - 1)
    lv = lo + step * 0.5
    while lv < hi:
        idx = round((lv - lo) / step); ic = (idx % 5 == 0)
        col = (150, 178, 225, 60) if ic else (108, 136, 185, 28)
        wd = max(2, int(H * 0.0011)) if ic else max(1, int(H * 0.0006))
        for a, b in _contour(Hf, GW, GH, lv):
            d.line([(a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy)], fill=col, width=wd)
        lv += step
    for kk in (8, 15):
        for a, b in _contour(Hf, GW, GH, lo + step * kk):
            d.line([(a[0] * sx, a[1] * sy), (b[0] * sx, b[1] * sy)], fill=GREEN + (46,),
                   width=max(2, int(H * 0.0009)))
    return layer


def _glow(W, H, cx, cy, radius, color, peak):
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    steps = 60
    for i in range(steps, 0, -1):
        rr = radius * i / steps
        a = int(peak * (1 - i / steps) ** 2)
        d.ellipse([cx - rr, cy - rr * 0.8, cx + rr, cy + rr * 0.8], fill=color + (a,))
    return g.filter(ImageFilter.GaussianBlur(radius / 14))


def _vignette(W, H, strength):
    v = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(v)
    m = max(W, H)
    steps = 60
    for i in range(steps):
        a = int(strength * (i / steps) ** 2)
        rr = m * (0.72 - 0.72 * i / steps)
        d.ellipse([W / 2 - rr, H / 2 - rr, W / 2 + rr, H / 2 + rr], fill=255 - a)
    v = v.filter(ImageFilter.GaussianBlur(m / 20))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.putalpha(Image.eval(v, lambda p: 255 - p))
    return out


def _wordmark(draw, text, font, cx, y, fill, tracking):
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + tracking
    return total


def render(W, H, out):
    cx = W // 2
    base = _vgrad(W, H, (16, 22, 33), (8, 11, 18)).convert("RGBA")
    base.alpha_composite(_topo(W, H))
    base.alpha_composite(_glow(W, H, cx, int(H * 0.30), int(W * 0.26), BLUE, 46))
    base.alpha_composite(_vignette(W, H, 210))

    # A small "SYSIBLE WORKSTATION" wordmark anchored to the BOTTOM — no centred mark.
    # GNOME draws the login dialog / user list and the lock clock DEAD CENTRE, so
    # the middle must stay clear or they collide (the old centred S-tile did). The
    # greeter renders its own small logo beside the user list, so the background
    # only needs a discreet footer wordmark. Kept small and professional.
    draw = ImageDraw.Draw(base)
    fs = int(H * 0.019)
    font = _sora(fs)
    # Anchor the footer wordmark at 80% height (not 86%): GDM/GNOME's greeter
    # reserves a bottom strip and, on wide displays, the background is drawn with
    # `zoom` (cover) which can crop the last few percent — at 86% the wordmark +
    # underline + tagline ran off the bottom edge. 80% keeps the whole group
    # inside the safe zone on every aspect ratio while still reading as a footer.
    wy = int(H * 0.80)
    tw = _wordmark(draw, "SYSIBLE WORKSTATION", font, cx, wy, FG, int(H * 0.006))
    # green accent underline
    uh = max(2, int(H * 0.0028))
    uy = wy + int(fs * 1.22)
    draw.rectangle([cx - tw / 2, uy, cx + tw / 2, uy + uh], fill=GREEN)
    # tagline beneath the underline
    tfs = int(H * 0.0105)
    _wordmark(draw, "ENGINEERING · AUTOMATION · CLOUD", _sora(tfs), cx, uy + int(H * 0.010),
              (150, 170, 205), int(H * 0.004))

    base.convert("RGB").save(out)
    print("wrote %s (%dx%d)" % (out, W, H))


if __name__ == "__main__":
    os.makedirs("live-build/config/includes.chroot/usr/share/backgrounds/sysible", exist_ok=True)
    render(3840, 2160, "live-build/config/includes.chroot/usr/share/backgrounds/sysible/sysible-login.png")
