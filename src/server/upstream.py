"""Finding the real Photon Name Server that other games are relayed to."""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)

# The real Photon Name Server, for other games' traffic. Resolved over
# DNS-over-HTTPS: the hosts-file redirect points the name itself at us.
NAME_SERVER_HOST = "ns.exitgames.com"
NAME_SERVER_FALLBACK_IP = "216.120.180.54"
NAME_SERVER_PORT = 4533
_DOH_URLS = (
    f"https://dns.google/resolve?name={NAME_SERVER_HOST}&type=A",
    f"https://cloudflare-dns.com/dns-query?name={NAME_SERVER_HOST}&type=A",
)


def resolve_upstream(spec: str | None = None) -> tuple[str, int]:
    """The Name Server other Photon games are relayed to.

    ``spec`` is ``host`` or ``host:port``; None or ``"auto"`` resolves the
    current IP of ns.exitgames.com via DNS-over-HTTPS, falling back to a
    known address.
    """
    if spec and spec != "auto":
        host, _, port = spec.partition(":")
        return host, int(port) if port else NAME_SERVER_PORT
    for url in _DOH_URLS:
        request = urllib.request.Request(
            url, headers={"Accept": "application/dns-json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                answer = json.loads(response.read())
        except (OSError, ValueError):
            continue
        for record in answer.get("Answer", []):
            if record.get("type") == 1 and record.get("data"):
                return record["data"], NAME_SERVER_PORT
    log.warning(
        "could not resolve %s; using %s", NAME_SERVER_HOST, NAME_SERVER_FALLBACK_IP
    )
    return NAME_SERVER_FALLBACK_IP, NAME_SERVER_PORT
