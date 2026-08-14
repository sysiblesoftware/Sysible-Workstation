"""`sysible verify` — validate that a Sysible Workstation box is ready for engineering work.

Each check returns a Result(status, detail). Status is one of:
    ok    — good to go
    warn  — usable, but something's worth knowing (never fails the run)
    fail  — a critical capability is missing/broken (fails the run)
    skip  — not applicable / not configured on this host

Checks are grouped so `sysible verify --containers` (etc.) runs just one area.
"""
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Result:
    status: str
    detail: str = ""


@dataclass
class Check:
    key: str
    label: str
    group: str
    run: Callable[[], Result]
    critical: bool = True  # a failing non-critical check reports fail but is advisory


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(args, timeout=6) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _systemd_active(unit: str) -> Optional[bool]:
    if not _have("systemctl"):
        return None
    try:
        r = _run(["systemctl", "is-active", unit])
        return r.stdout.strip() == "active"
    except Exception:
        return None


def _first_tool(*cmds) -> Optional[str]:
    for c in cmds:
        if _have(c):
            return c
    return None


def _tcp_open(host: str, port: int, timeout=3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def c_network() -> Result:
    # A routable, non-loopback IPv4 means the box is actually on a network.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 53))  # TEST-NET-1; no packets leave, just picks a src
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return Result(OK, f"outbound source address {ip}")
        return Result(FAIL, "no non-loopback address")
    except OSError:
        return Result(FAIL, "no route to a network")


def c_dns() -> Result:
    for host in ("deb.debian.org", "cloudflare.com"):
        try:
            socket.getaddrinfo(host, 443)
            return Result(OK, f"resolved {host}")
        except socket.gaierror:
            continue
    return Result(FAIL, "DNS resolution failed")


def c_ssh() -> Result:
    active = _systemd_active("ssh")
    if active is None:
        active = _systemd_active("sshd")
    if active:
        return Result(OK, "sshd running")
    if _tcp_open("127.0.0.1", 22, timeout=1):
        return Result(OK, "listening on :22")
    if _have("sshd") or os.path.exists("/usr/sbin/sshd"):
        return Result(WARN, "installed but not running")
    return Result(FAIL, "openssh-server not installed")


def c_docker() -> Result:
    if _have("docker"):
        try:
            if _run(["docker", "info"]).returncode == 0:
                return Result(OK, "docker engine reachable")
        except Exception:
            pass
        return Result(WARN, "docker CLI present, daemon not reachable (add your user to the docker group?)")
    if _have("podman"):
        return Result(OK, "podman present (rootless containers)")
    return Result(FAIL, "no container runtime (docker/podman)")


def c_compose() -> Result:
    if _have("docker") and _run(["docker", "compose", "version"]).returncode == 0:
        return Result(OK, "docker compose v2")
    if _have("docker-compose"):
        return Result(WARN, "legacy docker-compose v1 (prefer the v2 plugin)")
    return Result(WARN, "compose not installed")


def c_ansible() -> Result:
    return Result(OK, "installed") if _have("ansible") else Result(FAIL, "ansible not installed")


def c_iac() -> Result:
    t = _first_tool("terraform", "tofu")
    if t:
        return Result(OK, f"{t} installed")
    return Result(WARN, "no terraform/opentofu")


def c_kubernetes() -> Result:
    have = [c for c in ("kubectl", "helm", "k9s") if _have(c)]
    if "kubectl" in have:
        return Result(OK, "+".join(have))
    return Result(WARN, "kubectl not installed")


def c_cloud() -> Result:
    have = [c for c in ("aws", "az", "gcloud") if _have(c)]
    return Result(OK, "+".join(have)) if have else Result(WARN, "no cloud CLI (aws/az/gcloud)")


def c_virtualization() -> Result:
    kvm = os.path.exists("/dev/kvm")
    libvirt = _systemd_active("libvirtd")
    if kvm and libvirt:
        return Result(OK, "KVM + libvirtd")
    if kvm:
        return Result(WARN, "/dev/kvm present, libvirtd not running")
    return Result(WARN, "no hardware virtualization (/dev/kvm)")


def c_firewall() -> Result:
    if _systemd_active("nftables") or _systemd_active("ufw"):
        return Result(OK, "firewall active")
    if _first_tool("nft", "ufw", "iptables"):
        return Result(WARN, "firewall tools present, not enforcing")
    return Result(WARN, "no firewall configured")


def c_apparmor() -> Result:
    if os.path.exists("/sys/kernel/security/apparmor/profiles"):
        return Result(OK, "AppArmor enabled")
    return Result(WARN, "AppArmor not enabled")


def c_fail2ban() -> Result:
    a = _systemd_active("fail2ban")
    if a:
        return Result(OK, "fail2ban active")
    if _have("fail2ban-client"):
        return Result(WARN, "installed, not running")
    return Result(SKIP, "not installed")


def c_controller() -> Result:
    # Reachable only checked when this host is actually enrolled with a controller.
    cfg = "/etc/sysible/sysible_agent.env"
    url = None
    if os.path.exists(cfg):
        try:
            for line in open(cfg):
                if line.startswith("SYSIBLE_CONTROLLER="):
                    url = line.split("=", 1)[1].strip().split(",")[0]
                    break
        except OSError:
            pass
    if not url:
        return Result(SKIP, "host not enrolled with a controller")
    hostport = url.split("://", 1)[-1]
    host = hostport.split(":")[0]
    port = int(hostport.split(":")[1]) if ":" in hostport else 443
    return Result(OK, f"reachable {host}:{port}") if _tcp_open(host, port) else Result(FAIL, f"unreachable {host}:{port}")


def c_updates() -> Result:
    if not _have("apt-get"):
        return Result(SKIP, "not an apt system")
    try:
        r = _run(["apt-get", "-s", "upgrade"], timeout=30)
        n = sum(1 for ln in r.stdout.splitlines() if ln.startswith("Inst "))
        if n == 0:
            return Result(OK, "up to date")
        return Result(WARN, f"{n} package(s) upgradable (run: sudo apt upgrade)")
    except Exception:
        return Result(WARN, "could not query apt")


CHECKS: List[Check] = [
    Check("network", "Network configured", "network", c_network),
    Check("dns", "DNS working", "network", c_dns),
    Check("ssh", "SSH running", "network", c_ssh, critical=False),
    Check("containers", "Container runtime", "containers", c_docker),
    Check("compose", "Compose", "containers", c_compose, critical=False),
    Check("kubernetes", "Kubernetes tools", "containers", c_kubernetes, critical=False),
    Check("ansible", "Ansible installed", "automation", c_ansible),
    Check("iac", "Terraform/OpenTofu", "automation", c_iac, critical=False),
    Check("cloud", "Cloud CLI", "cloud", c_cloud, critical=False),
    Check("virtualization", "Virtualization (KVM)", "virtualization", c_virtualization, critical=False),
    Check("firewall", "Firewall", "security", c_firewall, critical=False),
    Check("apparmor", "AppArmor", "security", c_apparmor, critical=False),
    Check("fail2ban", "fail2ban", "security", c_fail2ban, critical=False),
    Check("controller", "Sysible Controller reachable", "controller", c_controller),
    Check("updates", "Updates current", "system", c_updates, critical=False),
]

# Flag → the groups it runs.
GROUP_FLAGS = {
    "network": {"network"},
    "containers": {"containers"},
    "virtualization": {"virtualization"},
    "security": {"security"},
}


def select(groups: Optional[set]) -> List[Check]:
    if not groups:
        return CHECKS
    return [c for c in CHECKS if c.group in groups]


def evaluate(checks: List[Check]) -> List[dict]:
    out = []
    for c in checks:
        try:
            res = c.run()
        except Exception as e:  # a check must never crash the whole run
            res = Result(WARN, f"check errored: {e}")
        out.append({"key": c.key, "label": c.label, "group": c.group,
                    "status": res.status, "detail": res.detail, "critical": c.critical})
    return out
