"""8.8.8.8 must be the LAST nameserver, and it must survive a lease renewal.

Reported as "I changed resolv.conf to 8.8.8.8 but it changed back. Why?" --
which is the expected behaviour, not a fault: dhclient regenerates
/etc/resolv.conf from the lease on every renewal, so an edit to that file is
overwritten by design. The setting has to go where the file is generated.

Confirmed against the real isc-dhcp-client package rather than assumed:

  * /etc/dhcp/dhclient-enter-hooks.d/ is shipped by the package;
  * /sbin/dhclient-script sources it (run_hookdir, line 256) BEFORE it calls
    make_resolv_conf (lines 354, 427, 460);
  * make_resolv_conf writes one `nameserver` line per entry of
    $new_domain_name_servers, in order.

So setting that variable in an enter hook decides what resolv.conf says, on
every lease. dhclient.conf's own `prepend domain-name-servers` would work too,
but that file is a packaged conffile with no conf.d, so shipping one makes
every later apt upgrade stop and ask which copy to keep.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "live-build/config/includes.chroot/etc/dhcp/dhclient-enter-hooks.d/sysible-dns"


def _run(offered):
    """Source the hook exactly as dhclient-script does, and read the result."""
    r = subprocess.run(
        ["sh", "-c", f'new_domain_name_servers="{offered}"; . "{HOOK}"; '
                     f'printf "%s" "$new_domain_name_servers"'],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_hook_ships():
    assert HOOK.is_file(), "nothing sets a default nameserver"


def test_the_hook_is_executable():
    """run-parts only runs executables; a non-executable hook is silently skipped."""
    assert HOOK.stat().st_mode & 0o111, f"{HOOK.name} is not executable, so it never runs"


def test_run_parts_will_actually_run_the_filename():
    """run-parts ignores names outside [a-zA-Z0-9_-], without saying so."""
    r = subprocess.run(["run-parts", "--list", str(HOOK.parent)],
                       capture_output=True, text=True)
    assert HOOK.name in r.stdout, (
        f"run-parts does not list {HOOK.name}, so dhclient-script will never "
        f"source it:\n{r.stdout}{r.stderr}"
    )


def test_it_is_valid_posix_sh():
    """dhclient-script is /bin/sh; a bashism breaks every lease on the host."""
    r = subprocess.run(["sh", "-n", str(HOOK)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_networks_own_resolver_is_asked_first():
    """It used to be 8.8.8.8 first, and that broke every internal name on the
    network. A public resolver answers NXDOMAIN for a LAN hostname, and NXDOMAIN
    is FINAL -- glibc tries the next nameserver on a timeout or a SERVFAIL, never
    on NXDOMAIN -- so the resolver that knew the answer was never asked.

    Reported as "SLEP hostname resolution isn't working, only IP". SLEP is a
    container; docker forwards to the host's resolvers in order, so every lookup
    died at 8.8.8.8. An IP worked because an IP never asks DNS."""
    assert _run("192.168.1.1 192.168.1.2").split()[0] == "192.168.1.1"


def test_google_dns_comes_last():
    assert _run("192.168.1.1 192.168.1.2").split()[-1] == "8.8.8.8"


def test_the_dhcp_servers_keep_their_order_in_front():
    """Prepend, not supersede: the network's own resolver is not taken away."""
    assert _run("192.168.1.1 192.168.1.2").split() == ["192.168.1.1", "192.168.1.2", "8.8.8.8"]


def test_a_lease_with_no_servers_yields_exactly_one():
    """A trailing space here becomes an empty `nameserver` line in resolv.conf."""
    out = _run("")
    assert out == "8.8.8.8", f"expected exactly '8.8.8.8', got {out!r}"


def test_it_does_not_duplicate_when_dhcp_already_offers_it():
    assert _run("8.8.8.8 192.168.1.1").split().count("8.8.8.8") == 1


@pytest.mark.parametrize("offered", ["", "10.0.0.1", "8.8.8.8", "1.1.1.1 10.0.0.1"])
def test_the_result_never_has_an_empty_entry(offered):
    out = _run(offered)
    assert "  " not in out and not out.startswith(" ") and not out.endswith(" "), (
        f"{offered!r} produced {out!r}, which writes a malformed resolv.conf"
    )
