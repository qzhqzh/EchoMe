"""Local checks before sending a memory-gate request to an optional model."""

import ipaddress
import re
from urllib.parse import urlsplit

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)

# Deliberately conservative: these signals block transmission, not just storage.
# This is a guard for common credentials, not a complete secret classifier.
_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----",
        r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}"
        r"|github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}"
        r"|glpat-[A-Za-z0-9_-]{12,}|hf_[A-Za-z0-9]{12,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b",
        r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b",
        r"\b(?:bearer|basic)\s+[A-Za-z0-9+/=_-]{8,}",
        r"(?:^|[\s\"'{,;?&])(?:[A-Za-z0-9]+[_-])*(?:password|passwd|pwd|secret|"
        r"token|api[_-]?key|access[_-]?key|private[_-]?key)[\"']?\s*[:=]\s*\S+",
        r"\bsshpass\s+(?:[^\r\n]*?\s)?-p(?:\s*\S+)",
        r"(?:密码|口令|密钥)\s*(?:是|为|[:：=])\s*\S+",
        r"\bhttps?://[^\s/:]+:[^\s/@]+@",
    )
)


def contains_sensitive_input(text: str) -> bool:
    """Return whether input resembles credentials, without retaining its contents."""
    return any(pattern.search(text) is not None for pattern in _SECRET_PATTERNS)


def validate_provider_url(value: str) -> str:
    """Allow configured HTTPS or literal local/private HTTP; never URL credentials."""
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError("Provider URL must be a nonempty URL without whitespace")
    if any(char in value for char in ("?", "#", "\\")):
        raise ValueError("Provider URL cannot contain a query, fragment, or backslash")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Provider URL is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("Provider URL requires HTTP(S), a host, and no credentials")
    if parsed.scheme == "http" and hostname.lower() != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            raise ValueError("HTTP provider URL requires localhost or a private IP") from None
        if not address.is_loopback and not any(
            address.version == network.version and address in network
            for network in _PRIVATE_NETWORKS
        ):
            raise ValueError("HTTP provider URL requires localhost or a private IP")
    return value.rstrip("/")
