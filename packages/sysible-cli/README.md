# sysible-cli

The `sysible` command for Sysible Workstation.

## `sysible verify`

Validate the system is ready for engineering work (containers, tools, services).
Run `sysible verify --help` for group flags and `--json`.

## `sysible ai` — local-model terminal companion

Explain a failed command or error output using a **local** LLM. Nothing leaves
the machine — it talks to a local model server (Ollama by default, or any
OpenAI-compatible server such as llama.cpp `server` / LM Studio / vLLM).

```
make 2>&1 | sysible ai                     # pipe output in
sysible ai --cmd 'systemctl status nginx'  # run a command and analyze it
sysible ai "why does apt hold broken packages"   # ask directly
sai <command>                              # run it; explain automatically if it fails
sai !!                                     # explain the previous command
```

After a command fails in an interactive shell, a dim hint suggests `sai !!`
(disable with `SYSIBLE_AI_HINT=0`).

### Setup

Point it at a local runtime and model:

```
# Ollama (default): install once, then pull a model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b        # or a smaller model on low-RAM machines:
ollama pull qwen2.5-coder:3b
```

### Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `SYSIBLE_AI_URL` | `http://127.0.0.1:11434` | Model server base URL |
| `SYSIBLE_AI_MODEL` | `qwen2.5-coder:7b` | Model name |
| `SYSIBLE_AI_BACKEND` | auto | `ollama`, or `openai` for a `/v1` server |
| `SYSIBLE_AI_KEY` | — | Bearer token for an OpenAI-compatible server (optional) |
| `SYSIBLE_AI_HINT` | `1` | Set `0` to silence the post-failure hint |

Add `--pull` to let `sysible ai` download the model automatically on first use.
