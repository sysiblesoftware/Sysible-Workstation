"""`sysible` command entry point."""
import argparse
import json
import os
import sys

from . import __version__
from . import verify as V

_GLYPH = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "–"}
_COLOR = {"ok": "32", "warn": "33", "fail": "31", "skip": "90"}


def _use_color(stream) -> bool:
    return stream.isatty() and os.environ.get("NO_COLOR") is None


def _paint(status: str, text: str, color: bool) -> str:
    if not color:
        return text
    return f"\033[{_COLOR.get(status, '0')}m{text}\033[0m"


def _cmd_verify(args) -> int:
    groups = set()
    for flag, g in V.GROUP_FLAGS.items():
        if getattr(args, flag, False):
            groups |= g
    results = V.evaluate(V.select(groups or None))

    if args.json:
        overall = _overall(results)
        print(json.dumps({"ready": overall == "ready", "overall": overall,
                          "checks": results}, indent=2))
        return 0 if overall == "ready" else 1

    color = _use_color(sys.stdout)
    for r in results:
        g = _GLYPH[r["status"]]
        line = f"  {_paint(r['status'], g, color)} {r['label']}"
        if r["detail"]:
            line += f"  \033[90m{r['detail']}\033[0m" if color else f"  ({r['detail']})"
        print(line)

    overall = _overall(results)
    print()
    if overall == "ready":
        print(_paint("ok", "System Ready", color))
        return 0
    if overall == "degraded":
        print(_paint("warn", "System usable — review the warnings above", color))
        return 0
    print(_paint("fail", "Not ready — critical checks failed", color))
    return 1


def _overall(results) -> str:
    if any(r["status"] == "fail" and r["critical"] for r in results):
        return "not-ready"
    if any(r["status"] in ("warn", "fail") for r in results):
        return "degraded"
    return "ready"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sysible", description="Sysible Linux command-line tool.")
    p.add_argument("-V", "--version", action="version", version=f"sysible {__version__}")
    sub = p.add_subparsers(dest="command")

    pv = sub.add_parser("verify", help="Validate the system is ready for engineering work.")
    pv.add_argument("--json", action="store_true", help="Machine-readable output.")
    for flag in V.GROUP_FLAGS:
        pv.add_argument(f"--{flag}", action="store_true", help=f"Run only the {flag} checks.")
    pv.set_defaults(func=_cmd_verify)

    # `sysible ai` (alias `sysible explain`) — local-model error companion.
    from . import ai as _ai
    _ai.add_parser(sub)

    args = p.parse_args(argv)
    # Dispatch on the resolved handler, not the subparser name: argparse leaves
    # the subparsers `dest` (command) as None when an ALIAS is used (e.g.
    # `sysible explain`), but still applies that subparser's set_defaults(func=…).
    if not hasattr(args, "func"):
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
