"""`sysible ai` — a local-model companion that explains terminal errors.

Everything runs against a LOCAL model server; nothing leaves the machine. By
default it talks to Ollama's HTTP API (http://127.0.0.1:11434), but any
OpenAI-compatible local server (llama.cpp `server`, LM Studio, vLLM, or Ollama's
own /v1 shim) works by pointing SYSIBLE_AI_URL/SYSIBLE_AI_BACKEND at it.

Stdlib only (urllib/json) so it ships with the dependency-free sysible-cli.

Config (env):
  SYSIBLE_AI_URL      base URL of the model server   (default http://127.0.0.1:11434)
  SYSIBLE_AI_MODEL    model name                      (default qwen2.5-coder:7b)
  SYSIBLE_AI_BACKEND  "ollama" | "openai"             (default: auto from URL)
  SYSIBLE_AI_KEY      bearer token for openai backend (optional; local servers ignore it)
"""
import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# Network failures we render as clean, user-facing guidance (never a traceback).
_NET_ERRORS = (urllib.error.URLError, OSError, http.client.HTTPException)

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"

SYSTEM_PROMPT = (
    "You are Sysible AI, a terse Linux troubleshooting assistant built into Sysible "
    "Linux (a Debian-based engineering workstation; package manager is apt). You are "
    "given a shell command, its exit code, and its output. Respond in this shape, and "
    "keep it tight:\n"
    "1. **Cause** — one or two sentences on what actually went wrong.\n"
    "2. **Fix** — the concrete command(s) to run, in a fenced block. Prefer the "
    "minimal, safe fix. Use apt/systemctl/Debian conventions.\n"
    "3. **Note** — only if a command is destructive or risky, say so in one line; "
    "otherwise omit.\n"
    "Do not pad with pleasantries. If the output does not actually contain an error, "
    "say so briefly."
)


class AIError(Exception):
    """A user-facing failure (server down, model missing, etc.)."""


def _cfg():
    url = os.environ.get("SYSIBLE_AI_URL", DEFAULT_URL).rstrip("/")
    model = os.environ.get("SYSIBLE_AI_MODEL", DEFAULT_MODEL)
    backend = os.environ.get("SYSIBLE_AI_BACKEND")
    if not backend:
        # Default to Ollama (the shipped/expected runtime). Only assume an
        # OpenAI-compatible server (llama.cpp `server`, LM Studio, vLLM) when the
        # URL explicitly points at a /v1 base — that's how those are configured.
        backend = "openai" if url.rstrip("/").endswith("/v1") else "ollama"
    return url, model, backend


def _http(url, data=None, headers=None, method="GET", timeout=300):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers or {},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=timeout)


# --- server / model preflight ----------------------------------------------
def _ollama_models(url):
    try:
        with _http(f"{url}/api/tags", timeout=5) as r:
            tags = json.load(r)
        return [m.get("name", "") for m in tags.get("models", [])]
    except Exception:
        return None  # server not reachable


def _ensure_ready(url, model, backend, auto_pull, out):
    """Raise AIError with actionable guidance if the local model isn't usable."""
    if backend != "ollama":
        return  # generic servers: fail lazily at request time
    models = _ollama_models(url)
    if models is None:
        raise AIError(
            f"No local model server answered at {url}.\n"
            "  Start it:   ollama serve   (or: systemctl --user start ollama)\n"
            "  Install it: https://ollama.com/download   (Debian: curl -fsSL "
            "https://ollama.com/install.sh | sh)\n"
            "  Point elsewhere: export SYSIBLE_AI_URL=http://host:port"
        )
    # Ollama tags carry a :tag; match with or without an explicit :latest.
    have = set(models) | {m.split(":")[0] for m in models}
    if model not in have and model.split(":")[0] not in have:
        if auto_pull:
            out.write(f"sysible ai: pulling {model} (first run)…\n")
            out.flush()
            _ollama_pull(url, model, out)
        else:
            raise AIError(
                f"Model '{model}' isn't downloaded yet on the local server.\n"
                f"  Pull it:  ollama pull {model}\n"
                f"  Or pick another: export SYSIBLE_AI_MODEL=<name>   "
                f"(installed: {', '.join(models) or 'none'})\n"
                f"  Or let me:  sysible ai --pull …"
            )


def _ollama_pull(url, model, out):
    try:
        with _http(f"{url}/api/pull", data={"name": model, "stream": True},
                   headers={"Content-Type": "application/json"}, method="POST",
                   timeout=3600) as r:
            last = ""
            for line in r:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                status = msg.get("status", "")
                if status and status != last:
                    out.write(f"  {status}\n")
                    out.flush()
                    last = status
                if msg.get("error"):
                    raise AIError(f"pull failed: {msg['error']}")
    except _NET_ERRORS as e:
        raise AIError(f"could not pull {model}: {e}")


