# Sysible AI — local-model terminal companion (shell ergonomics).
# Provides `sai` and, for interactive bash, a subtle hint after a command fails.
# The heavy lifting is in `sysible ai` (Python); this just captures output/exit.
# Everything runs against a LOCAL model server — nothing leaves the machine.

# `sai` — explain a command's failure with a local model.
#   sai <command>      run it (output shown live); if it fails, explain it
#   <command> |& sai   explain piped output
#   sai !!             explain the previous command (bash expands !! first)
sai() {
    if [ "$#" -eq 0 ]; then
        if [ -t 0 ]; then
            printf 'usage: sai <command>      run it; explain if it fails\n' >&2
            printf '       <command> |%s sai   explain piped output\n' '&' >&2
            printf '       sai !!             explain the previous command\n' >&2
            return 2
        fi
        sysible ai            # piped input: analyze stdin directly
        return $?
    fi
    local _tmp _rc
    _tmp=$(mktemp) || { sysible ai --command "$*"; return $?; }
    # Run it, show output live, capture it. PIPESTATUS[0] keeps the command's
    # real exit code (not tee's), and the pipe guarantees $_tmp is complete.
    { "$@"; } 2>&1 | tee "$_tmp"
    _rc=${PIPESTATUS[0]}
    if [ "$_rc" -ne 0 ]; then
        printf '\n\033[2m─ sysible ai · analyzing (exit %d) ─\033[0m\n' "$_rc"
        sysible ai --command "$*" --exit-code "$_rc" < "$_tmp"
    fi
    rm -f "$_tmp"
    return "$_rc"
}

# Optional post-command hint. After a command fails, print a dim one-liner
# pointing at `sai !!`. Skipped for commands that routinely exit non-zero
# (grep no-match, tests, diffs) so it isn't noisy. Disable with SYSIBLE_AI_HINT=0.
if [ -n "$BASH_VERSION" ] && [ -n "$PS1" ]; then
    __sysible_ai_hint() {
        local _rc=$?
        [ "${SYSIBLE_AI_HINT:-1}" = 0 ] && return "$_rc"
        # Inside SysTerm's Atlas pane, the failure is surfaced there — no text hint.
        [ -n "$SYSIBLE_ATLAS_FIFO" ] && return "$_rc"
        if [ "$_rc" -ne 0 ] && [ "$_rc" -ne 130 ]; then
            local _last _w
            _last=$(HISTTIMEFORMAT= history 1 2>/dev/null | sed 's/^ *[0-9]*[ *]*//')
            _w=${_last%% *}
            case "$_w" in
                grep|egrep|fgrep|rg|ag|test|'['|'[['|diff|cmp|pgrep|pkill|find|'') return "$_rc" ;;
            esac
            printf '\033[2m✦ exit %d · explain: \033[0m\033[1msai !!\033[0m\n' "$_rc"
        fi
        return "$_rc"
    }
    case ";${PROMPT_COMMAND};" in
        *";__sysible_ai_hint;"*) : ;;
        *) PROMPT_COMMAND="__sysible_ai_hint;${PROMPT_COMMAND:-}" ;;
    esac
fi

# --- Sysible Atlas: SysTerm AI companion integration -----------------------
# When bash runs inside SysTerm with the Atlas pane wired, a per-pane FIFO is
# exported ($SYSIBLE_ATLAS_FIFO) plus a pane id ($SYSIBLE_ATLAS_ID). We write
# two message kinds to it (base64 payloads, tab-separated, one line each — small
# enough to be an atomic FIFO write): a failed command, and an `ai`/`atlas`
# question. SysTerm keeps the read end open, so these writes never block. The
# companion reads THIS pane's on-screen output itself, so we send only the
# command/question, never the output.
if [ -n "$BASH_VERSION" ] && [ -n "$PS1" ] && [ -n "$SYSIBLE_ATLAS_FIFO" ] && [ -p "$SYSIBLE_ATLAS_FIFO" ]; then
    # Ask the companion a question:  ai <question>   (alias: atlas <question>)
    atlas() {
        if [ "$#" -eq 0 ]; then
            printf 'usage: ai <question>   (answered in the Atlas pane)\n' >&2
            return 2
        fi
        printf 'ask\t%s\t%s\n' "$SYSIBLE_ATLAS_ID" \
            "$(printf '%s' "$*" | base64 | tr -d '\n')" > "$SYSIBLE_ATLAS_FIFO" 2>/dev/null || true
    }
    ai() { atlas "$@"; }

    # After a command fails, hand it to the companion (unless it's one that
    # routinely exits non-zero). Silence with SYSIBLE_ATLAS_AUTO=0.
    __atlas_prompt() {
        local _rc=$?
        [ "${SYSIBLE_ATLAS_AUTO:-1}" = 0 ] && return "$_rc"
        if [ "$_rc" -ne 0 ] && [ "$_rc" -ne 130 ]; then
            local _last _w
            _last=$(HISTTIMEFORMAT= history 1 2>/dev/null | sed 's/^ *[0-9]*[ *]*//')
            _w=${_last%% *}
            case "$_w" in
                grep|egrep|fgrep|rg|ag|test|'['|'[['|diff|cmp|pgrep|pkill|find|ai|atlas|sai|'') return "$_rc" ;;
            esac
            printf 'error\t%s\t%s\t%s\n' "$SYSIBLE_ATLAS_ID" "$_rc" \
                "$(printf '%s' "$_last" | base64 | tr -d '\n')" > "$SYSIBLE_ATLAS_FIFO" 2>/dev/null || true
        fi
        return "$_rc"
    }
    case ";${PROMPT_COMMAND};" in
        *";__atlas_prompt;"*) : ;;
        *) PROMPT_COMMAND="__atlas_prompt;${PROMPT_COMMAND:-}" ;;
    esac
fi
