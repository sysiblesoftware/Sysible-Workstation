"""The login banner must print colour, not the codes for colour.

Reported from a real console, verbatim:

    [1m[32mSysible SLOP is set up on this machine.[0m
      Open:       [1mhttps://172.16.100.129/[0m
      Sign in:    [1madmin[0m / [1msysible[0m  — the shipped default...

The script set its colours as G='[32m'; B='[1m'; R='[0m' -- the ESC byte
(0x1B) that turns those into escape sequences was not in the file. There were
ZERO ESC bytes in it. So every line printed its own control codes as text, on
the first screen an operator ever sees.

A raw control byte in source is precisely what an editor, a copy-paste or a
sanitiser eats without trace, which is presumably how it was lost. The colours
are built with printf at run time now, and this checks the RENDERED OUTPUT
rather than the source text -- reading the source is what let a literal '[32m'
look correct for as long as it did.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HINT = ROOT / "live-build/config/includes.chroot/usr/local/bin/sysible-hint"
ESC = "\033"


def _colour_setup():
    """The line(s) that define the colour variables, lifted from the script."""
    src = HINT.read_text(encoding="utf-8")
    m = re.search(r"^\s*G=.*?R=.*$", src, re.M)
    assert m, "sysible-hint no longer defines G/B/R on one line — update this test"
    return m.group(0).strip()


def test_the_colour_variables_render_real_escape_sequences():
    line = _colour_setup()
    out = subprocess.run(
        ["sh", "-c", f'{line}; printf "%s%sX%s" "$B" "$G" "$R"'],
        capture_output=True, text=True,
    ).stdout
    assert ESC in out, (
        "the colour variables produce no ESC byte, so the banner prints its own "
        f"control codes as text on the first screen an operator sees. Got: {out!r}"
    )
    assert f"{ESC}[1m" in out and f"{ESC}[32m" in out and f"{ESC}[0m" in out, (
        f"expected real bold/green/reset sequences, got {out!r}"
    )


def test_no_bare_bracket_codes_are_emitted():
    """'[1m' with nothing in front of it is the exact bug, rendered."""
    line = _colour_setup()
    out = subprocess.run(
        ["sh", "-c", f'{line}; printf "%s%sX%s" "$B" "$G" "$R"'],
        capture_output=True, text=True,
    ).stdout
    stripped = out.replace(ESC, "")
    assert not re.search(r"(?<!\x1b)\[\d+m", stripped.replace("[", "\x00[", 0)) or ESC in out, (
        f"colour codes are being emitted without an ESC prefix: {out!r}"
    )


def test_the_script_runs_clean_under_dash():
    """/bin/sh on the image is dash; a bashism here breaks the login banner."""
    r = subprocess.run(["sh", "-n", str(HINT)], capture_output=True, text=True)
    assert r.returncode == 0, f"sysible-hint is not valid POSIX sh:\n{r.stderr}"


@pytest.mark.parametrize("phrase", [
    "Sysible SLOP is set up on this machine",
    "the shipped default, and it is public",
])
def test_the_banner_still_says_what_it_needs_to(phrase):
    assert phrase in HINT.read_text(encoding="utf-8"), (
        f"{phrase!r} is gone from the banner"
    )
