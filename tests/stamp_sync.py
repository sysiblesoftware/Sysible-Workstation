"""Stamp (or check) the sync-sha256 header on files shipped in more than one repo.

`install-sysible` ships byte-identical on Sysible Workstation and Sysible Server.
They used to be two copies and they drifted — silently, for long enough that
"install the Sysible software" meant something different on each edition. The
header line is the guard: each repo's tests recompute it, so editing one copy
without restamping fails in that repo alone, immediately, with no need for the
other repo to be checked out. And since the hash covers everything else in the
file, two copies can only carry the same stamp by being the same file.

    python tests/stamp_sync.py            # rewrite the header in place
    python tests/stamp_sync.py --check    # verify it (what the tests do)
"""
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLACEHOLDER = "0" * 64
HEADER = "# sync-sha256: "

# Files that must stay identical across the edition repos.
SHARED = [
    "live-build/config/includes.chroot/usr/local/bin/install-sysible",
    "live-build/config/includes.chroot/usr/local/bin/sysible-hint",
    "live-build/config/includes.chroot/usr/local/bin/sysible-release-check",
]


def digest(text: str) -> str:
    """Hash the file with its own stamp blanked, so the stamp can live inside it."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith(HEADER):
            line = HEADER + PLACEHOLDER + "\n"
        out.append(line)
    return hashlib.sha256("".join(out).encode()).hexdigest()


def stamped(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(HEADER):
            return line[len(HEADER):].strip()
    return None


def restamp(text: str) -> str:
    want = digest(text)
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith(HEADER):
            line = HEADER + want + "\n"
        out.append(line)
    return "".join(out)


def main(argv):
    check = "--check" in argv
    bad = 0
    for rel in SHARED:
        p = REPO / rel
        text = p.read_text()
        if stamped(text) is None:
            print(f"{rel}: no '{HEADER.strip()}' line", file=sys.stderr)
            bad = 1
            continue
        want = digest(text)
        if stamped(text) == want:
            print(f"{rel}: ok ({want[:12]}…)")
            continue
        if check:
            print(f"{rel}: stamp is {stamped(text)[:12]}…, content hashes to "
                  f"{want[:12]}… — run: python tests/stamp_sync.py", file=sys.stderr)
            bad = 1
        else:
            p.write_text(restamp(text))
            print(f"{rel}: stamped {want[:12]}…")
    return bad


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
