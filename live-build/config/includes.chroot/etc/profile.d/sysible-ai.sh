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
