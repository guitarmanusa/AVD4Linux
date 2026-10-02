"""Azure Virtual Desktop configuration for AVD4Linux.

Encapsulates the endpoints and FreeRDP 3 flags required to reach Azure Virtual Desktop in
Azure Commercial, Azure US Government (GCC High) and Azure US DoD, including
Smart Card redirection (MS-RDPESC) and Entra ID authentication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CloudProfile:
    """Everything needed to talk to an AVD sovereign cloud."""

    id: str
    label: str
    entry_url: str              # web client entry point (user-facing)
    authority: str              # Entra ID authority endpoint
    cba_authority: str          # Entra ID CBA (client cert) endpoint
    feed_url: str               # AVD ARM feed discovery endpoint
    resource_scope: str         # OAuth2 resource / scope for AVD
    freerdp_gateway_cloud: str  # FreeRDP /gateway:cloud: value
    extra_loader_args: tuple = field(default_factory=tuple)


# Endpoint reference:
#   Commercial: login.microsoftonline.com / certauth.login.microsoftonline.com
#   US Gov / GCC High / DoD: login.microsoftonline.us / certauth.login.microsoftonline.us
CLOUDS = {
    "commercial": CloudProfile(
        id="commercial",
        label="Azure Commercial",
        entry_url="https://rdweb.wvd.microsoft.com/arm/webclient/index.html",
        authority="https://login.microsoftonline.com/",
        cba_authority="https://certauth.login.microsoftonline.com/",
        feed_url="https://rdweb.wvd.microsoft.com/api/arm/feeddiscovery",
        resource_scope="https://wvd.microsoft.com/.default",
        freerdp_gateway_cloud="commercial",
    ),
    "gcc": CloudProfile(
        id="gcc",
        label="Azure US Government (GCC High)",
        entry_url="https://rdweb.wvd.azure.us/arm/webclient/index.html",
        authority="https://login.microsoftonline.us/",
        cba_authority="https://certauth.login.microsoftonline.us/",
        feed_url="https://rdweb.wvd.azure.us/api/arm/feeddiscovery",
        resource_scope="https://www.wvd.azure.us/.default",
        freerdp_gateway_cloud="usgov",
    ),
    "dod": CloudProfile(
        id="dod",
        label="Azure US DoD",
        entry_url="https://rdweb.wvd.azure.us/arm/webclient/index.html",
        authority="https://login.microsoftonline.us/",
        cba_authority="https://certauth.login.microsoftonline.us/",
        feed_url="https://rdweb.wvd.azure.us/api/arm/feeddiscovery",
        resource_scope="https://www.wvd.azure.us/.default",
        freerdp_gateway_cloud="usgov",
    ),
}

CONFIG_DIR = Path.home() / ".config" / "avd4linux"
KEYS: tuple[str, ...] = tuple(CLOUDS)

# Trusted Microsoft AVD gateway and target host domain suffixes.
# Used to validate hosts before routing Entra ID tokens or exposing Smart Card hardware.
# Broad root domains (e.g. microsoft.com) are excluded to prevent subdomains
# on shared Azure AppServices or storage blobs from being treated as trusted gateways.
TRUSTED_AVD_DOMAINS: tuple[str, ...] = (
    "wvd.microsoft.com",
    "rds.microsoft.com",
    "wvd.azure.us",
)

USGOV_AVD_DOMAINS: tuple[str, ...] = (
    "wvd.azure.us",
)


def is_trusted_avd_host(host: str | None) -> bool:
    """Validates whether a hostname belongs to trusted Microsoft AVD infrastructure.

    Used to prevent Confused Deputy token leaks and unauthorized smart card
    redirection when parsing user-supplied .rdp files.
    """
    if not host:
        return False
    clean_host = host.split(":")[0].strip().lower()
    if not clean_host:
        return False
    return any(
        clean_host == domain or clean_host.endswith("." + domain)
        for domain in TRUSTED_AVD_DOMAINS
    )


def is_usgov_avd_host(host: str | None) -> bool:
    """Returns True if host is a verified US Government AVD host."""
    if not host or not is_trusted_avd_host(host):
        return False
    clean_host = host.split(":")[0].strip().lower()
    return any(
        clean_host == domain or clean_host.endswith("." + domain)
        for domain in USGOV_AVD_DOMAINS
    )


def get_cloud(cloud_id: str) -> CloudProfile:
    key = cloud_id.lower()
    if key not in CLOUDS:
        raise KeyError(f"Unknown cloud {cloud_id!r}; choose from {list(CLOUDS)}")
    return CLOUDS[key]


def freerdp_arm_flags(cloud: CloudProfile, token: str | None = None,
                      gateway: str | None = None) -> list[str]:
    """Base FreeRDP 3 flags for AVD ARM gateway + Entra ID auth.

    gateway defaults to the ARM gateway advertised by the AVD feed;
    when a .rdp resource is used, FreeRDP reads it from the file and only
    `/gateway:type:arm` + `/sec:aad` need explicit confirmation.

    Note: Sensitive bearer/access tokens must never be appended as CLI flags
    (e.g. /access-token:) to prevent exposure via the Linux /proc/<pid>/cmdline
    process table; tokens should be fed over the PTY stream or stdin.
    """
    flags = [
        "/gateway:type:arm",
        f"/gateway:cloud:{cloud.freerdp_gateway_cloud}",
        "/sec:aad",
    ]
    if gateway:
        flags.append(f"/gateway:g:{gateway}")
    return flags


def smartcard_flags(reader: str | None = None,
                    smartcard_logon: bool = False) -> list[str]:
    """FreeRDP 3 flags for Smart Card redirection (MS-RDPESC)."""
    flags: list[str] = []
    if reader:
        flags.append(f"/smartcard:{reader}")
    else:
        flags.append("/smartcard")
    if smartcard_logon:
        flags.append("/smartcard-logon")
        flags.append("/sec:nla")
    return flags


def find_freerdp() -> str:
    """Locate the freerdp3 client binary."""
    from .session_manager import find_freerdp3

    found = find_freerdp3()
    if found:
        return found
    for p in ("wlfreerdp3", "sdl-freerdp"):
        import shutil
        located = shutil.which(p)
        if located:
            return located
    raise FileNotFoundError(
        "freerdp3 client not found; install freerdp3-x11/wayland or build the "
        "custom webcam-capable client into /opt/freerdp3-cam"
    )


def build_command(cloud: CloudProfile, resource_rdp: str | None = None,
                  reader: str | None = None,
                  extra: list[str] | None = None) -> list[str]:
    """Compile the full CLI invocation for a session."""
    cmd = [find_freerdp()]
    user = None
    if resource_rdp:
        cmd.append(resource_rdp)
    if user:
        cmd += ["/u:" + user]
    cmd += smartcard_flags(reader)
    if extra:
        cmd += extra
    return cmd