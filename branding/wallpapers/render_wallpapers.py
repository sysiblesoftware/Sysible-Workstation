#!/usr/bin/env python3
"""Sysible Linux wallpaper generator — the SINGLE reproducible source for every
shipped desktop background.

Renders each procedural style at 7680x4320 (JPEG q92) in DARK and LIGHT variants
with the LOCKED "SYSIBLE LINUX" banner composited bottom-left on every one.
Styles: topographic, topographic-ridge, neural, cosmos, roads (Lumpkin County,
GA). numpy is used for gradients, vignette
and large field fills so 8K renders stay fast and low-memory; PIL vector drawing
is used for the line art, and glow layers are rendered at reduced resolution and
upscaled so nothing loops per pixel in Python.

Usage:
    python3 branding/wallpapers/render_wallpapers.py            # full 8K set + previews
    python3 branding/wallpapers/render_wallpapers.py --test     # fast 1600x900 previews only

Output:
    dark  -> packages/sysible-artwork/backgrounds/<name>.jpg
    light -> packages/sysible-artwork/backgrounds/<name>-light.jpg
    1600px previews -> <scratchpad>/wp_preview/<name>[-light].jpg
"""
import os
import sys
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = "/home/user/sysible-linux"
FONT = os.path.join(ROOT, "branding/fonts/Sora.ttf")
OUT_DIR = os.path.join(ROOT, "packages/sysible-artwork/backgrounds")
PREVIEW_DIR = "/tmp/claude-0/-home-user-Sysible-Controller/c65daca9-69d4-5d3e-9d67-370754a4a228/scratchpad/wp_preview"

FULL_W, FULL_H = 7680, 4320
QUALITY = 92
PREVIEW_W = 1600

# ---- brand tokens -----------------------------------------------------------
WHITE = (233, 240, 247)   # #e9f0f7 wordmark on dark
GREEN = (109, 219, 115)   # #6ddb73 accent (green rule — same in both modes)
BLUE = (122, 162, 255)    # #7aa2ff secondary
MUTE = (150, 165, 190)    # #96a5be tagline on dark
DARK_TXT = (20, 32, 58)   # #14203a wordmark on light
LIGHT_MUTE = (74, 85, 112)  # #4a5570 tagline on light


def _sora(px):
    f = ImageFont.truetype(FONT, int(px))
    for nm in ("SemiBold", "Bold", "Regular"):
        try:
            f.set_variation_by_name(nm)
            break
        except Exception:
            continue
    return f


def palette(light):
    if light:
        return dict(
            light=True,
            bg_top=(0xEE, 0xF1, 0xF7), bg_bot=(0xDF, 0xE4, 0xEE),
            art_green=(47, 143, 60), art_blue=(47, 96, 212), art_star=(60, 78, 120),
            vig_color=(150, 165, 200), vig_alpha=0.16,
            back_color=(235, 238, 245), back_alpha=0.30,
        )
    return dict(
        light=False,
        bg_top=(0x0D, 0x11, 0x17), bg_bot=(0x09, 0x0B, 0x10),
        art_green=GREEN, art_blue=BLUE, art_star=(210, 225, 255),
        vig_color=(0, 0, 0), vig_alpha=0.48,
        back_color=(0, 0, 0), back_alpha=0.42,
    )


# ---- numpy field helpers ----------------------------------------------------
def base_gradient(W, H, pal):
    top = np.array(pal["bg_top"], dtype=np.float32)
    bot = np.array(pal["bg_bot"], dtype=np.float32)
    t = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    col = top[None, None, :] * (1.0 - t) + bot[None, None, :] * t   # (H,1,3)
    return np.repeat(col, W, axis=1)                                # (H,W,3)


def _radial_norm(W, H, cx, cy):
    """Aspect-correct normalized radius (1.0 ~ half the shorter axis) from (cx,cy)
    given as fractions of W,H."""
    ax = (np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :] - cx)
    ay = (np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None] - cy)
    asp = W / float(H)
    return np.sqrt((ax * asp) ** 2 + ay ** 2)


