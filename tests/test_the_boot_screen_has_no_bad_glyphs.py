"""Text a bootloader draws must be ASCII, or the glyph comes out as garbage.

Reported as "the install menu at the beginning has a bugged out & symbol": the
GRUB theme's footer label read

    text = "Sysible Workstation — ..."

with an EM DASH (U+2014). The theme says so itself -- "Fonts are the GRUB
default (no .pf2 needed)" -- and the default font has no glyph at U+2014, so
GRUB draws a replacement box where the dash should be. On the first screen the
operator ever sees.

A bootloader is not a desktop. GRUB renders theme labels with whatever font is
loaded at that moment, isolinux's MENU LABEL is drawn from a VGA-era bitmap
font, and neither has the fallback chain that makes a stray em dash harmless in
an ordinary GUI. So the rule here is the blunt one: if a bootloader has to draw
it, it is ASCII.

Comments are exempt -- GRUB never renders a # line, and this very file is full
of them.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOOT = ROOT / "live-build" / "config"

# Values a bootloader actually draws, as opposed to paths, colours and geometry.
THEME_DRAWN = re.compile(r'^\s*(?:text|title-text)\s*[:=]\s*"([^"]*)"', re.M)
MENU_DRAWN = re.compile(r'^\s*(?:menu label|menuentry)\s+\^?"?([^"\n]*)"?', re.M | re.I)


def _strip_comments(text: str, char: str = "#") -> str:
    return "\n".join(l.split(char)[0] for l in text.splitlines())


def _offenders(label: str, value: str):
    return [(label, c, hex(ord(c))) for c in value if ord(c) > 127]


def _boot_files():
    pats = ("includes.chroot/boot/grub/themes/*/theme.txt", "binary_grub/*.cfg",
            "bootloaders/isolinux/*.cfg", "includes.binary/boot/grub/*.cfg")
    out = []
    for p in pats:
        out += sorted(BOOT.glob(p))
    return out


def test_the_boot_screen_has_no_glyph_the_bootloader_cannot_draw():
    files = _boot_files()
    assert files, f"no bootloader config found under {BOOT} -- the guard would pass vacuously"
    bad = []
    for f in files:
        body = _strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        for rx in (THEME_DRAWN, MENU_DRAWN):
            for m in rx.finditer(body):
                bad += _offenders(f"{f.relative_to(ROOT)}: {m.group(1)!r}", m.group(1))
    assert not bad, "non-ASCII in text a bootloader must draw:\n" + "\n".join(
        f"  {w}  ->  {c!r} ({h})" for w, c, h in bad)


def test_the_build_does_not_reintroduce_one_when_it_rebrands_the_menu():
    """build.sh rewrites the generated menu labels, inside embedded python
    heredocs. A dash pasted into one of those replacement strings or cloned
    entry titles lands on the same screen by a different route, where a check
    that only reads the shipped config files cannot see it.

    Log output is exempt: an em dash in an `echo` goes to the CI log, which is
    UTF-8 and reads it fine. The rule applies to the blocks that WRITE boot
    configuration."""
    build = ROOT / "live-build" / "build.sh"
    if not build.is_file():
        pytest.skip("no live-build/build.sh")
    src = build.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks, cur = [], None
    for line in src:
        if cur is None:
            if "<<'PY'" in line:
                cur = []
        elif line.strip() == "PY":
            blocks.append("\n".join(cur)); cur = None
        else:
            cur.append(line)
    if not blocks:
        pytest.skip("build.sh patches no boot config inline")
    bad = []
    for i, b in enumerate(blocks):
        for n, line in enumerate(_strip_comments(b).splitlines(), 1):
            bad += _offenders(f"build.sh boot-patch block {i + 1} line {n}: {line.strip()!r}", line)
    assert not bad, (
        "non-ASCII in a block that writes boot menu text:\n"
        + "\n".join(f"  {w}  ->  {c!r} ({h})" for w, c, h in bad))


def test_the_guard_can_actually_see_a_bad_character():
    """A positive control. The regexes above must match the shape these files
    really use, or both tests pass by matching nothing at all."""
    sample = '    text = "Sysible — thing"\n    menu label ^Install — now\n'
    hits = [m.group(1) for rx in (THEME_DRAWN, MENU_DRAWN) for m in rx.finditer(sample)]
    assert len(hits) == 2, hits
    assert all(_offenders("x", h) for h in hits), hits
    # ...and it must find the real theme's footer, so the glob is not empty talk.
    themes = [f for f in _boot_files() if f.name == "theme.txt"]
    assert themes, "the GRUB theme is not being read by this guard"
    drawn = [m.group(1) for t in themes
             for m in THEME_DRAWN.finditer(_strip_comments(t.read_text()))]
    assert any("Sysible" in d for d in drawn), drawn
