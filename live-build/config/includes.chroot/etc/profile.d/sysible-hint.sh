# Sysible: one line at login about the software on this machine — what to install
# when nothing is, and what is behind its release once something is. Interactive
# logins only, never the network (sysible-hint reads a file a timer wrote), and
# never fatal: a hint that breaks a login shell is worse than no hint.
case "$-" in
    *i*)
        if [ -x /usr/local/bin/sysible-hint ]; then
            /usr/local/bin/sysible-hint 2>/dev/null || true
        fi
        ;;
esac
