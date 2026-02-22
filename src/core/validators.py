"""URL validation utilities to prevent SSRF attacks."""

import ipaddress
import socket
from urllib.parse import urlparse

# Blocked Docker internal hostnames
_BLOCKED_HOSTNAMES = {
    "localhost",
    "db",
    "redis",
    "orchestrator",
    "scraper",
    "host.docker.internal",
    "gateway.docker.internal",
    "metadata.google.internal",
}

# Blocked IP ranges (private, loopback, link-local, metadata)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private
    ipaddress.ip_network("172.16.0.0/12"),      # Private (Docker)
    ipaddress.ip_network("192.168.0.0/16"),     # Private
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / AWS IMDS
    ipaddress.ip_network("100.64.0.0/10"),      # Shared address (CGNAT)
    ipaddress.ip_network("0.0.0.0/8"),          # "This" network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def is_internal_url(url: str) -> tuple[bool, str]:
    """Check if a URL points to an internal/private resource.

    Returns:
        Tuple of (is_internal, reason). If is_internal is True,
        the URL should be blocked.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return True, "No hostname in URL"

        # Check blocked hostnames
        hostname_lower = hostname.lower()
        if hostname_lower in _BLOCKED_HOSTNAMES:
            return True, f"Blocked hostname: {hostname}"

        # Check for IP-like hostnames ending with internal TLD patterns
        if hostname_lower.endswith(".internal"):
            return True, f"Internal domain: {hostname}"

        # Resolve hostname to IP addresses
        try:
            addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            # DNS resolution failed - could be non-existent or internal-only domain
            # Allow it through - the scraper will handle the connection error
            return False, ""

        # Check all resolved IPs against blocked ranges
        for addr_info in addr_infos:
            ip_str = addr_info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        return True, f"Hostname {hostname} resolves to blocked IP {ip_str} ({network})"
            except ValueError:
                continue

        return False, ""

    except Exception as e:
        return True, f"URL validation error: {str(e)}"


def validate_scan_url(url: str) -> str:
    """Validate a URL for scanning. Raises ValueError if URL is not safe to scan.

    Returns the validated URL string.
    """
    # Basic scheme check
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme}")

    if not parsed.hostname:
        raise ValueError("URL must have a hostname")

    # SSRF check
    is_internal, reason = is_internal_url(url)
    if is_internal:
        raise ValueError(f"URL points to internal resource: {reason}")

    return url