# --- chat streaming ---------------------------------------------------------
def _stream_ollama(url, model, messages, out):
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        with _http(f"{url}/api/chat", data=payload,
                   headers={"Content-Type": "application/json"}, method="POST") as r:
            for line in r:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise AIError(msg["error"])
                chunk = msg.get("message", {}).get("content", "")
                if chunk:
                    out.write(chunk)
                    out.flush()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if "not found" in body.lower():
            raise AIError(f"model '{model}' not found — run: ollama pull {model}")
        raise AIError(f"server error {e.code}: {body[:300]}")
    except _NET_ERRORS as e:
        raise AIError(f"cannot reach model server at {url}: {e}")
    out.write("\n")


def _stream_openai(url, model, messages, out):
    key = os.environ.get("SYSIBLE_AI_KEY", "local")
    payload = {"model": model, "messages": messages, "stream": True}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    base = url if url.endswith("/v1") else f"{url}/v1"
    try:
        with _http(f"{base}/chat/completions", data=payload, headers=headers,
                   method="POST") as r:
            for line in r:
                line = line.decode(errors="replace").strip() if isinstance(line, bytes) else line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    out.write(delta)
                    out.flush()
    except urllib.error.HTTPError as e:
        raise AIError(f"server error {e.code}: {e.read().decode(errors='replace')[:300]}")
    except _NET_ERRORS as e:
        raise AIError(f"cannot reach model server at {base}: {e}")
    out.write("\n")


# --- context gathering ------------------------------------------------------
def _distro():
    try:
        with open("/etc/os-release") as f:
            kv = dict(
                line.rstrip().split("=", 1) for line in f if "=" in line
            )
        return kv.get("PRETTY_NAME", "").strip('"') or "Sysible Linux"
    except OSError:
        return "Sysible Linux"


def _trim(text, max_chars=6000):
    """Keep the tail — errors live at the end — but cap the payload sent to the model."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    return "…(truncated)…\n" + text[-max_chars:]


def _build_messages(command, exit_code, output, question):
    ctx = [f"Distro: {_distro()}"]
    cwd = os.environ.get("PWD") or ""
    if cwd:
        ctx.append(f"CWD: {cwd}")
    parts = ["\n".join(ctx)]
    if command:
        parts.append(f"Command:\n{command}")
    if exit_code is not None:
        parts.append(f"Exit code: {exit_code}")
    if output:
        parts.append(f"Output:\n{_trim(output)}")
    if question:
        parts.append(f"Question: {question}")
    user = "\n\n".join(parts)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def analyze(command=None, exit_code=None, output=None, question=None,
            auto_pull=False, out=None):
    out = out or sys.stdout
    url, model, backend = _cfg()
    _ensure_ready(url, model, backend, auto_pull, out)
    messages = _build_messages(command, exit_code, output, question)
    if backend == "ollama":
        _stream_ollama(url, model, messages, out)
    else:
        _stream_openai(url, model, messages, out)


# --- CLI entry --------------------------------------------------------------
def add_parser(sub):
    p = sub.add_parser(
        "ai",
        aliases=["explain"],
        help="Explain a terminal error with a LOCAL model (Ollama / OpenAI-compatible).",
        description="Analyze a failed command or error output using a local LLM. "
                    "Reads piped stdin, a --cmd to run, or a free-form question.",
    )
    p.add_argument("question", nargs="*", help="Free-form question or error text.")
    p.add_argument("--cmd", metavar="CMD",
                   help="Run CMD, capture its output+exit code, and analyze it.")
    p.add_argument("--command", metavar="STR", default=None,
                   help="The command string, as context (does NOT run it; pair with piped output).")
    p.add_argument("--exit-code", type=int, default=None,
                   help="Exit code of the command whose output you're piping in.")
    p.add_argument("--pull", action="store_true",
                   help="Download the model automatically if it's missing.")
    p.set_defaults(func=cmd_ai)
    return p


def cmd_ai(args) -> int:
    command = None
    exit_code = args.exit_code
    output = None
    question = " ".join(args.question) if args.question else None

    if args.command:
        command = args.command
    if args.cmd:
        command = args.cmd
        proc = subprocess.run(args.cmd, shell=True, capture_output=True, text=True)
        output = (proc.stdout or "") + (proc.stderr or "")
        exit_code = proc.returncode
        # Echo what happened so the user sees the real output too.
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.write(f"[exit {exit_code}]\n\n")
    elif not sys.stdin.isatty():
        output = sys.stdin.read()

    if not (output or question):
        sys.stderr.write(
            "sysible ai: nothing to analyze.\n"
            "  Pipe output:   make 2>&1 | sysible ai\n"
            "  Run a command: sysible ai --cmd 'systemctl status foo'\n"
            "  Ask directly:  sysible ai \"why is apt holding broken packages\"\n"
            "  In a shell:    a failed command prints  →  sai !!\n"
        )
        return 2

    try:
        analyze(command=command, exit_code=exit_code, output=output,
                question=question, auto_pull=args.pull)
    except AIError as e:
        sys.stderr.write(f"sysible ai: {e}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
    return 0
