#!/usr/bin/env python3
"""Render the Sysible lock / login screen background.

A calm, atmospheric composition: a dark field with a fine hexagon mesh, a soft
blue-green glow, a vignette, and the Sysible mark + wordmark set low so the top
stays clear for GNOME's clock (lock) and the user list (login). Output goes both
to /usr/share/backgrounds/sysible (a 4K wallpaper) and, at a leaner size, into
the GDM gnome-shell theme via the system hook.
"""
import io
import math
import os
import cairosvg
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Canonical brand mark — single source of truth (see branding/render-branding.py).
LOGO = "branding/logo/sysible-mark.svg"
GREEN = (99, 200, 105)
BLUE = (85, 128, 238)
FG = (233, 240, 247)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vgrad(W, H, top, bot):
    g = Image.new("RGB", (1, H))
    for y in range(H):
        g.putpixel((0, y), _lerp(top, bot, y / H))
    return g.resize((W, H))


def _hex_mesh(W, H, r, cx, cy, glowR):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    dx = r * math.sqrt(3)
    dy = r * 1.5
    row = 0
    y = -r
    while y < H + r:
        off = (dx / 2) if (row % 2) else 0
        x = -r
        while x < W + dx:
            hx = x + off
            dist = math.hypot(hx - cx, cy - y) if False else math.hypot(hx - cx, y - cy)
            t = max(0.0, 1 - dist / glowR)
            pts = [(hx + r * 0.92 * math.sin(math.radians(60 * a)),
                    y - r * 0.92 * math.cos(math.radians(60 * a))) for a in range(6)]
            pts.append(pts[0])
            if t > 0.02:
                col = _lerp(GREEN, BLUE, min(1, (hx) / W))
                a = int((0.10 + 0.55 * t) * 255)
                d.line(pts, fill=col + (a,), width=2)
            else:
                d.line(pts, fill=(150, 170, 200, 14), width=1)
            x += dx
        y += dy
        row += 1
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


def render(W, H, out):
    cx, cy = W // 2, int(H * 0.52)
    base = _vgrad(W, H, (10, 13, 19), (7, 9, 14)).convert("RGBA")
    base.alpha_composite(_glow(W, H, cx, cy, int(W * 0.30), BLUE, 70))
    base.alpha_composite(_glow(W, H, cx, cy, int(W * 0.20), GREEN, 46))
    base.alpha_composite(_hex_mesh(W, H, int(H * 0.028), cx, cy, max(W, H) * 0.42))
    base.alpha_composite(_vignette(W, H, 210))

    # mark + wordmark, set a touch below centre
    lh = int(H * 0.16)
    logo = Image.open(io.BytesIO(cairosvg.svg2png(url=LOGO, output_height=lh))).convert("RGBA")
    ly = cy - lh // 2
    base.alpha_composite(logo, (cx - logo.width // 2, ly))
    draw = ImageDraw.Draw(base)
    fs = int(H * 0.033)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fs)
    _wordmark(draw, "SYSIBLE LINUX", font, cx, ly + lh + int(H * 0.03), FG, int(H * 0.008))

    base.convert("RGB").save(out)
    print("wrote %s (%dx%d)" % (out, W, H))


if __name__ == "__main__":
    os.makedirs("live-build/config/includes.chroot/usr/share/backgrounds/sysible", exist_ok=True)
    render(3840, 2160, "live-build/config/includes.chroot/usr/share/backgrounds/sysible/sysible-login.png")