def apply_vignette(arr, pal, cx=0.5, cy=0.46):
    r = _radial_norm(arr.shape[1], arr.shape[0], cx, cy)
    r0, r1 = 0.16, 0.92 * (arr.shape[1] / float(arr.shape[0]))
    f = np.clip((r - r0) / (r1 - r0), 0.0, 1.0) ** 2
    a = (f * pal["vig_alpha"])[:, :, None]
    vc = np.array(pal["vig_color"], dtype=np.float32)[None, None, :]
    arr *= (1.0 - a)
    arr += vc * a
    return arr


def add_radial_bloom(arr, cx, cy, radius, color, strength, mode="add"):
    """Soft additive/tinted radial glow, computed with numpy (no per-pixel loop)."""
    W, H = arr.shape[1], arr.shape[0]
    ax = (np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :] - cx) * (W / float(H))
    ay = (np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None] - cy)
    d2 = (ax ** 2 + ay ** 2) / (radius ** 2)
    g = np.exp(-d2 * 2.3).astype(np.float32) * strength
    c = np.array(color, dtype=np.float32)[None, None, :]
    if mode == "add":
        arr += g[:, :, None] * c
    else:  # screen-ish blend toward color
        arr += (c - arr) * g[:, :, None]
    return arr


def to_rgba(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---- deterministic rng ------------------------------------------------------
def rng(seed):
    return np.random.default_rng(seed)


# ---- glow layer helper ------------------------------------------------------
def glow_layer(W, H, draw_fn, blur_px, scale=4):
    """Render soft glows at reduced resolution, blur once, upscale. draw_fn receives
    (ImageDraw, k) where k maps full-res coords -> reduced-res coords."""
    gw, gh = max(1, W // scale), max(1, H // scale)
    g = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    draw_fn(gd, 1.0 / scale)
    g = g.filter(ImageFilter.GaussianBlur(max(1.0, blur_px / scale)))
    return g.resize((W, H), Image.BILINEAR)


# ============================================================================
# BANNER — LOCKED design (banner_c_mock.py). small SYSIBLE LINUX, green rule
# directly UNDER the wordmark, ENGINEERING · AUTOMATION justified under the rule,
# bottom-left with ~5.5% left / ~13% bottom safe margin. Identical everywhere.
# ============================================================================
def draw_banner(img_rgba, pal):
    W, H = img_rgba.size
    # soft corner backing so the banner always reads over the art
    r = _radial_norm(W, H, 0.0, 1.0)
    f = np.clip(1.0 - r / 0.55, 0.0, 1.0) ** 1.5
    back = np.zeros((H, W, 4), dtype=np.float32)
    bc = np.array(pal["back_color"], dtype=np.float32)
    back[:, :, :3] = bc[None, None, :]
    back[:, :, 3] = f * pal["back_alpha"] * 255.0
    back_img = Image.fromarray(back.astype(np.uint8), "RGBA")
    img_rgba = Image.alpha_composite(img_rgba, back_img)

    draw = ImageDraw.Draw(img_rgba, "RGBA")
    x = int(W * 0.055)
    y_base = int(H * 0.87)
    cap = int(H * 0.030)

    word_col = DARK_TXT if pal["light"] else WHITE
    mute_col = LIGHT_MUTE if pal["light"] else MUTE

    wf = _sora(cap)
    word = "SYSIBLE LINUX"
    tr = cap * 0.10
    cap_h = wf.getbbox(word)[3]
    top = int(y_base - cap_h)
    px = x
    for ch in word:
        draw.text((px, top), ch, font=wf, fill=word_col)
        px += draw.textlength(ch, font=wf) + tr
    ww = (px - tr) - x
    ry = top + cap_h + int(cap * 0.24)
    draw.rectangle([x, ry, x + ww, ry + max(2, int(cap * 0.05))], fill=GREEN)

    tf = _sora(int(cap * 0.24))
    tag = "ENGINEERING · AUTOMATION"
    raw = sum(draw.textlength(c, font=tf) for c in tag)
    extra = max(0.0, (ww - raw)) / (len(tag) - 1)
    gy = ry + int(cap * 0.16)
    gx = x
    for ch in tag:
        draw.text((gx, gy), ch, font=tf, fill=mute_col)
        gx += draw.textlength(ch, font=tf) + extra
    return img_rgba


# ============================================================================
# STYLE RENDERERS  (each returns a final RGB PIL image, banner NOT yet applied)
# ============================================================================
def _topo_overlay(W, H, pal, rings, freq, jitter, seed, deform=0.11):
    """Concentric deformed contour rings, green->blue by ring, sin fade for depth."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    r = rng(seed)
    cx, cy = W * 0.52, H * 0.5
    base = min(W, H) * (0.9 / rings)
    lw = max(2, int(W / 2400))
    ga = pal["art_green"]
    ba = pal["art_blue"]
    a_lo, a_hi = (0.10, 0.34) if pal["light"] else (0.09, 0.30)
    phase = r.random() * math.tau
    for k in range(rings):
        rr = base * (k + 1)
        pts = []
        a = 0.0
        while a <= math.pi * 2 + 0.02:
            pp = (rr
                  + math.sin(a * 3 + k * 0.7 + phase) * rr * deform
                  + math.cos(a * freq - k * 0.5) * rr * deform * 0.45
                  + math.sin(a * (freq * 2 + 1) + k) * rr * jitter)
            pts.append((cx + pp * math.cos(a), cy + pp * 0.62 * math.sin(a)))
            a += 0.012
        fade = math.sin(math.pi * (k + 1) / (rings + 1))
        col = mix(ga, ba, k / max(1, rings - 1))
        al = int((a_lo + (a_hi - a_lo) * fade) * 255)
        d.line(pts, fill=col + (al,), width=lw, joint="curve")
    return overlay


def render_topographic(W, H, pal):
    arr = base_gradient(W, H, pal)
    arr = apply_vignette(arr, pal)
    img = to_rgba(arr)
    ov = _topo_overlay(W, H, pal, rings=26, freq=5, jitter=0.0, seed=101, deform=0.11)
    img = Image.alpha_composite(img, ov)
    return img.convert("RGB")


def render_topographic_ridge(W, H, pal):
    arr = base_gradient(W, H, pal)
    arr = apply_vignette(arr, pal)
    img = to_rgba(arr)
    # denser + ridged: two interleaved contour families with higher frequency
    ov = _topo_overlay(W, H, pal, rings=54, freq=9, jitter=0.05, seed=202, deform=0.14)
    img = Image.alpha_composite(img, ov)
    ov2 = _topo_overlay(W, H, pal, rings=54, freq=13, jitter=0.06, seed=707, deform=0.09)
    img = Image.alpha_composite(img, ov2)
    return img.convert("RGB")


def render_neural(W, H, pal):
    arr = base_gradient(W, H, pal)
    # faint central bloom for depth
    add_radial_bloom(arr, 0.5, 0.45, 0.6, pal["art_blue"], 0.05 if pal["light"] else 0.10)
    arr = apply_vignette(arr, pal)
    img = to_rgba(arr)

    r = rng(303)
    N = 520
    xs = r.random(N) * W
    ys = r.random(N) * H
    hub = (np.arange(N) % 7 == 0)

    # edges: connect nodes within a threshold, drawn once on an overlay
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ed = ImageDraw.Draw(ov, "RGBA")
    TH = W * 0.075
    lw = max(1, int(W / 3600))
    edge_base = 0.20 if pal["light"] else 0.15
    dx = xs[:, None] - xs[None, :]
    dy = ys[:, None] - ys[None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    ii, jj = np.where((dist < TH) & (np.triu(np.ones((N, N), bool), 1)))
    for i, j in zip(ii, jj):
        t = dist[i, j] / TH
        col = mix(pal["art_green"], pal["art_blue"], xs[i] / W)
        ed.line([(xs[i], ys[i]), (xs[j], ys[j])],
                fill=col + (int(edge_base * (1 - t) * 255),), width=lw)
    img = Image.alpha_composite(img, ov)

    # node glow (hubs), rendered small + blurred + upscaled
    if not pal["light"]:
        def gdraw(gd, k):
            for i in np.where(hub)[0]:
                col = mix(pal["art_green"], pal["art_blue"], xs[i] / W)
                gr = (W / 150) * k
                gd.ellipse([xs[i] * k - gr, ys[i] * k - gr, xs[i] * k + gr, ys[i] * k + gr],
                           fill=col + (110,))
        img = Image.alpha_composite(img, glow_layer(W, H, gdraw, blur_px=W / 220, scale=4))

    # node cores
    nd = ImageDraw.Draw(img, "RGBA")
    for i in range(N):
        col = mix(mix(pal["art_green"], (63, 200, 200), ys[i] / H), pal["art_blue"], xs[i] / W)
        rr = (W / 900) if hub[i] else (W / 2000)
        a = 255 if hub[i] else (200 if pal["light"] else 220)
        nd.ellipse([xs[i] - rr, ys[i] - rr, xs[i] + rr, ys[i] + rr], fill=col + (a,))
    return img.convert("RGB")


def render_cosmos(W, H, pal):
    arr = base_gradient(W, H, pal)
    # soft nebula blooms (green + blue), additive on dark / tinted on light
    mode = "blend" if pal["light"] else "add"
    s = 0.16 if pal["light"] else 0.30
    add_radial_bloom(arr, 0.74, 0.30, 0.42, pal["art_blue"], s, mode)
    add_radial_bloom(arr, 0.62, 0.52, 0.38, pal["art_green"], s * 0.8, mode)
    add_radial_bloom(arr, 0.30, 0.34, 0.30, pal["art_blue"], s * 0.7, mode)
    add_radial_bloom(arr, 0.20, 0.72, 0.26, pal["art_green"], s * 0.55, mode)
    arr = apply_vignette(arr, pal)
    img = to_rgba(arr)

    r = rng(404)
    n = int(W * H / 5200)
    xs = r.random(n) * W
    ys = r.random(n) * H
    mag = r.random(n) ** 2.6
    # bright-star glow layer
    bright = np.where(mag > 0.86)[0]

    def gdraw(gd, k):
        for i in bright:
            gr = (W / 640) * k * (0.5 + mag[i])
            col = pal["art_star"] if not pal["light"] else (90, 110, 150)
            gd.ellipse([xs[i] * k - gr, ys[i] * k - gr, xs[i] * k + gr, ys[i] * k + gr],
                       fill=col + (70,))
    img = Image.alpha_composite(img, glow_layer(W, H, gdraw, blur_px=W / 300, scale=4))

    # star cores
    sd = ImageDraw.Draw(img, "RGBA")
    warm = r.random(n)
    for i in range(n):
        rad = (W / 6400) * (0.5 + mag[i] * 3.0)
        if pal["light"]:
            b = int(40 + mag[i] * 70)
            col = (b, int(b * 1.05), int(b * 1.3))
            a = int(120 + mag[i] * 120)
        else:
            b = int(120 + mag[i] * 135)
            col = (b, b, min(255, int(b * 1.03))) if warm[i] < 0.7 else (min(255, int(b * 1.06)), int(b * 0.97), int(b * 0.88))
            a = int(120 + mag[i] * 135)
        sd.ellipse([xs[i] - rad, ys[i] - rad, xs[i] + rad, ys[i] + rad], fill=col + (a,))
    return img.convert("RGB")


# ---- roads: LUMPKIN COUNTY, GA (dark only) ---------------------------------
# Dahlonega (county seat) is the dense central hub; primary state/US highways
# radiate to the county edges; rural roads branch off and thin toward the
# mountainous edges; a couple of small community clusters imply other towns.
# A soft county-boundary polygon frames the extent instead of a tight 5mi circle.
def render_roads(W, H, pal):
    arr = base_gradient(W, H, pal)
    img = to_rgba(arr)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    r = rng(1867)
    cx, cy = W * 0.52, H * 0.50   # Dahlonega, roughly county centre
    RC = min(W, H) * 0.62         # county "radius" (fills most of the frame)
    nodes = []

    # Irregular county-boundary polygon (stylised Lumpkin outline), used both as a
    # framing outline and to keep roads inside the county extent.
    r.random()  # advance
    nb = 22
    bpts = []
    for i in range(nb):
        ang = i / nb * math.tau
        # lumpy radius: rural county with an irregular border
        rr = RC * (0.90 + 0.16 * math.sin(ang * 3 + 0.6) + 0.09 * math.cos(ang * 5 - 1.1))
        bpts.append((cx + rr * math.cos(ang) * 1.02, cy + rr * math.sin(ang) * 0.86))

    def in_county(x, y):
        # point-in-polygon (even-odd) against the boundary
        inside = False
        j = len(bpts) - 1
        for i in range(len(bpts)):
            xi, yi = bpts[i]
            xj, yj = bpts[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
                inside = not inside
            j = i
        return inside

    ag, ab = pal["art_green"], pal["art_blue"]

    def col(x, a):
        return mix(ag, ab, min(1.0, max(0.0, x / W))) + (int(a),)

    def road(x0, y0, ang, length, width, depth, curve=0.32):
        nsteps = max(2, int(length / (min(W, H) * 0.02)))
        pts = [(x0, y0)]
        x, y, a = x0, y0, ang
        for _ in range(nsteps):
            a += (r.random() - 0.5) * curve
            seg = length / nsteps
            x += math.cos(a) * seg
            y += math.sin(a) * seg
            if not in_county(x, y):
                break
            pts.append((x, y))
        if len(pts) < 2:
            return
        ld.line(pts, fill=col(x0, 195 if depth == 0 else 150 if depth == 1 else 105),
                width=width, joint="curve")
        nodes.append((pts[0][0], pts[0][1], depth))
        nodes.append((pts[-1][0], pts[-1][1], depth))
        if depth < 3:
            nb_ = 3 if depth == 0 else (2 if depth == 1 else 1)
            for _ in range(nb_):
                if len(pts) > 3:
                    i = 1 + int(r.random() * (len(pts) - 2))
                else:
                    i = 1
                bx, by = pts[i]
                nodes.append((bx, by, depth + 1))
                ba = math.atan2(by - y0, bx - x0) + (1.4 if r.random() < 0.5 else -1.4) + (r.random() - 0.5) * 0.6
                road(bx, by, ba, length * (0.60 - 0.10 * depth),
                     max(1, width - int(W / 3400)), depth + 1, curve + 0.06)

    # --- primary highways radiating from Dahlonega toward the county edges
    #     (GA-60, GA-9, GA-52, US-19 vibe) — named angles + a few extras
    NH = 8
    for i in range(NH):
        ang = i / NH * math.tau + (r.random() - 0.5) * 0.28
        road(cx, cy, ang, RC * 1.15, max(3, int(W / 620)), 0, curve=0.20)

    def grid_cluster(gx0, gy0, cells, cell, rot, marker=False):
        """A small downtown-style street grid centred at (gx0,gy0)."""
        def tp(u, v):
            X = u * cell
            Y = v * cell
            return (gx0 + X * math.cos(rot) - Y * math.sin(rot),
                    gy0 + X * math.sin(rot) + Y * math.cos(rot))
        half = cells
        lw = max(1, int(W / 1100)) if marker else max(1, int(W / 1500))
        aa = 155 if marker else 120
        for gx in range(-half, half + 1):
            ld.line([tp(gx, -half), tp(gx, half)], fill=col(gx0, aa), width=lw)
            ld.line([tp(-half, gx), tp(half, gx)], fill=col(gx0, aa), width=lw)
        if marker:
            sq = cell * 0.9
            ld.rectangle([gx0 - sq, gy0 - sq, gx0 + sq, gy0 + sq],
                         outline=GREEN + (230,), width=max(2, int(W / 900)))

    # Dahlonega downtown grid + green square marker
    grid_cluster(cx, cy, 3, min(W, H) * 0.055, 0.3, marker=True)

    # 1–2 secondary community clusters (other Lumpkin communities) offset from town
    grid_cluster(cx - RC * 0.55, cy - RC * 0.42, 2, min(W, H) * 0.030, -0.4)
    grid_cluster(cx + RC * 0.60, cy + RC * 0.30, 2, min(W, H) * 0.032, 0.5)

    # extra rural connectors seeded around the county interior (sparser out toward edges)
    for _ in range(10):
        ang = r.random() * math.tau
        rad = RC * (0.30 + 0.55 * r.random())
        sx = cx + math.cos(ang) * rad
        sy = cy + math.sin(ang) * rad * 0.86
        if not in_county(sx, sy):
            continue
        road(sx, sy, r.random() * math.tau, RC * (0.28 + 0.30 * r.random()),
             max(1, int(W / 1400)), 1, curve=0.45)

    # intersection nodes
    for (nx, ny, dep) in nodes:
        rr = max(1.2, (W / 780) * (1.0 - 0.20 * dep))
        c = mix(ag, ab, min(1.0, nx / W))
        ld.ellipse([nx - rr, ny - rr, nx + rr, ny + rr], fill=c + (215,))

    # subtle county-boundary outline (thin, low alpha)
    b_col = (74, 85, 112) if pal["light"] else (150, 165, 190)
    ld.line(bpts + [bpts[0]], fill=b_col + (85 if pal["light"] else 70,),
            width=max(1, int(W / 2600)), joint="curve")

    img = Image.alpha_composite(img, layer).convert("RGB")

    # soft county-shaped vignette toward the field edge (expanded — network fills frame)
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.polygon(bpts, fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(RC * 0.10))
    edge = Image.new("RGB", (W, H), (223, 228, 238) if pal["light"] else (9, 12, 19))
    img = Image.composite(img, edge, vig)
    return img


# ============================================================================
# SPECS + main
# ============================================================================
STYLES = [
    ("sysible-topographic", render_topographic, True),
    ("sysible-topographic-ridge", render_topographic_ridge, True),
    ("sysible-neural", render_neural, True),
    ("sysible-cosmos", render_cosmos, True),
    ("sysible-roads", render_roads, True),   # Lumpkin County, GA — dark + light
]


def render_one(name, fn, light, W, H, save_full, test):
    pal = palette(light)
    img = fn(W, H, pal)          # RGB
    img = draw_banner(img.convert("RGBA"), pal).convert("RGB")
    suffix = "-light" if light else ""
    if save_full and not test:
        full_path = os.path.join(OUT_DIR, f"{name}{suffix}.jpg")
        img.save(full_path, "JPEG", quality=QUALITY)
    else:
        full_path = None
    # preview
    pw = PREVIEW_W
    ph = int(H * pw / W)
    prev = img.resize((pw, ph), Image.LANCZOS)
    prev_path = os.path.join(PREVIEW_DIR, f"{name}{suffix}.jpg")
    prev.save(prev_path, "JPEG", quality=90)
    return full_path, prev_path


def main():
    test = "--test" in sys.argv
    W, H = (1600, 900) if test else (FULL_W, FULL_H)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    written = []
    for name, fn, has_light in STYLES:
        modes = [False, True] if has_light else [False]
        for light in modes:
            fp, pp = render_one(name, fn, light, W, H, save_full=True, test=test)
            tag = f"{name}{'-light' if light else ''}"
            if fp:
                sz = os.path.getsize(fp)
                written.append((fp, sz))
                print(f"[full ] {tag:34s} {sz/1e6:6.2f} MB  {fp}")
            else:
                print(f"[test ] {tag:34s}  preview -> {pp}")
    # remove obsolete circuit background
    circ = os.path.join(OUT_DIR, "sysible-circuit.jpg")
    if os.path.exists(circ) and not test:
        os.remove(circ)
        print(f"[rm   ] removed obsolete {circ}")
    print(f"\n{len(written)} full images written; previews in {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
