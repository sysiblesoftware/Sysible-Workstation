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

# (The post-command "✦ exit N · explain: sai !!" auto-hint has been removed —
# nothing prints automatically after a failed command. The `sai` command above
# stays available for on-demand explanations, and the SysTerm Atlas integration
# below is unaffected.)

# --- Sysible Atlas: SysTerm AI companion integration -----------------------
# When bash runs inside SysTerm with the Atlas pane wired, a per-pane FIFO is
# exported ($SYSIBLE_ATLAS_FIFO) plus a pane id ($SYSIBLE_ATLAS_ID). We write
# two message kinds to it (base64 payloads, tab-separated, one line each — small
# enough to be an atomic FIFO write): a failed command, and an `ai`/`atlas`
# question. SysTerm keeps the read end open, so these writes never block. The
# companion reads THIS pane's on-screen output itself, so we send only the
# command/question, never the output.
if [ -n "$BASH_VERSION" ] && [ -n "$PS1" ] && [ -n "$SYSIBLE_ATLAS_FIFO" ] && [ -p "$SYSIBLE_ATLAS_FIFO" ]; then
    # Capture the command AS IT RUNS (DEBUG trap), not from `history` afterwards —
    # so a git-in-your-prompt helper or a PROMPT_COMMAND function can't be mistaken
    # for the command you actually typed. Only top-level commands are recorded; PS1
    # $(...) run in subshells that don't fire DEBUG. After a command fails, hand it
    # to the companion (skip ones that routinely exit non-zero). Silence with
    # SYSIBLE_ATLAS_AUTO=0.
    __atlas_cmd=""
    __atlas_debug() {
        [ -n "$COMP_LINE" ] && return
        [ "${#FUNCNAME[@]}" -le 1 ] || return
        case "$BASH_COMMAND" in
            __atlas_*|__sysible_*) return ;;
        esac
        __atlas_cmd=$BASH_COMMAND
    }
    trap '__atlas_debug' DEBUG

    __atlas_prompt() {
        local _rc=$?
        # Skip the FIRST prompt of each shell: it fires right after bashrc/profile
        # sourcing, whose leftover $? and captured command would surface as a
        # phantom "zombie" catch before you've run anything.
        if [ -z "$__atlas_ready" ]; then
            __atlas_ready=1
            __atlas_cmd=""
            return "$_rc"
        fi
        if [ "${SYSIBLE_ATLAS_AUTO:-1}" != 0 ] && [ "$_rc" -ne 0 ] \
           && [ "$_rc" -ne 130 ] && [ -n "$__atlas_cmd" ]; then
            local _w=${__atlas_cmd%% *}
            case "$_w" in
                grep|egrep|fgrep|rg|ag|test|'['|'[['|diff|cmp|pgrep|pkill|find|ai|atlas|sai|'') : ;;
                *)
                    printf 'error\t%s\t%s\t%s\n' "$SYSIBLE_ATLAS_ID" "$_rc" \
                        "$(printf '%s' "$__atlas_cmd" | base64 | tr -d '\n')" \
                        > "$SYSIBLE_ATLAS_FIFO" 2>/dev/null || true
                    ;;
            esac
        fi
        __atlas_cmd=""
        return "$_rc"
    }
    case ";${PROMPT_COMMAND};" in
        *";__atlas_prompt;"*) : ;;
        *) PROMPT_COMMAND="__atlas_prompt;${PROMPT_COMMAND:-}" ;;
    esac
fi
